"""Evidence packets (architecture §6.2) - built by code, never by the LLM.

Each packet item carries an ID; agents may only cite those IDs, and the
decision card's evidence lineage is rendered from the same items.
"""
from __future__ import annotations

from typing import Optional

from ..db import audit_evidence_id
from ..engine.assess import SRC_CODE, record_evidence_id
from ..engine.normalize import display_value
from ..schemas import EvidenceItem, FactAssessment

CONTEXT = [("crm", "owner"), ("crm", "last_contacted"), ("finance", "invoice_status"), ("pipeline", "forecast_category")]
FIELD_LABEL = {"stage": "stage", "value": "deal value", "close_date": "close date", "company": "company name"}


def _audit_items(audit: list[dict], fields: set[str], limit: int) -> list[dict]:
    rel = [a for a in audit if a["field"] in fields]
    rel = sorted(rel, key=lambda a: (a["changed_at"], a["id"]))[-limit:]
    return [{"id": audit_evidence_id(a["id"]), "source": a["source"], "field": a["field"], "old": a["old_value"],
             "new": a["new_value"], "at": a["changed_at"], "by": a["changed_by"], "reason": a["reason"]} for a in rel]


def _context(deal_id: str, rows: dict[str, Optional[dict]], extra: list[tuple[str, str]]) -> list[dict]:
    out = []
    for source, field in CONTEXT + extra:
        row = rows.get(source)
        if row and row.get(field) is not None:
            out.append({"id": record_evidence_id(source, deal_id, field), "source": source, "field": field,
                        "value": row[field], "updated_at": row["updated_at"]})
    return out


def _candidates(fact: FactAssessment) -> list[dict]:
    return [{"id": r.evidence_id, "source": r.source, "field": fact.field, "value": r.raw, "normalized_display": r.display,
             "updated_at": r.updated_at, "age_days": round(r.age_days, 1), "freshness": round(r.F, 3),
             "reliability": round(r.R, 3)} for r in fact.readings]


def _finish(packet: dict) -> dict:
    ids = {c["id"] for c in packet["candidates"]} | {a["id"] for a in packet["audit"]} | {c["id"] for c in packet["context"]}
    packet["_evidence_ids"] = ids
    return packet


def build_conflict_packet(fact: FactAssessment, rows: dict, audit: list[dict], company: str, today: str) -> dict:
    a, b = fact.groups[0], fact.groups[1]
    label = FIELD_LABEL.get(fact.field, fact.field)
    extra = [("crm", "stage")] if fact.field != "stage" else []
    sides = {
        "A": {"claim": f"The correct {label} is {a.display} (as recorded in {', '.join(a.sources)}).",
              "value": a.display, "normalized": a.normalized, "sources": a.sources},
        "B": {"claim": f"The correct {label} is {b.display} (as recorded in {', '.join(b.sources)}).",
              "value": b.display, "normalized": b.normalized, "sources": b.sources},
    }
    return _finish({
        "deal_id": fact.deal_id, "company": company, "reason": "conflict", "field": fact.field,
        "fields": [fact.field], "today": today,
        "question": f"Systems disagree on the {label} of deal {fact.deal_id}. Which value is correct?",
        "sides": sides,
        "other_values": [g.display for g in fact.groups[2:]],
        "candidates": _candidates(fact),
        "audit": _audit_items(audit, {fact.field, "invoice_status", "forecast_category"}, 12),
        "context": _context(fact.deal_id, rows, extra),
    })


def build_stale_packet(facts: list[FactAssessment], rows: dict, audit: list[dict], company: str, today: str) -> dict:
    deal_id = facts[0].deal_id
    fields = [f.field for f in facts]
    holds = "; ".join(f"{FIELD_LABEL.get(f.field, f.field)} = {f.groups[0].display}" for f in facts)
    extra = [("crm", x) for x in ("stage", "close_date") if x not in fields]
    sides = {
        "A": {"claim": f"The recorded facts still hold ({holds}); they can be used as-is.",
              "value": "holds", "normalized": "holds", "sources": []},
        "B": {"claim": "The record is too stale to act on; it must be re-verified with the account owner before any decision.",
              "value": "reverify", "normalized": "reverify", "sources": []},
    }
    cands = [c for f in facts for c in _candidates(f)]
    return _finish({
        "deal_id": deal_id, "company": company, "reason": "stale", "field": "record", "fields": fields,
        "today": today,
        "question": f"Every system agrees on deal {deal_id}, but the facts are old. Do they still hold, or must they be re-verified?",
        "sides": sides, "other_values": [],
        "candidates": cands,
        "audit": _audit_items(audit, {"stage", "value", "close_date", "invoice_status", "forecast_category"}, 10),
        "context": _context(deal_id, rows, extra),
    })


def evidence_items(packet: dict) -> list[EvidenceItem]:
    items = []
    for c in packet["candidates"]:
        items.append(EvidenceItem(
            id=c["id"], kind="record", source=c["source"], at=c["updated_at"],
            summary=f"{SRC_CODE[c['source']]} {c['field']} = {c['value']!s} (record updated {c['updated_at'][:10]}, "
                    f"{c['age_days']:.0f}d ago)"))
    for a in packet["audit"]:
        items.append(EvidenceItem(
            id=a["id"], kind="audit", source=a["source"], at=a["at"],
            summary=f"{SRC_CODE[a['source']]} {a['field']}: {a['old']} → {a['new']} by {a['by']} ({a['reason']}) "
                    f"on {a['at'][:10]}"))
    for c in packet["context"]:
        val = c["value"]
        if c["field"] in ("stage",):
            from ..engine.normalize import normalize_field
            val = display_value("stage", normalize_field("stage", val))
        items.append(EvidenceItem(
            id=c["id"], kind="context", source=c["source"], at=c["updated_at"],
            summary=f"{SRC_CODE[c['source']]} {c['field']} = {val}"))
    return items
