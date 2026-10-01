"""Human approval state machine (FR-7).

    debating -> pending_approval | needs_review -> approved | rejected   (terminal)

Nothing is marked "action taken" without an explicit approval, and every
approval/rejection is logged. The "action" on approval is a sync of the
synthetic source systems to the reconciled value, written with an audit entry
("arbiter_sync"), which also lowers the reliability of the source that was
wrong. Stale "holds" verdicts re-confirm the record; "re-verify" verdicts
create a follow-up task instead of changing data.
"""
from __future__ import annotations

from datetime import datetime

from ..db import SOURCE_FIELDS, Store
from ..engine.normalize import normalize_field, to_source_format, values_equal
from ..schemas import ApproveRequest

APPROVABLE = {"pending_approval", "needs_review"}
OPEN_STATES = {"debating", "pending_approval", "needs_review"}


class TransitionError(ValueError):
    pass


def check_transition(card: dict, req: ApproveRequest):
    if card["status"] not in APPROVABLE:
        raise TransitionError(
            f"Decision #{card['id']} is '{card['status']}'. Only decisions that are pending approval or need "
            f"review can be approved or rejected.")


def apply_effects(store: Store, card: dict, actor: str, now: datetime, tolerance: float) -> str:
    at = now.isoformat()
    by = f"arbiter (approved by {actor})"
    deal_id = card["deal_id"]
    lines: list[str] = []
    for rec in card["debates"]:
        v = rec["verdict"]
        if rec["reason"] == "conflict":
            fieldname = rec["field"]
            if v["winner"] not in ("A", "B"):
                lines.append(f"{fieldname}: no value chosen - escalated to the deal owner")
                continue
            side = rec["side_a"] if v["winner"] == "A" else rec["side_b"]
            target = side["normalized"]
            crm = store.source_row("crm", deal_id)
            for source in ("crm", "finance", "pipeline"):
                if fieldname not in SOURCE_FIELDS[source]:
                    continue
                row = store.source_row(source, deal_id)
                if row is None:
                    continue
                if values_equal(fieldname, normalize_field(fieldname, row[fieldname]), target, tolerance):
                    continue
                new_raw = to_source_format(source, fieldname, target, company_hint=crm["company"] if crm else None)
                store.update_source_field(source, deal_id, fieldname, new_raw, at, by, "arbiter_sync")
                lines.append(f"{source}.{fieldname} → {new_raw}")
            if not any(l.startswith(tuple(f"{s}.{fieldname}" for s in ("crm", "finance", "pipeline"))) for l in lines):
                lines.append(f"{fieldname}: systems already agree - nothing to sync")
        else:
            if v["winner"] == "A":
                for source in ("crm", "finance", "pipeline"):
                    if store.source_row(source, deal_id):
                        store.touch_source(source, deal_id, at)
                        with store.tx() as c:
                            c.execute(
                                "INSERT INTO audit_log(source,deal_id,field,old_value,new_value,changed_at,changed_by,reason)"
                                " VALUES(?,?,?,?,?,?,?,?)", [source, deal_id, "record", None, "verified", at, by, "verified"])
                lines.append("record re-confirmed in all systems (freshness reset)")
            else:
                owner = (store.source_row("crm", deal_id) or {}).get("owner", "the deal owner")
                lines.append(f"re-verification task created for {owner}")
    return "Action taken: " + "; ".join(lines) if lines else "Approved - no data change required."


def overlaps(a: dict, b: dict) -> bool:
    return bool(set(a.get("conflict_hashes", [])) & set(b.get("conflict_hashes", []))) or (
        a["deal_id"] == b["deal_id"] and bool(set(a["fields"]) & set(b["fields"])) and b["status"] in OPEN_STATES)
