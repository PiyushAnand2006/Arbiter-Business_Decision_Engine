"""Deterministic discrepancy taxonomy + severity (no LLM).

Reconciliation tools classify every mismatch before anyone reads it, so reviewers
can triage by *kind* of problem, not just by record. The labels come from the
evidence packet alone:

    entry_error           a lone outlier with a typo shape (x10, transposed digits, day/month swap)
    automated_overwrite   the outlier was written by an import bot
    authoritative_update  one side was set by the system of record for that fact (billing -> amount)
    lagging_system        a person changed the value; the other system(s) still hold the old copy
    unexplained           no evidence pattern - the debate has to work harder
    stale_record          every system agrees but the facts decayed below the threshold
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from .normalize import normalize_field, values_equal

BOTS = {"bulk_import_bot", "crm_sync_bot", "billing_system"}

LABELS = {
    "entry_error": "Entry error",
    "automated_overwrite": "Automated overwrite",
    "authoritative_update": "Authoritative update",
    "lagging_system": "Lagging system",
    "unexplained": "Unexplained",
    "stale_record": "Stale record",
}


def origin_of(packet: dict, side: dict) -> Optional[dict]:
    """Most recent audit entry that *originated* a side's value (sync echoes only as a fallback)."""
    fieldname = packet["field"]
    writes = [a for a in packet["audit"]
              if a["field"] == fieldname and a["source"] in side["sources"]
              and values_equal(fieldname, normalize_field(fieldname, a["new"]), side["normalized"], 0.005)]
    originating = [a for a in writes if a["reason"] != "sync"]
    pool = originating or writes
    return max(pool, key=lambda a: a["at"]) if pool else None


def typo_shape(fieldname: str, outlier, reference) -> Optional[str]:
    if outlier is None or reference is None:
        return None
    if fieldname == "value" and reference:
        ratio = outlier / reference
        if 9.5 <= ratio <= 10.5 or 0.095 <= ratio <= 0.105:
            return "an extra or missing zero"
        a, b = str(int(outlier)), str(int(reference))
        if sorted(a) == sorted(b) and a != b:
            return "transposed digits"
    if fieldname == "close_date":
        da, db = date.fromisoformat(outlier), date.fromisoformat(reference)
        if (da.month, da.day) == (db.day, db.month) and da != db:
            return "day and month swapped"
    return None


def classify(packet: dict) -> dict:
    if packet["reason"] == "stale":
        return {"field": "record", "type": "stale_record", "label": LABELS["stale_record"],
                "detail": "All systems agree, but no one has confirmed these facts recently."}
    f = packet["field"]
    a, b = packet["sides"]["A"], packet["sides"]["B"]
    if len(a["sources"]) < len(b["sources"]):
        minority, majority = a, b
    elif len(b["sources"]) < len(a["sources"]):
        minority, majority = b, a
    else:
        minority = majority = None

    def out(kind: str, detail: str) -> dict:
        return {"field": f, "type": kind, "label": LABELS[kind], "detail": detail}

    if minority:
        shape = typo_shape(f, minority["normalized"], majority["normalized"])
        if shape:
            return out("entry_error", f"{', '.join(minority['sources'])} differs by {shape}.")
    for side, other in ((a, b), (b, a)):
        o = origin_of(packet, side)
        if o and o["reason"] == "import":
            return out("automated_overwrite", f"{o['source']} value was written by {o['by']} on {o['at'][:10]}.")
    for side, other in ((a, b), (b, a)):
        o = origin_of(packet, side)
        if o and o["reason"] == "invoice":
            return out("authoritative_update", f"{o['source']} value comes from the issued invoice.")
    by_src = {c["source"]: c for c in packet["candidates"]}
    for side, other in ((a, b), (b, a)):
        o = origin_of(packet, side)
        if o and o["by"] not in BOTS and o["reason"] in ("update", "create", "correction"):
            other_latest = max(by_src[s]["updated_at"] for s in other["sources"])
            if o["at"] > other_latest:
                return out("lagging_system", f"{', '.join(other['sources'])} still hold{'s' if len(other['sources']) == 1 else ''} "
                                             f"the value from before {o['by']}'s change on {o['at'][:10]}.")
    return out("unexplained", "No audit pattern explains the difference.")


def severity(value_at_stake: float, kinds: list[str]) -> str:
    if value_at_stake >= 100_000 or (value_at_stake >= 50_000 and "unexplained" in kinds):
        return "high"
    if value_at_stake >= 25_000:
        return "medium"
    return "low"
