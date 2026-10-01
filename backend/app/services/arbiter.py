"""ArbiterService: the application core that API routes and scripts call.

scan()      engine over every deal -> conflicts + decision cards (fast, no LLM)
resolve()   background: evidence packets -> cache | budget | debate -> card
query()     rule-parsed question about one deal -> card (direct or debated)
decide()    human approve / reject -> effects + audit
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from ..agents.debate import provisional_record, run_debate
from ..agents.llm import Budget, LLMClient, make_client
from ..agents.packet import build_conflict_packet, build_stale_packet
from ..data import injector
from ..data.seed import seed_store
from ..db import SOURCE_FIELDS, SOURCE_TABLES, Store, audit_evidence_id
from ..engine.assess import CONTEXT_FIELDS, assess_deal, assess_fact, record_evidence_id
from ..engine.confidence import age_days, freshness, reliability_table, window_start
from ..engine.normalize import PRETTY_STAGE, STAGES, display_value, to_source_format
from ..schemas import ApproveRequest, DebateRecord, FactAssessment, InjectRequest, SourceEdit
from . import approvals as appr
from . import decisions as dec

log = logging.getLogger("arbiter")

FIELD_KEYWORDS = {
    "stage": ["status", "stage", "closed", "won", "lost", "where", "state"],
    "value": ["value", "amount", "worth", "how much", "$", "revenue", "size", "price", "acv"],
    "close_date": ["close date", "closing", "close", "date", "when"],
    "company": ["company", "customer", "account", "who"],
}
PRIORITY_KEYWORDS = ["follow up", "follow-up", "followup", "priorit", "first", "which open deals", "focus", "rank"]


class NotFound(LookupError):
    pass


class ArbiterService:
    def __init__(self, store: Store, cfg, llm: Optional[LLMClient] = None, async_debates: bool = True):
        self.store = store
        self.cfg = cfg
        self.llm = llm or make_client(cfg)
        self.budget = Budget(store, cfg.MAX_DEBATES_PER_SESSION)
        self.async_debates = async_debates
        self.executor = ThreadPoolExecutor(max_workers=cfg.DEBATE_WORKERS, thread_name_prefix="debate") \
            if async_debates else None
        self.monitor_enabled = cfg.MONITOR_ENABLED
        self.fixed_now: Optional[datetime] = None
        self.generation = 0
        self._scan_lock = threading.RLock()
        self._inflight: set[int] = set()
        self._inflight_lock = threading.Lock()

    # ------------------------------------------------------------------ time
    @property
    def clock_offset_days(self) -> float:
        return float(self.store.get_meta("clock_offset_days", 0.0))

    def now(self) -> datetime:
        base = self.fixed_now or datetime.now(timezone.utc)
        return base + timedelta(days=self.clock_offset_days)

    def set_clock(self, offset_days: float) -> dict:
        self.store.set_meta("clock_offset_days", offset_days)
        self.store.log_event(self.now().isoformat(), "clock",
                             f"Clock moved to +{offset_days:g} days" if offset_days else "Clock back to real time",
                             "Confidence recomputed for every fact")
        summary = self.scan()
        return {"offset_days": offset_days, "now": self.now().isoformat(), "scan": summary}

    # ---------------------------------------------------------------- engine
    def reliability(self, now: datetime) -> dict:
        return reliability_table(self.store.audit_since(window_start(now, self.cfg.RELIABILITY_WINDOW_DAYS)),
                                 self.cfg.RELIABILITY_FLOOR)

    def rows(self, deal_id: str) -> dict[str, Optional[dict]]:
        return {s: self.store.source_row(s, deal_id) for s in SOURCE_TABLES}

    @staticmethod
    def company_of(rows: dict) -> str:
        for s in ("crm", "pipeline", "finance"):
            if rows.get(s):
                return rows[s]["company"]
        return "?"

    def assess_all(self, fields: Optional[list[str]] = None) -> tuple[dict[str, list[FactAssessment]], dict]:
        now = self.now()
        rel = self.reliability(now)
        recs = self.store.all_records()
        out = {}
        for did in self.store.deal_ids():
            rows = {s: recs[s].get(did) for s in recs}
            out[did] = assess_deal(did, rows, rel, now, self.cfg, fields)
        return out, recs

    def assess_one(self, deal_id: str, fields: Optional[list[str]] = None) -> list[FactAssessment]:
        rows = self.rows(deal_id)
        if not any(rows.values()):
            raise NotFound(f"Deal {deal_id} does not exist")
        now = self.now()
        return assess_deal(deal_id, rows, self.reliability(now), now, self.cfg, fields)

    # ------------------------------------------------------------------ scan
    @staticmethod
    def signature(deal_id: str, flagged: list[FactAssessment]) -> str:
        return deal_id + "|" + ",".join(sorted(f.conflict_hash for f in flagged))

    def scan(self) -> dict:
        with self._scan_lock:
            t0 = datetime.now(timezone.utc)
            now = self.now()
            facts_by_deal, recs = self.assess_all()
            counts = {"facts": 0, "direct": 0, "conflict": 0, "stale": 0}
            open_hashes: set[str] = set()
            new_ids: list[int] = []
            for did, facts in facts_by_deal.items():
                flagged = [f for f in facts if f.route != "direct"]
                for f in facts:
                    counts["facts"] += 1
                    counts["direct" if f.route == "direct" else f.reason] += 1
                for f in flagged:
                    open_hashes.add(f.conflict_hash)
                    self.store.upsert_conflict(did, f.field, f.reason, f.conflict_hash,
                                               [{"source": r.source, "raw": r.raw, "display": r.display}
                                                for r in f.readings], now.isoformat())
                if not flagged:
                    continue
                sig = self.signature(did, flagged)
                if self.store.find_decision_by_signature(sig):
                    continue
                rows = {s: recs[s].get(did) for s in recs}
                label = ", ".join(f.field.replace("_", " ") for f in flagged)
                query = (f"Reconcile {label} for {did}" if any(f.reason == "conflict" for f in flagged)
                         else f"Re-check stale {label} for {did}")
                card = dec.new_card(did, self.company_of(rows), flagged, "scan", query, now,
                                    datetime.now(timezone.utc), self.cfg, deal_facts=facts)
                card_id = self.store.insert_decision(did, sig, card, now.isoformat())
                self.store.link_conflicts(card["conflict_hashes"], card_id)
                new_ids.append(card_id)
                kind = "conflict" if card["reason"] == "conflict" else "stale record"
                self.store.log_event(now.isoformat(), "detected", f"{kind.capitalize()} detected on {did}",
                                     f"{label} · {card['company']}", did, card_id, card["severity"])
            self.store.close_conflicts_not_in(open_hashes)
            summary = {
                "at": now.isoformat(), "deals": len(facts_by_deal), "facts_scanned": counts["facts"],
                "direct": counts["direct"], "debate": counts["conflict"] + counts["stale"],
                "conflicts": counts["conflict"], "stale": counts["stale"], "new_decisions": new_ids,
                "scan_ms": int((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
            }
            self.store.set_meta("last_scan", summary)
            self._record_trend(summary)
        for card_id in new_ids:
            self.enqueue(card_id)
        return summary

    def _record_trend(self, summary: dict):
        """Keep a short history of open issues (only when something changed, or every 30 s)."""
        hist = self.store.get_meta("scan_history", [])
        point = {"at": summary["at"], "direct": summary["direct"], "conflicts": summary["conflicts"],
                 "stale": summary["stale"]}
        if hist:
            last = hist[-1]
            same = all(last[k] == point[k] for k in ("direct", "conflicts", "stale"))
            recent = (datetime.fromisoformat(point["at"]) - datetime.fromisoformat(last["at"])).total_seconds() < 30
            if same and recent:
                return
        self.store.set_meta("scan_history", (hist + [point])[-120:])

    # ------------------------------------------------------------ debating
    def enqueue(self, card_id: int):
        with self._inflight_lock:
            if card_id in self._inflight:
                return
            self._inflight.add(card_id)
        gen = self.generation
        if self.executor:
            self.executor.submit(self._resolve_safely, card_id, gen)
        else:
            self._resolve_safely(card_id, gen)

    def resume_pending(self):
        for card in self.store.list_decisions(status="debating", limit=500):
            self.enqueue(card["id"])

    def _resolve_safely(self, card_id: int, gen: int):
        try:
            self.resolve(card_id, gen)
        except Exception:  # never let a worker crash silently or kill the dashboard
            log.exception("resolving decision %s failed", card_id)
            card = self.store.get_decision(card_id)
            if card and card["status"] == "debating" and gen == self.generation:
                card["status"] = "needs_review"
                card["status_note"] = "Internal error while debating - review the evidence manually."
                self.store.save_decision(card, self.now().isoformat())
        finally:
            with self._inflight_lock:
                self._inflight.discard(card_id)

    def packets_for(self, deal_id: str, facts: list[FactAssessment]) -> list[dict]:
        rows = self.rows(deal_id)
        audit = self.store.audit_for_deal(deal_id)
        company = self.company_of(rows)
        today = self.now().date().isoformat()
        packets = []
        for f in facts:
            if f.reason == "conflict" and len(f.groups) >= 2:
                p = build_conflict_packet(f, rows, audit, company, today)
                p["_hash"] = f.conflict_hash
                packets.append(p)
        stale = [f for f in facts if f.reason == "stale"]
        if stale:
            p = build_stale_packet(stale, rows, audit, company, today)
            joined = "|".join(sorted(f.conflict_hash for f in stale))
            p["_hash"] = "stale-" + hashlib.sha256(joined.encode()).hexdigest()[:20]
            packets.append(p)
        return packets

    def debate_packet(self, packet: dict, on_stage=None) -> DebateRecord:
        cached = self.store.cached_debate(packet["_hash"])
        if cached:
            rec = DebateRecord.model_validate(cached)
            if set(rec.verdict.evidence_ids) <= packet["_evidence_ids"]:
                rec.cache_hit, rec.llm_calls, rec.duration_ms = True, 0, 0
                self.budget.record_cache_hit()
                return rec
        if not self.budget.try_reserve():
            return provisional_record(packet, "session debate budget exhausted")
        high_stakes = packet.get("_stake", 0.0) >= self.cfg.CONSISTENCY_CHECK_MIN_STAKE
        rec = run_debate(packet, self.llm, self.cfg.MAX_CALLS_PER_CONFLICT, consistency_check=high_stakes,
                         on_stage=on_stage)
        self.budget.record_calls(rec.llm_calls)
        if rec.fallback_used:
            self.budget.record_fallback()
        else:
            self.store.cache_debate(packet["_hash"], packet["deal_id"], packet["field"], rec.model_dump(),
                                    rec.llm_calls, rec.provider, rec.model, self.now().isoformat())
        return rec

    def resolve(self, card_id: int, gen: Optional[int] = None):
        card = self.store.get_decision(card_id)
        if not card or card["status"] != "debating":
            return
        deal_id = card["deal_id"]
        deal_facts = self.assess_one(deal_id)
        facts = [f for f in deal_facts if f.field in card["fields"]]
        packets = self.packets_for(deal_id, facts)
        stake = (card.get("risk_hint") or {}).get("value_at_stake", 0.0)
        records = []
        for i, p in enumerate(packets):
            p["_stake"] = stake
            records.append(self.debate_packet(
                p, on_stage=lambda s, i=i, p=p: self._progress(card_id, gen, p["field"], s, i, len(packets))))
        if gen is not None and gen != self.generation:
            return  # dataset was reset while we were debating
        card = dec.assemble(card, facts, packets, records, self.now(), datetime.now(timezone.utc), self.cfg,
                            deal_facts=deal_facts)
        self.store.save_decision(card, self.now().isoformat())
        verdict = "needs review" if card["status"] == "needs_review" else "verdict ready"
        answer = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in card["answer"].items() if v)
        self.store.log_event(self.now().isoformat(), "resolved", f"{deal_id} {verdict}", answer, deal_id,
                             card_id, card["severity"])
        self._maybe_alert(card)

    def _progress(self, card_id: int, gen: Optional[int], field: str, stage: str, index: int, total: int):
        """Expose the live debate stage (arguing -> judging -> verifying) to the dashboard."""
        if gen is not None and gen != self.generation:
            return
        card = self.store.get_decision(card_id)
        if card and card["status"] == "debating":
            card["progress"] = {"field": field, "stage": stage, "index": index, "total": total}
            self.store.save_decision(card, self.now().isoformat())

    def _maybe_alert(self, card: dict):
        """Optional Slack-compatible webhook for verdicts at or above ALERT_MIN_SEVERITY."""
        url = self.cfg.ALERT_WEBHOOK_URL
        rank = {"low": 0, "medium": 1, "high": 2}
        if not url or rank.get(card.get("severity") or "low", 0) < rank.get(self.cfg.ALERT_MIN_SEVERITY, 2):
            return
        labels = ", ".join(d["label"] for d in card.get("discrepancies", []))
        text = (f"Arbiter · {card['severity']} severity · {card['deal_id']} {card['company']}: {labels}. "
                f"Proposed: {', '.join(f'{k} {v}' for k, v in card['answer'].items() if v)}. "
                f"Waiting for approval (decision #{card['id']}).")
        try:
            import httpx
            httpx.post(url, json={"text": text, "decision_id": card["id"], "deal_id": card["deal_id"],
                                  "severity": card["severity"]}, timeout=5)
            self.store.log_event(self.now().isoformat(), "alert", f"Alert sent for {card['deal_id']}", text,
                                 card["deal_id"], card["id"], card["severity"])
        except Exception as e:  # alerts must never break the pipeline
            log.warning("alert webhook failed: %s", e)

    # ----------------------------------------------------------------- query
    def parse_query(self, q: str) -> tuple[Optional[str], list[str]]:
        m = re.search(r"\bD\s?-?(\d{4})\b", q, re.I)
        deal_id = f"D{m.group(1)}" if m else None
        ql = q.lower()
        fields = [f for f, kws in FIELD_KEYWORDS.items() if any(k in ql for k in kws)]
        if "close_date" in fields and "stage" in fields and not any(k in ql for k in ("status", "stage", "won", "lost")):
            fields.remove("stage")
        return deal_id, fields or ["stage", "value", "close_date"]

    def query(self, q: str) -> dict:
        deal_id, fields = self.parse_query(q)
        if not deal_id:
            if any(k in q.lower() for k in PRIORITY_KEYWORDS):
                return {"type": "priorities", "query": q, **self.priorities()}
            raise ValueError("Mention a deal ID (for example D1042), or ask which open deals to follow up first.")
        deal_facts = self.assess_one(deal_id)
        facts = [f for f in deal_facts if f.field in fields]
        # If these exact conflicts already have an open decision, answer with it instead of duplicating it.
        hashes = {f.conflict_hash for f in facts if f.route != "direct"}
        if hashes:
            for existing in self.store.list_decisions(deal_id=deal_id, limit=50):
                if existing["status"] in appr.OPEN_STATES and hashes <= set(existing.get("conflict_hashes", [])):
                    return {"type": "decision", "query": q, "reused": True, "card": self.public_card(existing)}
        now = self.now()
        rows = self.rows(deal_id)
        card = dec.new_card(deal_id, self.company_of(rows), facts, "query", q, now, datetime.now(timezone.utc),
                            self.cfg, deal_facts=deal_facts)
        sig = f"query|{deal_id}|{now.isoformat()}|{q}"
        card_id = self.store.insert_decision(deal_id, sig, card, now.isoformat())
        if card["status"] == "debating":
            self.enqueue(card_id)
        return {"type": "decision", "query": q, "card": self.public_card(self.store.get_decision(card_id))}

    # ------------------------------------------------------------- decisions
    def public_card(self, card: dict) -> dict:
        now = self.now()
        out = {k: v for k, v in card.items() if not k.startswith("_")}
        out["expired"] = dec.is_expired(card, now)
        return out

    SUMMARY_KEYS = ("id", "deal_id", "company", "query", "origin", "fields", "path", "reason", "answer",
                    "confidence", "confidence_field", "status", "status_note", "created_at", "resolved_at", "expires_at", "expired",
                    "time_to_decision_ms", "risk_hint", "decided_at", "severity", "discrepancies", "progress")

    def list_decisions(self, status: Optional[str] = None, path: Optional[str] = None,
                       deal_id: Optional[str] = None, limit: int = 200, summary: bool = False) -> list[dict]:
        cards = [self.public_card(c) for c in self.store.list_decisions(status, path, deal_id, limit)]
        if not summary:
            return cards
        out = []
        for c in cards:
            s = {k: c.get(k) for k in self.SUMMARY_KEYS}
            s["cache_hits"] = sum(1 for d in c["debates"] if d.get("cache_hit"))
            s["llm_calls"] = sum(d.get("llm_calls", 0) for d in c["debates"])
            s["fallback"] = any(d.get("fallback_used") for d in c["debates"])
            out.append(s)
        return out

    def get_decision(self, card_id: int) -> dict:
        card = self.store.get_decision(card_id)
        if not card:
            raise NotFound(f"Decision #{card_id} not found")
        return self.public_card(card)

    def decide(self, card_id: int, req: ApproveRequest) -> dict:
        with self._scan_lock:
            card = self.store.get_decision(card_id)
            if not card:
                raise NotFound(f"Decision #{card_id} not found")
            appr.check_transition(card, req)
            now = self.now()
            if req.action == "reject":
                effect = "Rejected - no data changed; the disagreement stays flagged for follow-up."
                card["status"] = "rejected"
            else:
                effect = appr.apply_effects(self.store, card, req.actor, now, self.cfg.NUMERIC_TOLERANCE)
                card["status"] = "approved"
                # a sync / re-confirmation resets freshness, so the sunset timer restarts
                card["expires_at"] = dec.expiry(self.assess_one(card["deal_id"], card["fields"]), now,
                                                self.cfg).isoformat()
            approval = self.store.insert_approval(card_id, req.action, req.actor, req.note, effect, now.isoformat())
            verb = "approved" if req.action == "approve" else "rejected"
            self.store.log_event(now.isoformat(), verb, f"{card['deal_id']} {verb} by {req.actor}",
                                 effect.replace("Action taken: ", ""), card["deal_id"], card_id, card.get("severity"))
            card["approvals"] = [*card.get("approvals", []), approval]
            card["status_note"] = effect
            card["decided_at"] = now.isoformat()
            self.store.save_decision(card, now.isoformat())
            if req.action == "approve":
                for other in self.store.list_decisions(deal_id=card["deal_id"], limit=500):
                    if other["id"] != card_id and other["status"] in appr.OPEN_STATES and appr.overlaps(card, other):
                        other["status"] = "superseded"
                        other["status_note"] = f"Superseded by decision #{card_id} ({req.actor} approved it)."
                        self.store.save_decision(other, now.isoformat())
                self.scan()
        return self.public_card(card)

    # ------------------------------------------------------------ priorities
    def priorities(self) -> dict:
        facts_by_deal, recs = self.assess_all(["stage", "value", "close_date"])
        today = self.now().date()
        ranked, flagged = [], []
        for did, facts in facts_by_deal.items():
            by = {f.field: f for f in facts}
            stage = by["stage"].groups[0].normalized if by["stage"].groups else None
            if stage not in ("prospecting", "qualification", "proposal", "negotiation"):
                continue
            value = by["value"].groups[0].normalized or 0.0
            prob = self.cfg.STAGE_WIN_PROB.get(stage, 0.3)
            crm = recs["crm"].get(did) or {}
            lc = crm.get("last_contacted")
            days = (today - date.fromisoformat(lc)).days if lc else 99
            urgency = 1 - freshness(days, self.cfg.HALF_LIFE_DAYS.get("last_contacted", 7))
            conf = min(f.confidence for f in facts)
            flags = [f"{f.field.replace('_', ' ')} {'conflict' if f.reason == 'conflict' else 'is stale'}"
                     for f in facts if f.route != "direct"]
            if conf < self.cfg.THRESH_LOW and not flags:
                flags.append("low confidence")
            item = {
                "deal_id": did, "company": crm.get("company") or "?", "stage": PRETTY_STAGE.get(stage, stage),
                "value": value, "value_display": display_value("value", value), "win_probability": prob,
                "days_since_contact": days, "urgency": round(urgency, 3),
                "score": round(value * prob * (0.35 + 0.65 * urgency), 2), "confidence": conf, "flags": flags,
                "owner": crm.get("owner"),
                "evidence_ids": [record_evidence_id("crm", did, "stage"), record_evidence_id("crm", did, "value"),
                                 record_evidence_id("crm", did, "last_contacted")],
                "why": (f"{display_value('value', value)} × {prob:.0%} win probability; last contact {days} day"
                        f"{'s' if days != 1 else ''} ago"),
            }
            (flagged if flags else ranked).append(item)
        ranked.sort(key=lambda x: -x["score"])
        for i, item in enumerate(ranked, 1):
            item["rank"] = i
        flagged.sort(key=lambda x: -x["score"])
        return {"ranked": ranked[:15], "flagged": flagged,
                "method": "score = value × stage win probability × (0.35 + 0.65 × contact urgency); deals with "
                          "conflicting or stale facts are listed separately instead of being silently ranked."}

    # ----------------------------------------------------------------- deals
    def deals(self) -> list[dict]:
        facts_by_deal, recs = self.assess_all()
        out = []
        for did, facts in facts_by_deal.items():
            crm = recs["crm"].get(did) or {}
            out.append({
                "deal_id": did, "company": crm.get("company"), "owner": crm.get("owner"),
                "min_confidence": min(f.confidence for f in facts),
                "status": ("conflict" if any(f.reason == "conflict" for f in facts)
                           else "stale" if any(f.reason == "stale" for f in facts) else "clean"),
                # systems holding a minority value on any conflicted fact
                "outliers": sorted({r.source for f in facts if f.reason == "conflict" and f.groups
                                    for r in f.readings if r.source not in f.groups[0].sources}),
                "updated_at": max((r.updated_at for f in facts for r in f.readings), default=None),
                "facts": {f.field: {"display": f.groups[0].display if f.groups else None, "route": f.route,
                                    "reason": f.reason, "confidence": f.confidence, "conflicted": f.conflicted,
                                    "values": [g.display for g in f.groups]} for f in facts},
            })
        return out

    def deal_detail(self, deal_id: str) -> dict:
        rows = self.rows(deal_id)
        if not any(rows.values()):
            raise NotFound(f"Deal {deal_id} does not exist")
        now = self.now()
        rel = self.reliability(now)
        gated = assess_deal(deal_id, rows, rel, now, self.cfg)
        context = []
        for source, fields in CONTEXT_FIELDS.items():
            row = rows.get(source)
            for f in fields:
                if row and f != "owner":
                    fa = assess_fact(deal_id, f, {source: row}, rel, now, self.cfg)
                    context.append(fa.model_dump())
        audit = [{**a, "evidence_id": audit_evidence_id(a["id"])} for a in self.store.audit_for_deal(deal_id)]
        return {
            "deal_id": deal_id, "company": self.company_of(rows), "rows": rows,
            "facts": [f.model_dump() for f in gated], "context_facts": context,
            "audit": list(reversed(audit))[:40], "decisions": self.list_decisions(deal_id=deal_id, limit=20),
        }

    def source_table(self, source: str) -> dict:
        if source not in SOURCE_TABLES:
            raise NotFound(f"Unknown source {source}")
        return {"source": source, "fields": SOURCE_FIELDS[source], "rows": self.store.source_rows(source)}

    def edit_source(self, source: str, deal_id: str, edit: SourceEdit) -> dict:
        if source not in SOURCE_TABLES:
            raise NotFound(f"Unknown source {source}")
        if edit.field not in SOURCE_FIELDS[source]:
            raise ValueError(f"{source} has no editable field {edit.field!r}")
        if not self.store.source_row(source, deal_id):
            raise NotFound(f"{source} has no deal {deal_id}")
        old = self.store.source_row(source, deal_id)[edit.field]
        audit_id = self.store.update_source_field(source, deal_id, edit.field, edit.value, self.now().isoformat(),
                                                  edit.actor or "presenter", "update")
        self.store.log_event(self.now().isoformat(), "edit", f"{source.capitalize()} record edited · {deal_id}",
                             f"{edit.field}: {old} → {edit.value} by {edit.actor or 'presenter'}", deal_id)
        return {"row": self.store.source_row(source, deal_id), "audit_id": audit_evidence_id(audit_id)}

    # ------------------------------------------------------------------ demo
    def inject_drift(self, req: InjectRequest) -> dict:
        n_prev = int(self.store.get_meta("drifts", 0))
        deal_id = req.deal_id
        if deal_id is None:
            facts_by_deal, _ = self.assess_all()
            heroes = {injector.HERO_CLEAN, injector.HERO_CONFLICT, injector.HERO_STALE}
            clean = sorted(d for d, fs in facts_by_deal.items()
                           if d not in heroes and all(f.route == "direct" for f in fs))
            if not clean:
                raise ValueError("No clean deals left to drift - reset the demo data.")
            deal_id = clean[(n_prev * 7 + 3) % len(clean)]
        rows = self.rows(deal_id)
        if not rows.get("crm"):
            raise NotFound(f"Deal {deal_id} does not exist")
        plan = injector.plan_drift(rows, deal_id, req.field, req.source, n_prev, self.now().date())
        new_raw = to_source_format(plan["source"], plan["field"], plan["new"], company_hint=rows["crm"]["company"])
        old_raw = rows[plan["source"]][plan["field"]]
        audit_id = self.store.update_source_field(plan["source"], deal_id, plan["field"], new_raw,
                                                  self.now().isoformat(), plan["by"], plan["reason"])
        self.store.set_meta("drifts", n_prev + 1)
        self.store.log_event(self.now().isoformat(), "drift", f"Drift injected into {deal_id}",
                             f"{plan['source']}.{plan['field']}: {old_raw} → {new_raw} ({plan['story']})", deal_id)
        return {"deal_id": deal_id, "source": plan["source"], "field": plan["field"], "old": old_raw,
                "new": new_raw, "story": plan["story"], "audit_id": audit_evidence_id(audit_id)}

    def reset(self, clear_debate_cache: bool = False) -> dict:
        with self._scan_lock:
            self.generation += 1
            truth = seed_store(self.store, now=self.fixed_now, clear_debate_cache=clear_debate_cache,
                               ground_truth_path=self.cfg.GROUND_TRUTH_PATH)
            self.store.log_event(self.now().isoformat(), "reset", "Demo data reseeded",
                                 f"{truth['n_deals']} deals across CRM, Finance and Pipeline")
        summary = self.scan()
        return {"deals": truth["n_deals"], "injected": len(truth["items"]), "scan": summary,
                "debate_cache_kept": not clear_debate_cache}

    def set_monitor(self, enabled: bool):
        self.monitor_enabled = enabled
        return {"enabled": enabled}

    # ----------------------------------------------------------------- stats
    def stats(self) -> dict:
        cards = self.store.list_decisions(limit=5000)
        by_status: dict[str, int] = {}
        by_path: dict[str, int] = {}
        for c in cards:
            by_status[c["status"]] = by_status.get(c["status"], 0) + 1
            by_path[c["path"]] = by_path.get(c["path"], 0) + 1
        ttd = [c["time_to_decision_ms"] for c in cards if c.get("time_to_decision_ms") and c["path"] != "direct"]
        conflicts = self.store.open_conflicts()
        return {
            "last_scan": self.store.get_meta("last_scan"),
            "open_conflicts": sum(1 for c in conflicts if c["reason"] == "conflict"),
            "open_stale": sum(1 for c in conflicts if c["reason"] == "stale"),
            "decisions_by_status": by_status, "decisions_by_path": by_path,
            "avg_time_to_decision_ms": int(sum(ttd) / len(ttd)) if ttd else None,
            "budget": self.budget.snapshot(), "debate_cache_size": self.store.debate_cache_size(),
            "provider": self.llm.provider, "model": self.llm.model,
            "monitor_enabled": self.monitor_enabled, "clock_offset_days": self.clock_offset_days,
            "now": self.now().isoformat(), "seeded_at": self.store.get_meta("seeded_at"),
            "history": self.store.get_meta("scan_history", []),
            "review": self._review_metrics(cards),
        }

    @staticmethod
    def _review_metrics(cards: list[dict]) -> dict:
        """Decision analytics: how the human side of the loop is doing."""
        decided = [c for c in cards if c["status"] in ("approved", "rejected")]
        approved = sum(1 for c in decided if c["status"] == "approved")
        waits = []
        for c in decided:
            if c.get("resolved_at") and c.get("decided_at"):
                waits.append((datetime.fromisoformat(c["decided_at"]) -
                              datetime.fromisoformat(c["resolved_at"])).total_seconds())
        debated = [c for c in cards if c["path"] != "direct"]
        kinds: dict[str, int] = {}
        for c in debated:
            for d in c.get("discrepancies", []):
                kinds[d["label"]] = kinds.get(d["label"], 0) + 1
        return {
            "decided": len(decided), "approved": approved,
            "approval_rate": round(approved / len(decided), 3) if decided else None,
            # share of debated decisions the engine flagged for close review (fallback, judge unsure, swap disagreement)
            "flagged_rate": round(sum(1 for c in debated if any(d["verdict"]["needs_human_review"]
                                                               for d in c["debates"])) / len(debated), 3)
            if debated else None,
            "median_review_s": sorted(waits)[len(waits) // 2] if waits else None,
            "by_type": kinds,
            "by_severity": {s: sum(1 for c in debated if c.get("severity") == s and c["status"] in appr.OPEN_STATES)
                            for s in ("high", "medium", "low")},
        }

    # -------------------------------------------------------------- activity
    def activity(self, limit: int = 40) -> list[dict]:
        return self.store.events(limit)

    def source_health(self) -> list[dict]:
        """Per-system scorecard, in the spirit of truth-discovery source trust estimation."""
        facts_by_deal, _ = self.assess_all()
        now = self.now()
        corrections = self.store.corrections_by_source(window_start(now, self.cfg.RELIABILITY_WINDOW_DAYS))
        stats = {s: {"facts": 0, "agree": 0, "outlier": 0, "stale": 0, "ages": [], "R": []} for s in SOURCE_TABLES}
        for facts in facts_by_deal.values():
            for f in facts:
                top = set(f.groups[0].sources) if f.groups else set()
                for r in f.readings:
                    st = stats[r.source]
                    st["facts"] += 1
                    st["agree"] += r.source in top
                    st["outlier"] += f.reason == "conflict" and r.source not in top
                    st["stale"] += f.reason == "stale"
                    st["ages"].append(r.age_days)
                    st["R"].append(r.R)
        lost: dict[str, int] = {s: 0 for s in SOURCE_TABLES}
        for card in self.store.list_decisions(limit=5000):
            for d in card["debates"]:
                w = d["verdict"]["winner"]
                if d["reason"] == "conflict" and w in ("A", "B"):
                    for s in (d["side_b"] if w == "A" else d["side_a"])["sources"]:
                        lost[s] = lost.get(s, 0) + 1
        out = []
        for s, st in stats.items():
            ages = sorted(st["ages"])
            out.append({
                "source": s, "facts": st["facts"],
                "agreement_rate": round(st["agree"] / st["facts"], 4) if st["facts"] else None,
                "reliability": round(sum(st["R"]) / len(st["R"]), 4) if st["R"] else None,
                "median_age_days": round(ages[len(ages) // 2], 1) if ages else None,
                "open_outliers": st["outlier"], "stale_facts": st["stale"],
                "debates_lost": lost.get(s, 0), "corrections_90d": corrections.get(s, 0),
            })
        return out

    def export_csv(self) -> str:
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["decision_id", "deal_id", "company", "fields", "reason", "discrepancy", "severity", "status",
                    "answer", "confidence", "exposure", "created_at", "resolved_at", "decided_at", "decided_by",
                    "effect"])
        for c in reversed(self.store.list_decisions(limit=5000)):
            last = (c.get("approvals") or [{}])[-1]
            w.writerow([c["id"], c["deal_id"], c["company"], " ".join(c["fields"]), c["reason"],
                        "; ".join(d["label"] for d in c.get("discrepancies", [])), c.get("severity") or "",
                        c["status"], "; ".join(f"{k}={v}" for k, v in c["answer"].items()), c["confidence"],
                        (c.get("risk_hint") or {}).get("exposure", ""), c["created_at"], c.get("resolved_at") or "",
                        c.get("decided_at") or "", last.get("actor", ""), last.get("effect", "")])
        return buf.getvalue()

    def shutdown(self):
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
