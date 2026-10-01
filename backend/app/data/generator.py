"""Synthetic systems of record for "Northwind Systems" (FR-1).

Builds ~50 deals that exist in three systems (CRM, Finance, Pipeline tracker),
each system storing the same facts in its own format, plus an audit log with a
realistic change history. Fully deterministic for a given (seed, now).

Truth lives in canonical form in `DatasetBuilder.src[source][deal_id]`; rows are
rendered into each system's native format only at the end (`render`).
"""
from __future__ import annotations

import random
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from faker import Faker

from ..engine.normalize import STAGES, to_source_format

SYSTEMS = ("crm", "finance", "pipeline")
SHARED_FIELDS = ("company", "stage", "value", "close_date")
FORECAST = {"prospecting": "pipeline", "qualification": "pipeline", "proposal": "best_case",
            "negotiation": "commit", "closed_won": "closed", "closed_lost": "omitted"}
SYNC_BOT = "crm_sync_bot"
IMPORT_BOT = "bulk_import_bot"
BILLING = "billing_system"


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def invoice_for(stage: str, rng: random.Random) -> str:
    if stage == "closed_won":
        return rng.choice(["invoiced", "paid"])
    if stage == "closed_lost":
        return "void"
    return "not_invoiced"


class DatasetBuilder:
    def __init__(self, seed: int, n_deals: int, now: datetime):
        self.seed = seed
        self.rng = random.Random(seed)
        self.fake = Faker("en_US")
        self.fake.seed_instance(seed)
        self.now = now.astimezone(timezone.utc).replace(microsecond=0)
        self.n_deals = n_deals
        self.deals: dict[str, dict] = {}                     # canonical base facts
        self.src: dict[str, dict[str, dict]] = {s: {} for s in SYSTEMS}
        self.updated: dict[str, dict[str, datetime]] = {s: {} for s in SYSTEMS}
        self.audit: list[dict] = []
        self.finance_staff: list[str] = []

    # ----------------------------------------------------------------- utils
    def ago(self, days: float) -> datetime:
        return self.now - timedelta(days=days)

    def fmt(self, source: str, field: str, value: Any, deal_id: Optional[str] = None) -> Optional[str]:
        if value is None:
            return None
        hint = self.deals[deal_id]["company"] if (deal_id and field == "company") else None
        return to_source_format(source, field, value, company_hint=hint)

    def log(self, source: str, deal_id: str, field: str, old: Any, new: Any, at: datetime,
            by: str, reason: str):
        self.audit.append({
            "source": source, "deal_id": deal_id, "field": field,
            "old_value": self.fmt(source, field, old, deal_id) if field in SHARED_FIELDS else old,
            "new_value": self.fmt(source, field, new, deal_id) if field in SHARED_FIELDS else new,
            "changed_at": iso(at), "changed_by": by, "reason": reason,
        })

    def set_fact(self, source: str, deal_id: str, field: str, new: Any, at: datetime, by: str,
                 reason: str, log: bool = True):
        old = self.src[source][deal_id].get(field)
        self.src[source][deal_id][field] = new
        if log:
            self.log(source, deal_id, field, old, new, at, by, reason)
        if at > self.updated[source][deal_id]:
            self.updated[source][deal_id] = at

    # ------------------------------------------------------------------ base
    def build_base(self):
        rng, fake = self.rng, self.fake
        used: set[str] = set()
        self.finance_staff = [f"{fake.first_name()[0].lower()}.{fake.last_name().lower()} (finance)" for _ in range(4)]
        for i in range(self.n_deals):
            deal_id = f"D{1001 + i}"
            company = fake.company()
            while company in used:
                company = fake.company()
            used.add(company)
            stage = rng.choices(STAGES, weights=[7, 10, 12, 13, 7, 2])[0]
            value = float(rng.randrange(160, 5000) * 50)
            if stage.startswith("closed"):
                close = self.now.date() - timedelta(days=rng.randint(3, 40))
            else:
                close = self.now.date() + timedelta(days=rng.randint(12, 120))
            self.deals[deal_id] = {
                "deal_id": deal_id, "company": company, "owner": fake.name(), "stage": stage,
                "value": value, "close_date": close.isoformat(),
                "last_contacted": (self.now.date() - timedelta(days=rng.randint(0, 8))).isoformat(),
                "invoice_status": invoice_for(stage, rng), "forecast_category": FORECAST[stage],
            }

    def build_history(self):
        """Stage progression + syncs + a few import/correction pairs (reliability signal)."""
        rng = self.rng
        correction_rate = {"crm": 0.12, "finance": 0.05, "pipeline": 0.30}
        for deal_id, d in self.deals.items():
            created = self.ago(rng.uniform(55, 95))
            history_end = self.ago(31)
            for s in SYSTEMS:
                self.src[s][deal_id] = {}
                self.updated[s][deal_id] = created
            # creation
            first_stage = "prospecting"
            initial_value = float(round(d["value"] * rng.uniform(0.85, 1.0) / 50) * 50)
            for s in SYSTEMS:
                by = d["owner"] if s == "crm" else SYNC_BOT
                reason = "create" if s == "crm" else "sync"
                at = created if s == "crm" else created + timedelta(hours=rng.uniform(1, 6))
                self.set_fact(s, deal_id, "company", d["company"], at, by, reason, log=False)
                self.set_fact(s, deal_id, "stage", first_stage, at, by, reason)
                self.set_fact(s, deal_id, "value", initial_value, at, by, reason)
                self.set_fact(s, deal_id, "close_date", d["close_date"], at, by, reason, log=False)
            # progression to current stage
            target = d["stage"]
            path = STAGES[1:STAGES.index("negotiation") + 1] if target == "closed_lost" else STAGES[1:STAGES.index(target) + 1]
            if target == "closed_lost":
                path = path[: rng.randint(1, len(path))] + ["closed_lost"]
            span = (history_end - created).total_seconds()
            steps = [created + timedelta(seconds=span * (k + 1) / (len(path) + 1)) for k in range(len(path))]
            for new_stage, at in zip(path, steps):
                for s in SYSTEMS:
                    by = d["owner"] if s == "crm" else SYNC_BOT
                    lag = timedelta(hours=0 if s == "crm" else rng.uniform(1, 20))
                    self.set_fact(s, deal_id, "stage", new_stage, at + lag, by, "update" if s == "crm" else "sync")
            if initial_value != d["value"]:
                at = steps[len(steps) // 2] if steps else created + timedelta(days=2)
                for s in SYSTEMS:
                    by = d["owner"] if s == "crm" else SYNC_BOT
                    lag = timedelta(hours=0 if s == "crm" else rng.uniform(1, 20))
                    self.set_fact(s, deal_id, "value", d["value"], at + lag, by, "update" if s == "crm" else "sync")
            # import mistakes that were later corrected -> historical correction rate
            for s in SYSTEMS:
                if rng.random() < correction_rate[s]:
                    field = rng.choice(["stage", "value"])
                    t0 = self.ago(rng.uniform(34, 85))
                    good = self.src[s][deal_id][field]
                    bad = (good * rng.choice([0.9, 1.1])) if field == "value" else rng.choice(STAGES[:3])
                    if bad != good:
                        self.log(s, deal_id, field, good, bad, t0, IMPORT_BOT, "import")
                        self.log(s, deal_id, field, bad, good, t0 + timedelta(hours=rng.uniform(3, 30)),
                                 d["owner"] if s == "crm" else rng.choice(self.finance_staff) if s == "finance" else SYNC_BOT,
                                 "correction")
            # recent housekeeping touches (records are actively maintained)
            for s in SYSTEMS:
                self.updated[s][deal_id] = max(self.updated[s][deal_id], self.ago(self.rng.uniform(0.3, 10)))

    # ---------------------------------------------------------------- render
    def render(self) -> dict:
        rng = random.Random(self.seed + 7)  # cosmetic noise stream, independent of injection
        out: dict[str, list[dict]] = {s: [] for s in SYSTEMS}
        for deal_id, d in self.deals.items():
            for s in SYSTEMS:
                f = self.src[s][deal_id]
                row = {
                    "deal_id": deal_id,
                    "company": self.fmt(s, "company", f["company"], deal_id),
                    "stage": self.fmt(s, "stage", f["stage"]),
                    "value": self.fmt(s, "value", f["value"]),
                    "close_date": self.fmt(s, "close_date", f["close_date"]),
                    "updated_at": iso(self.updated[s][deal_id]),
                }
                # cosmetic-only noise: must never be flagged as a conflict
                roll = rng.random()
                if s == "crm" and roll < 0.25:
                    row["value"] = f"{f['value']:.2f}"
                if s == "finance" and roll < 0.20 and f["stage"] == "closed_won":
                    row["stage"] = "WON"
                if s == "pipeline" and roll < 0.30 and f["value"] >= 20000:
                    row["value"] = str(int(round(f["value"] / 100.0) * 100))
                if s == "pipeline" and 0.30 <= roll < 0.50 and not re.search(r"(Inc|LLC|Ltd|PLC|Group)\.?$", row["company"]):
                    row["company"] = row["company"] + " Inc."
                if s == "finance" and 0.50 <= roll < 0.65:
                    row["company"] = row["company"].title() + "."
                if s == "crm":
                    row.update(owner=d["owner"], last_contacted=f.get("last_contacted", d["last_contacted"]))
                elif s == "finance":
                    row["invoice_status"] = f.get("invoice_status", d["invoice_status"])
                else:
                    row["forecast_category"] = f.get("forecast_category", FORECAST[f["stage"]])
                out[s].append(row)
        return {**out, "audit": sorted(self.audit, key=lambda a: a["changed_at"])}


def build_base_dataset(seed: int, n_deals: int, now: datetime) -> DatasetBuilder:
    b = DatasetBuilder(seed, n_deals, now)
    b.build_base()
    b.build_history()
    return b


def today(now: datetime) -> date:
    return now.astimezone(timezone.utc).date()
