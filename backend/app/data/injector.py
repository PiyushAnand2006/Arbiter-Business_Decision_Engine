"""Deterministic conflict + staleness injection, returning ground truth (FR-1).

Each pattern is a realistic way systems drift apart, with an audit trail that
makes the true value recoverable from evidence alone:

  hero_crm_ahead        D1042: CRM closed the deal 2 days ago, finance still "open" (stage + value)
  crm_ahead_minority    CRM advanced the stage; finance *and* pipeline are stale copies (majority is wrong)
  import_regression     a bulk import bot knocked the pipeline stage backwards (most-recent is wrong)
  finance_lost          finance marked the deal lost + voided the invoice; CRM untouched for weeks
  crm_amended           rep amended the value in CRM, pipeline synced, finance lags
  finance_invoiced      billing issued the invoice at a different amount (minority, authoritative)
  value_typo_x10        a finance user added a zero                     (most-recent is wrong)
  value_typo_transpose  a finance user transposed two digits            (most-recent is wrong)
  date_slipped_majority rep pushed the close date in CRM, pipeline synced, finance lags
  date_slipped_minority rep pushed the close date in the pipeline tracker only
  date_import_swap      an import swapped day/month in finance          (most-recent is wrong)
  stale_open            every system agrees but nobody touched the deal for 60-90 days -> re-verify
  stale_closed_won      old but closed + paid: the record should hold

The ground truth is written to a separate file and is never read by the
engine or the agents - only by the evaluation script.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from ..engine.normalize import STAGES, display_value
from .generator import BILLING, FORECAST, IMPORT_BOT, SYNC_BOT, DatasetBuilder

HERO_CLEAN, HERO_CONFLICT, HERO_STALE = "D1007", "D1042", "D1019"

PLAN = [
    ("crm_ahead_minority", 2), ("import_regression", 2), ("finance_lost", 1),
    ("crm_amended", 2), ("finance_invoiced", 1), ("value_typo_x10", 1), ("value_typo_transpose", 1),
    ("date_slipped_majority", 1), ("date_slipped_minority", 1), ("date_import_swap", 1),
    ("stale_open", 3), ("stale_closed_won", 1),
]


def _round50(v: float) -> float:
    return float(round(v / 50.0) * 50)


def _transpose(v: float) -> float:
    s = str(int(v))
    return float(s[1] + s[0] + s[2:])


# --------------------------------------------------------------------------- #
# Phase 1 - before history: choose deals and pin the base facts patterns need
# --------------------------------------------------------------------------- #
def prepare(b: DatasetBuilder) -> None:
    rng, now = b.rng, b.now.date()
    ids = list(b.deals)
    heroes = [x for x in (HERO_CLEAN, HERO_CONFLICT, HERO_STALE) if x in b.deals]
    pool = [x for x in ids if x not in heroes]
    rng.shuffle(pool)
    b.plan = {}
    if HERO_CONFLICT in b.deals:
        b.plan[HERO_CONFLICT] = "hero_crm_ahead"
    if HERO_STALE in b.deals:
        b.plan[HERO_STALE] = "stale_open"
    for pattern, count in PLAN:
        if pattern == "stale_open" and HERO_STALE in b.deals:
            count -= 1
        for _ in range(count):
            if pool:
                b.plan[pool.pop()] = pattern

    for deal_id, pattern in b.plan.items():
        d = b.deals[deal_id]

        def open_stage(stage: str):
            d.update(stage=stage, forecast_category=FORECAST[stage], invoice_status="not_invoiced")
            if date.fromisoformat(d["close_date"]) < now + timedelta(days=10):
                d["close_date"] = (now + timedelta(days=rng.randint(20, 90))).isoformat()

        if pattern == "hero_crm_ahead":
            open_stage("negotiation")
            d.update(value=45000.0, close_date=(now + timedelta(days=21)).isoformat())
        elif pattern == "stale_open":
            open_stage("negotiation" if deal_id == HERO_STALE else "proposal")
            if deal_id == HERO_STALE:
                d.update(value=72500.0, close_date=(now - timedelta(days=12)).isoformat())
            else:
                d["close_date"] = (now + rng.choice([-9, 25]) * timedelta(days=1)).isoformat()
        elif pattern == "stale_closed_won":
            d.update(stage="closed_won", forecast_category="closed", invoice_status="paid",
                     close_date=(now - timedelta(days=80)).isoformat())
        elif pattern == "crm_ahead_minority":
            open_stage("proposal")
        elif pattern in ("import_regression", "finance_lost"):
            open_stage("negotiation" if pattern == "finance_lost" else rng.choice(["proposal", "negotiation"]))
        elif pattern in ("crm_amended", "date_slipped_majority", "date_slipped_minority"):
            if d["stage"].startswith("closed"):
                open_stage(rng.choice(["proposal", "negotiation"]))
        elif pattern == "finance_invoiced":
            d.update(stage="closed_won", forecast_category="closed", invoice_status="not_invoiced",
                     close_date=(now - timedelta(days=5)).isoformat())
        elif pattern == "value_typo_x10":
            if d["stage"].startswith("closed"):
                open_stage("negotiation")
            d["value"] = _round50(rng.uniform(12000, 58000))
        elif pattern == "value_typo_transpose":
            if d["stage"].startswith("closed"):
                open_stage("proposal")
            v = _round50(rng.uniform(21000, 98000))
            while str(int(v))[0] == str(int(v))[1] or str(int(v))[1] == "0":
                v = _round50(rng.uniform(21000, 98000))
            d["value"] = v
        elif pattern == "date_import_swap":
            if d["stage"].startswith("closed"):
                open_stage("negotiation")
            target = now + timedelta(days=rng.randint(35, 100))
            while target.day > 12 or target.day == target.month:
                target += timedelta(days=1)
            d["close_date"] = target.isoformat()


# --------------------------------------------------------------------------- #
# Phase 2 - after history: apply the drift and record ground truth
# --------------------------------------------------------------------------- #
def _shift_history(b: DatasetBuilder, deal_id: str, days: float) -> None:
    from .generator import iso
    from ..engine.confidence import parse_ts
    for a in b.audit:
        if a["deal_id"] == deal_id:
            a["changed_at"] = iso(parse_ts(a["changed_at"]) - timedelta(days=days))


def inject(b: DatasetBuilder) -> dict:
    rng, T = b.rng, b.ago
    staff = b.finance_staff
    truth: list[dict] = []

    def gt(deal_id, field, pattern, value, wrong, kind="conflict", expected="resolve"):
        truth.append({
            "deal_id": deal_id, "field": field, "kind": kind, "pattern": pattern,
            "truth": value, "truth_display": display_value(field, value) if field != "record" else expected,
            "wrong_sources": wrong, "expected_verdict": expected,
        })

    def lag(source: str, deal_id: str, lo: float, hi: float):
        b.updated[source][deal_id] = T(rng.uniform(lo, hi))

    for deal_id, pattern in b.plan.items():
        d = b.deals[deal_id]
        owner, base = d["owner"], dict(d)

        if pattern == "hero_crm_ahead":
            b.set_fact("crm", deal_id, "stage", "closed_won", T(2.1), owner, "update")
            b.set_fact("crm", deal_id, "value", 48000.0, T(2.05), owner, "update")
            b.src["crm"][deal_id]["last_contacted"] = T(2).date().isoformat()
            b.set_fact("pipeline", deal_id, "stage", "closed_won", T(1.6), SYNC_BOT, "sync")
            b.set_fact("pipeline", deal_id, "value", 48000.0, T(1.6), SYNC_BOT, "sync")
            b.src["pipeline"][deal_id]["forecast_category"] = "closed"
            b.log("pipeline", deal_id, "forecast_category", "commit", "closed", T(1.6), SYNC_BOT, "sync")
            b.updated["finance"][deal_id] = T(16)
            gt(deal_id, "stage", pattern, "closed_won", ["finance"])
            gt(deal_id, "value", pattern, 48000.0, ["finance"])

        elif pattern == "crm_ahead_minority":
            t = T(rng.uniform(1, 3))
            b.set_fact("crm", deal_id, "stage", "negotiation", t, owner, "update")
            b.src["crm"][deal_id]["last_contacted"] = t.date().isoformat()
            lag("finance", deal_id, 12, 20)
            lag("pipeline", deal_id, 12, 20)
            gt(deal_id, "stage", pattern, "negotiation", ["finance", "pipeline"])

        elif pattern == "import_regression":
            earlier = STAGES[: STAGES.index(base["stage"])]
            b.set_fact("pipeline", deal_id, "stage", rng.choice(earlier[:2]), T(rng.uniform(0.6, 1.4)), IMPORT_BOT, "import")
            lag("crm", deal_id, 3, 8)
            lag("finance", deal_id, 3, 8)
            gt(deal_id, "stage", pattern, base["stage"], ["pipeline"])

        elif pattern == "finance_lost":
            who = rng.choice(staff)
            b.set_fact("finance", deal_id, "stage", "closed_lost", T(2), who, "update")
            b.src["finance"][deal_id]["invoice_status"] = "void"
            b.log("finance", deal_id, "invoice_status", "not_invoiced", "void", T(2), who, "update")
            lag("crm", deal_id, 24, 27)
            lag("pipeline", deal_id, 23, 26)
            b.src["crm"][deal_id]["last_contacted"] = T(26).date().isoformat()
            gt(deal_id, "stage", pattern, "closed_lost", ["crm", "pipeline"])

        elif pattern == "crm_amended":
            new = _round50(base["value"] * rng.choice([0.85, 0.9, 1.1, 1.15, 1.2]))
            t = T(rng.uniform(1.5, 3))
            b.set_fact("crm", deal_id, "value", new, t, owner, "update")
            b.set_fact("pipeline", deal_id, "value", new, t + timedelta(hours=6), SYNC_BOT, "sync")
            lag("finance", deal_id, 13, 20)
            gt(deal_id, "value", pattern, new, ["finance"])

        elif pattern == "finance_invoiced":
            new = _round50(base["value"] * rng.uniform(1.04, 1.09))
            b.set_fact("finance", deal_id, "value", new, T(3), BILLING, "invoice")
            b.src["finance"][deal_id]["invoice_status"] = "invoiced"
            b.log("finance", deal_id, "invoice_status", "not_invoiced", "invoiced", T(3), BILLING, "invoice")
            lag("crm", deal_id, 21, 28)
            lag("pipeline", deal_id, 20, 27)
            gt(deal_id, "value", pattern, new, ["crm", "pipeline"])

        elif pattern in ("value_typo_x10", "value_typo_transpose"):
            bad = base["value"] * 10 if pattern == "value_typo_x10" else _transpose(base["value"])
            b.set_fact("finance", deal_id, "value", bad, T(rng.uniform(0.7, 1.2)), rng.choice(staff), "update")
            lag("crm", deal_id, 4, 9)
            lag("pipeline", deal_id, 4, 9)
            gt(deal_id, "value", pattern, base["value"], ["finance"])

        elif pattern == "date_slipped_majority":
            new = (date.fromisoformat(base["close_date"]) + timedelta(days=rng.randint(30, 60))).isoformat()
            t = T(rng.uniform(1.5, 3))
            b.set_fact("crm", deal_id, "close_date", new, t, owner, "update")
            b.set_fact("pipeline", deal_id, "close_date", new, t + timedelta(hours=5), SYNC_BOT, "sync")
            lag("finance", deal_id, 14, 22)
            gt(deal_id, "close_date", pattern, new, ["finance"])

        elif pattern == "date_slipped_minority":
            new = (date.fromisoformat(base["close_date"]) + timedelta(days=rng.randint(30, 60))).isoformat()
            b.set_fact("pipeline", deal_id, "close_date", new, T(rng.uniform(1, 2)), owner, "update")
            lag("crm", deal_id, 15, 24)
            lag("finance", deal_id, 15, 24)
            gt(deal_id, "close_date", pattern, new, ["crm", "finance"])

        elif pattern == "date_import_swap":
            good = date.fromisoformat(base["close_date"])
            bad = date(good.year, good.day, good.month).isoformat()
            b.set_fact("finance", deal_id, "close_date", bad, T(0.8), IMPORT_BOT, "import")
            gt(deal_id, "close_date", pattern, base["close_date"], ["finance"])

        elif pattern in ("stale_open", "stale_closed_won"):
            age = 70.0 if deal_id == HERO_STALE else rng.uniform(62, 88)
            _shift_history(b, deal_id, age - 25)
            for s, jitter in zip(("crm", "finance", "pipeline"), (0.0, 1.5, 0.8)):
                b.updated[s][deal_id] = T(age + jitter)
            b.src["crm"][deal_id]["last_contacted"] = T(age + 1).date().isoformat()
            expected = "reverify" if pattern == "stale_open" else "holds"
            gt(deal_id, "record", pattern, expected, [], kind="stale", expected=expected)

    return {
        "seed": b.seed,
        "generated_at": b.now.isoformat(),
        "n_deals": b.n_deals,
        "items": truth,
        "clean_deals": sorted(set(b.deals) - set(b.plan)),
        "heroes": {"clean": HERO_CLEAN, "conflict": HERO_CONFLICT, "stale": HERO_STALE},
    }


# --------------------------------------------------------------------------- #
# Live demo drift (FR-9): applied straight to the store, with an audit trail
# --------------------------------------------------------------------------- #
DRIFT_ROTATION = ["value", "stage", "close_date"]


def plan_drift(records: dict, deal_id: str, field: Optional[str], source: Optional[str],
               n_previous: int, now_date: date) -> dict:
    """Decide what drift to apply. `records` = {source: row} for the deal (raw rows)."""
    from ..engine.normalize import normalize_field

    field = field or DRIFT_ROTATION[n_previous % len(DRIFT_ROTATION)]
    crm = records["crm"]
    if field == "value":
        good = normalize_field("value", crm["value"])
        src = source or "finance"
        return {"source": src, "field": "value", "new": good * 10, "by": "a.kim (finance)" if src == "finance" else "presenter",
                "reason": "update", "story": f"{src} value typed with an extra zero"}
    if field == "stage":
        good = normalize_field("stage", crm["stage"])
        idx = STAGES.index(good) if good in STAGES else 3
        new = STAGES[max(0, min(idx, 4) - 2)] if good != "prospecting" else "negotiation"
        src = source or "pipeline"
        return {"source": src, "field": "stage", "new": new, "by": IMPORT_BOT, "reason": "import",
                "story": f"bulk import overwrote the {src} stage"}
    good = date.fromisoformat(normalize_field("close_date", crm["close_date"]))
    new = good + timedelta(days=45)
    src = source or "pipeline"
    return {"source": src, "field": "close_date", "new": new.isoformat(), "by": "presenter", "reason": "update",
            "story": f"{src} close date pushed out 45 days"}
