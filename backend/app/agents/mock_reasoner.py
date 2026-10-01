"""Deterministic stand-in for an LLM (dev / CI / offline demo; zero quota).

It reads ONLY the evidence packet - never the ground truth - and weighs the
same signals the judge prompt describes (human vs bot changes, recency, typo
shapes, corroborating context). Output is shaped exactly like a model's JSON
reply, so it goes through the same validator as real providers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ..engine.classify import origin_of
from ..engine.normalize import normalize_field

BOTS = {"bulk_import_bot", "crm_sync_bot", "billing_system"}
OPEN = {"prospecting", "qualification", "proposal", "negotiation"}


@dataclass
class Finding:
    weight: float
    text: str
    ids: list[str] = field(default_factory=list)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _d(s: str) -> str:
    return s[:10]


def _days(n: float) -> str:
    n = round(n)
    return f"{n} day{'s' if n != 1 else ''}"


def _ctx(packet: dict, fieldname: str) -> dict | None:
    return next((c for c in packet["context"] if c["field"] == fieldname), None)


# --------------------------------------------------------------------------- #
# Conflicts
# --------------------------------------------------------------------------- #
_origin = origin_of  # shared with the deterministic classifier


def _conflict_findings(packet: dict) -> dict[str, list[Finding]]:
    fieldname = packet["field"]
    sides = packet["sides"]
    cands = packet["candidates"]
    out: dict[str, list[Finding]] = {"A": [], "B": []}
    for me, other in (("A", "B"), ("B", "A")):
        s, o = sides[me], sides[other]
        my_c = [c for c in cands if c["source"] in s["sources"]]
        ot_c = [c for c in cands if c["source"] in o["sources"]]
        my_ids = [c["id"] for c in my_c]
        ot_latest = max((c["updated_at"] for c in ot_c), default="")
        f = out[me]

        if len(s["sources"]) > len(o["sources"]):
            f.append(Finding(0.8, f"{len(s['sources'])} of {len(cands)} systems ({', '.join(s['sources'])}) "
                                  f"agree on {s['value']}.", my_ids))

        origin = _origin(packet, s)
        if origin:
            by, reason = origin["by"], origin["reason"]
            if reason == "import":
                f.append(Finding(-2.5, f"{s['value']} in {origin['source']} was written by {by} (automated import) "
                                       f"on {_d(origin['at'])}, overwriting {origin['old']}.", [origin["id"]]))
            elif reason == "invoice":
                f.append(Finding(2.5, f"{origin['source']} amount was set by {by} from the issued invoice on "
                                      f"{_d(origin['at'])}; billing is authoritative for invoiced amounts.", [origin["id"]]))
            elif by not in BOTS and reason in ("update", "create", "correction"):
                if origin["at"] > ot_latest:
                    f.append(Finding(2.0, f"{by} changed {fieldname} from {origin['old']} to {origin['new']} in "
                                          f"{origin['source']} on {_d(origin['at'])}, after the other side's records "
                                          f"were last updated ({_d(ot_latest)}).",
                                     [origin["id"], *[c["id"] for c in ot_c]]))
                    # ...which makes the other side a stale copy of the previous value
                    out[other].append(Finding(-0.3, f"{', '.join(o['sources'])} still show{'s' if len(o['sources']) == 1 else ''} "
                                                    f"{o['value']}, last updated {_d(ot_latest)} - before {by}'s change on "
                                                    f"{_d(origin['at'])}, so it is a stale copy of the previous value.",
                                              [*[c["id"] for c in ot_c], origin["id"]]))
                else:
                    f.append(Finding(0.4, f"{s['value']} was entered by {by} on {_d(origin['at'])}.", [origin["id"]]))

        # entry-error shapes, only for a lone outlier
        if len(s["sources"]) < len(o["sources"]):
            a, b = s["normalized"], o["normalized"]
            if fieldname == "value" and a and b:
                ratio = a / b
                if 9.5 <= ratio <= 10.5 or 0.095 <= ratio <= 0.105:
                    f.append(Finding(-2.5, f"{s['value']} is ~10x the value in {', '.join(o['sources'])} "
                                           f"({o['value']}): a likely extra or missing zero.", my_ids))
                elif sorted(str(int(a))) == sorted(str(int(b))) and int(a) != int(b):
                    f.append(Finding(-2.0, f"{s['value']} has the same digits as {o['value']} in a different order: "
                                           f"a likely transposition typo.", my_ids))
            if fieldname == "close_date" and a and b:
                da, db = date.fromisoformat(a), date.fromisoformat(b)
                if (da.month, da.day) == (db.day, db.month) and da != db:
                    f.append(Finding(-2.0, f"{a} is {b} with day and month swapped: a likely import formatting error.",
                                     my_ids))

        if fieldname == "stage":
            inv = _ctx(packet, "invoice_status")
            if inv:
                v = s["normalized"]
                if v == "closed_won" and inv["value"] in ("invoiced", "paid"):
                    f.append(Finding(1.0, f"Finance invoice status is '{inv['value']}', consistent with a won deal.", [inv["id"]]))
                if v == "closed_lost" and inv["value"] == "void":
                    f.append(Finding(1.5, "Finance voided the invoice, consistent with a lost deal.", [inv["id"]]))
                if v in OPEN and inv["value"] == "void":
                    f.append(Finding(-1.0, "Finance voided the invoice, which contradicts an open deal.", [inv["id"]]))
            fc = _ctx(packet, "forecast_category")
            if fc and s["normalized"] == "closed_won" and fc["value"] == "closed" and "pipeline" not in s["sources"]:
                f.append(Finding(0.4, "Pipeline forecast category is 'closed'.", [fc["id"]]))
            lc = _ctx(packet, "last_contacted")
            if lc and "crm" in s["sources"] and s["normalized"] in OPEN:
                days = (date.fromisoformat(packet["today"]) - date.fromisoformat(lc["value"])).days
                if days > 20:
                    f.append(Finding(-0.6, f"CRM shows no customer contact for {days} days while the deal is still open.",
                                     [lc["id"]]))

        my_f = max((c["freshness"] for c in my_c), default=0.0)
        ot_f = max((c["freshness"] for c in ot_c), default=0.0)
        if my_f - ot_f > 0.2:
            fresh = min(my_c, key=lambda c: c["age_days"])
            stale = min(ot_c, key=lambda c: c["age_days"])
            f.append(Finding(0.6 * (my_f - ot_f), f"{fresh['source']} was updated {_days(fresh['age_days'])} ago; "
                                                  f"the freshest record on the other side is {_days(stale['age_days'])} old.",
                             [fresh["id"], stale["id"]]))
    return out


# --------------------------------------------------------------------------- #
# Stale records
# --------------------------------------------------------------------------- #
def _stale_findings(packet: dict) -> dict[str, list[Finding]]:
    cands = packet["candidates"]
    today = date.fromisoformat(packet["today"])
    out: dict[str, list[Finding]] = {"A": [], "B": []}
    stage_c = [c for c in cands if c["field"] == "stage"]
    stage = normalize_field("stage", stage_c[0]["value"]) if stage_c else None
    stage_ids = [c["id"] for c in stage_c]
    if stage is None:  # stage not stale itself - read it from context
        sc = _ctx(packet, "stage")
        stage = normalize_field("stage", sc["value"]) if sc else None
        stage_ids = [sc["id"]] if sc else []
    min_age = min((c["age_days"] for c in cands), default=0.0)

    if stage in ("closed_won", "closed_lost"):
        out["A"].append(Finding(2.0, f"The deal is closed ({stage.replace('_', ' ')}); closed deals rarely change "
                                     "after the fact.", stage_ids))
    inv = _ctx(packet, "invoice_status")
    if inv and inv["value"] in ("paid", "void"):
        out["A"].append(Finding(1.0, f"Finance invoice status is '{inv['value']}': the money side is settled.", [inv["id"]]))
    out["A"].append(Finding(0.5, "All systems still agree with each other.", [c["id"] for c in cands][:4]))

    if stage in OPEN:
        out["B"].append(Finding(0.5, "The deal is still open, so its stage, value and date can move at any time.", stage_ids))
        cd = _ctx(packet, "close_date") or next((c for c in cands if c["field"] == "close_date"), None)
        if cd:
            cdate = normalize_field("close_date", cd["value"])
            if cdate and date.fromisoformat(cdate) < today:
                out["B"].append(Finding(2.0, f"Close date {cdate} has passed but the deal is still open.", [cd["id"]]))
        lc = _ctx(packet, "last_contacted")
        if lc:
            days = (today - date.fromisoformat(lc["value"])).days
            if days > 30:
                out["B"].append(Finding(1.5, f"Nobody has contacted the customer for {days} days.", [lc["id"]]))
    if min_age > 45:
        out["B"].append(Finding(1.0, f"No system has touched this record for {min_age:.0f} days.",
                                [min(cands, key=lambda c: c["age_days"])["id"]]))
    return out


# --------------------------------------------------------------------------- #
# Role outputs
# --------------------------------------------------------------------------- #
def _findings(packet: dict) -> dict[str, list[Finding]]:
    return _stale_findings(packet) if packet["reason"] == "stale" else _conflict_findings(packet)


def _score(fs: list[Finding]) -> float:
    return sum(f.weight for f in fs)


def argument(role: str, packet: dict) -> dict:
    me, other = ("A", "B") if role == "proponent" else ("B", "A")
    fs = _findings(packet)
    pos = sorted([f for f in fs[me] if f.weight > 0], key=lambda f: -f.weight)[:4]
    neg_other = sorted([f for f in fs[other] if f.weight < 0], key=lambda f: f.weight)
    if not pos:
        c = [c["id"] for c in packet["candidates"] if c["source"] in packet["sides"][me]["sources"]] or \
            [packet["candidates"][0]["id"]]
        pos = [Finding(0.1, f"{packet['sides'][me]['value']} is what {', '.join(packet['sides'][me]['sources']) or 'the record'} "
                            "currently shows.", c)]
    weaknesses = [f.text for f in neg_other][:3]
    if not weaknesses:
        weaknesses = [f"Side {other} offers no evidence newer than side {me}'s strongest item."]
    return {
        "position": packet["sides"][me]["claim"],
        "claims": [{"text": f.text, "evidence_ids": f.ids} for f in pos],
        "weaknesses_of_other_side": weaknesses,
    }


def verdict(packet: dict) -> dict:
    fs = _findings(packet)
    sa, sb = _score(fs["A"]), _score(fs["B"])
    margin = abs(sa - sb)
    if margin < 0.6:
        winner = "neither"
    else:
        winner = "A" if sa > sb else "B"
    sides = packet["sides"]
    if winner == "neither":
        ids = sorted({i for f in fs["A"] + fs["B"] for i in f.ids})[:8] or [packet["candidates"][0]["id"]]
        return {
            "winner": "neither", "resolved_value": "",
            "reasoning": "The evidence does not clearly favour either side; both positions have comparable support.",
            "evidence_ids": ids,
            "residual_uncertainty": "A person with direct knowledge of the deal should confirm the correct value.",
            "needs_human_review": True,
        }
    loser = "B" if winner == "A" else "A"
    win_pos = sorted([f for f in fs[winner] if f.weight > 0], key=lambda f: -f.weight)
    lose_neg = sorted([f for f in fs[loser] if f.weight < 0], key=lambda f: f.weight)
    lose_pos = sorted([f for f in fs[loser] if f.weight > 0], key=lambda f: -f.weight)
    why_win = " ".join(f.text for f in win_pos[:2]) or "Its evidence is stronger."
    if lose_neg:
        why_lose = lose_neg[0].text
    elif lose_pos:
        why_lose = f"its best evidence ({lose_pos[0].text.rstrip('.')}) is outweighed."
    else:
        why_lose = "it has no supporting evidence beyond the current record."
    ids: list[str] = []
    for f in win_pos[:3] + lose_neg[:2]:
        for i in f.ids:
            if i not in ids:
                ids.append(i)
    if packet["reason"] == "stale":
        residual = ("Holding is only safe until the next change; the confidence score stays low until someone "
                    "re-verifies." if winner == "A" else "The values may still be right - they are simply unverified.")
    else:
        residual = (f"{', '.join(sides[loser]['sources'])} have not confirmed {sides[winner]['value']}; "
                    "approving will sync them.")
    return {
        "winner": winner,
        "resolved_value": sides[winner]["value"],
        "reasoning": f"Side {winner} ({sides[winner]['value']}) wins: {why_win} Side {loser} loses: {why_lose}",
        "evidence_ids": ids,
        "residual_uncertainty": residual,
        "needs_human_review": margin < 1.0,
    }
