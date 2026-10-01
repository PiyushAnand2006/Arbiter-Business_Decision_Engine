"""Decision card assembly (architecture §7): answer, objective confidence,
evidence lineage, debate summary, counterfactual, risk hint, sunset timer.

The counterfactual is derived from the losing side's argument plus the judge's
stated reason - it is not a separate LLM call. Confidence always comes from the
engine (the chosen value's freshness/reliability/agreement), never the judge.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import mean
from typing import Optional

from ..agents.packet import evidence_items
from ..engine.classify import classify, severity
from ..engine.confidence import combine, validity_days
from ..engine.normalize import normalize_field
from ..schemas import (Counterfactual, DebateRecord, EvidenceItem, FactAssessment, FactSummary, RiskHint)

FIELD_LABEL = {"stage": "Stage", "value": "Value", "close_date": "Close date", "company": "Company"}


def fact_summary(f: FactAssessment) -> dict:
    return FactSummary(field=f.field, route=f.route, reason=f.reason, confidence=f.confidence, F=f.F, R=f.R, A=f.A,
                       groups=f.groups, readings=f.readings).model_dump()


def record_evidence(f: FactAssessment) -> list[EvidenceItem]:
    return [EvidenceItem(id=r.evidence_id, kind="record", source=r.source, at=r.updated_at,
                         summary=f"{r.source.upper()} {f.field} = {r.raw} (record updated {r.updated_at[:10]}, "
                                 f"{r.age_days:.0f}d ago)") for r in f.readings]


def side_confidence(f: FactAssessment, sources: list[str], cfg) -> tuple[float, float, float, float]:
    """Objective confidence of the value held by `sources` (the winning side)."""
    rs = [r for r in f.readings if r.source in sources]
    if not rs:
        return f.confidence, f.F, f.R, f.A
    F = max(r.F for r in rs)
    R = mean(r.R for r in rs)
    A = len(rs) / max(1, len(f.readings))
    return combine(F, R, A, cfg.WEIGHTS), round(F, 4), round(R, 4), round(A, 4)


def risk_hint(facts: list[FactAssessment], confidence: float, cfg) -> Optional[RiskHint]:
    by = {f.field: f for f in facts}
    val_f, stage_f = by.get("value"), by.get("stage")
    values = [g.normalized for g in val_f.groups if isinstance(g.normalized, (int, float))] if val_f else []
    stages = [g.normalized for g in stage_f.groups] if stage_f else []
    if not values:
        return None
    value = max(values)
    prob = max((cfg.STAGE_WIN_PROB.get(s, 0.3) for s in stages), default=0.3)
    at_stake = value * prob
    exposure = at_stake * (1 - confidence)
    note = f"${value:,.0f} × {prob:.0%} win probability = ${at_stake:,.0f} expected revenue"
    if len(values) > 1:
        note += f"; ${max(values) - min(values):,.0f} disputed between systems"
    return RiskHint(value_at_stake=round(at_stake, 2), win_probability=prob, exposure=round(exposure, 2), note=note)


def new_card(deal_id: str, company: str, facts: list[FactAssessment], origin: str, query: str,
             now: datetime, real_now: datetime, cfg, deal_facts: Optional[list[FactAssessment]] = None) -> dict:
    """`facts` are the ones this card decides; `deal_facts` (all of the deal's facts) price the risk."""
    flagged = [f for f in facts if f.route != "direct"]
    weakest = min(facts, key=lambda f: f.confidence)
    reason = "conflict" if any(f.reason == "conflict" for f in flagged) else ("stale" if flagged else "clean")
    evidence = [e.model_dump() for f in facts for e in record_evidence(f)]
    risk = risk_hint(deal_facts or facts, weakest.confidence, cfg)
    card = {
        "id": 0, "deal_id": deal_id, "company": company, "query": query, "origin": origin,
        "fields": [f.field for f in facts],
        "path": "debate" if flagged else "direct",
        "reason": reason,
        "answer": {f.field: (f.groups[0].display if f.route == "direct" and f.groups else None) for f in facts},
        "confidence": weakest.confidence,
        "confidence_breakdown": {"F": weakest.F, "R": weakest.R, "A": weakest.A},
        "confidence_field": weakest.field,
        "facts": [fact_summary(f) for f in facts],
        "evidence": evidence,
        "debates": [], "counterfactuals": [],
        "risk_hint": risk.model_dump() if risk else None,
        "status": "debating" if flagged else "informational",
        "status_note": ("Debate queued - the data disagrees or has decayed below the confidence threshold."
                        if flagged else "All systems agree and the data is fresh - answered directly, no debate."),
        "created_at": now.isoformat(), "resolved_at": None if flagged else now.isoformat(),
        "expires_at": None, "expired": False,
        "time_to_decision_ms": None if flagged else 0,
        "decided_at": None,
        "conflict_hashes": sorted(f.conflict_hash for f in flagged if f.conflict_hash),
        "approvals": [],
        "discrepancies": [],
        "severity": severity(risk.value_at_stake if risk else 0.0, []) if flagged else None,
        "progress": None,
        "_created_real": real_now.isoformat(),
    }
    if not flagged:
        card["expires_at"] = expiry(facts, now, cfg).isoformat()
    return card


def expiry(facts: list[FactAssessment], now: datetime, cfg, overrides: Optional[dict] = None) -> datetime:
    """Sunset timer: when the weakest fact's confidence will decay below the threshold.

    validity window (from a fresh verification) minus the current age of the
    freshest record supporting the answer. Already-decayed facts expire now.
    """
    days = []
    for f in facts:
        R, A, F = (overrides or {}).get(f.field, (f.R, f.A, f.F))
        half_life = cfg.HALF_LIFE_DAYS.get(f.field, 30)
        window = validity_days(half_life, R, A, cfg.WEIGHTS, cfg.THRESH_LOW)
        age = -half_life * math.log2(max(F, 1e-9))
        days.append(window - age)
    return now + timedelta(days=min(days) if days else 7)


def _argument_text(arg) -> Optional[str]:
    if not arg:
        return None
    claims = arg["claims"] if isinstance(arg, dict) else [c.model_dump() for c in arg.claims]
    pos = arg["position"] if isinstance(arg, dict) else arg.position
    return pos + (" " + claims[0]["text"] if claims else "")


def assemble(card: dict, facts: list[FactAssessment], packets: list[dict], records: list[DebateRecord],
             now: datetime, real_now: datetime, cfg, deal_facts: Optional[list[FactAssessment]] = None) -> dict:
    by_field = {f.field: f for f in facts}
    answer: dict[str, Optional[str]] = {}
    scored: list[tuple[float, float, float, float, str]] = []
    overrides: dict[str, tuple[float, float]] = {}
    counterfactuals: list[dict] = []
    notes: list[str] = []
    review = provisional = False

    for f in facts:
        if f.route == "direct":
            answer[f.field] = f.groups[0].display if f.groups else None
            scored.append((f.confidence, f.F, f.R, f.A, f.field))

    evidence: dict[str, dict] = {e["id"]: e for e in card.get("evidence", [])}
    cited: set[str] = set()
    for packet, rec in zip(packets, records):
        v = rec.verdict
        cited.update(v.evidence_ids)
        for e in evidence_items(packet):
            evidence.setdefault(e.id, e.model_dump())
        if rec.provider == "rules" and not rec.cache_hit:
            provisional = True
        if rec.fallback_used and rec.provider != "rules":
            notes.append(f"{rec.field}: judge output unusable - rule-based fallback applied")
        if v.needs_human_review:
            review = True
        loser = None
        if v.winner in ("A", "B"):
            loser = "B" if v.winner == "A" else "A"

        if packet["reason"] == "conflict":
            f = by_field[packet["field"]]
            if v.winner in ("A", "B"):
                side = packet["sides"][v.winner]
                answer[f.field] = side["value"]
                C, F, R, A = side_confidence(f, side["sources"], cfg)
                overrides[f.field] = (R, A, F)
            else:
                answer[f.field] = None
                C, F, R, A = f.confidence, f.F, f.R, f.A
                notes.append(f"{f.field}: judge could not decide - needs a human")
            scored.append((C, F, R, A, f.field))
            losers = [loser] if loser else ["A", "B"]
            for lb in losers:
                ls = packet["sides"][lb]
                arg = rec.challenger if lb == "B" else rec.proponent
                weaknesses = []
                win_arg = rec.proponent if lb == "B" else rec.challenger
                if win_arg is not None and loser:
                    weaknesses = win_arg.weaknesses_of_other_side[:2]
                why = v.reasoning if loser else "Not chosen: the judge found the evidence inconclusive."
                new_points = [w for w in weaknesses if w not in why]
                if new_points:
                    why += " Rebuttal from the winning side: " + " ".join(new_points)
                counterfactuals.append(Counterfactual(
                    field=f.field, rejected_value=ls["value"], rejected_sources=ls["sources"],
                    why_it_lost=why, losing_argument=_argument_text(arg)).model_dump())
        else:  # stale record review
            for fname in packet["fields"]:
                f = by_field[fname]
                disp = f.groups[0].display if f.groups else None
                answer[fname] = disp if v.winner == "A" else (f"{disp} (re-verify)" if disp else None)
                scored.append((f.confidence, f.F, f.R, f.A, f.field))
            human = {"holds": "Use the recorded values as-is", "reverify": "Re-verify the record before acting"}
            if loser:
                ls = packet["sides"][loser]
                arg = rec.challenger if loser == "B" else rec.proponent
                counterfactuals.append(Counterfactual(
                    field="record", rejected_value=human[ls["value"]], rejected_sources=[],
                    why_it_lost=v.reasoning, losing_argument=_argument_text(arg)).model_dump())
            if v.winner != "A":
                notes.append("Stale record: re-verification recommended")

    for eid, e in evidence.items():
        e["cited"] = eid in cited
    weakest = min(scored, key=lambda t: t[0]) if scored else (card["confidence"], 0, 0, 0, card.get("confidence_field"))
    card.update(
        answer={k: answer.get(k) for k in card["fields"]},
        confidence=weakest[0],
        confidence_breakdown={"F": weakest[1], "R": weakest[2], "A": weakest[3]},
        confidence_field=weakest[4],
        facts=[fact_summary(f) for f in facts],
        evidence=sorted(evidence.values(), key=lambda e: (not e["cited"], e["kind"] != "record", e["id"])),
        debates=[r.model_dump() for r in records],
        counterfactuals=counterfactuals,
        path="provisional" if provisional else ("debate" if records else "direct"),
        resolved_at=now.isoformat(),
        expires_at=expiry(facts, now, cfg, overrides).isoformat(),
    )
    risk = risk_hint(deal_facts or facts, card["confidence"], cfg)
    card["risk_hint"] = risk.model_dump() if risk else None
    card["discrepancies"] = [classify(p) for p in packets]
    card["severity"] = severity(risk.value_at_stake if risk else 0.0, [d["type"] for d in card["discrepancies"]])
    card["progress"] = None
    created_real = datetime.fromisoformat(card.get("_created_real", real_now.isoformat()))
    card["time_to_decision_ms"] = int((real_now - created_real).total_seconds() * 1000)
    if provisional:
        card["status"] = "needs_review"
        card["status_note"] = ("Provisional answer - the session debate budget is spent, so a majority-and-recency "
                               "rule decided. Review carefully before approving.")
    elif not records:
        card["status"] = "informational"
        card["status_note"] = "The disagreement cleared before the debate ran - answered directly."
    elif review or notes:
        card["status"] = "needs_review"
        card["status_note"] = "; ".join(notes) or "The judge flagged residual uncertainty - review before approving."
    else:
        card["status"] = "pending_approval"
        card["status_note"] = "Verdict ready - waiting for human approval. Nothing changes until someone approves."
    return card


def is_expired(card: dict, now: datetime) -> bool:
    exp = card.get("expires_at")
    return bool(exp) and datetime.fromisoformat(exp) < now and card["status"] != "debating"


def parse_for_compare(field: str, display: str):
    return normalize_field(field, display)
