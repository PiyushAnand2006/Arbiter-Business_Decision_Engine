"""Guardrail for every LLM reply (architecture §6.4).

1. The reply must parse as JSON and match the Pydantic schema (no extra keys).
2. Every cited evidence ID must exist in the packet - hallucinated IDs are rejected.
3. The judge's resolved_value must be the winning side's value ("" for "neither").
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from ..engine.normalize import normalize_field, values_equal
from ..schemas import Argument, Verdict


class ValidationFailure(ValueError):
    pass


def parse_json(raw: str) -> dict:
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationFailure(f"reply is not valid JSON ({e.msg} at char {e.pos})") from e
    if not isinstance(data, dict):
        raise ValidationFailure("reply must be a JSON object")
    return data


def _check_ids(ids: list[str], packet: dict, where: str):
    valid = packet["_evidence_ids"]
    bad = [i for i in ids if i not in valid]
    if bad:
        raise ValidationFailure(f"{where} cites evidence IDs that do not exist in the packet: {bad}")


def validate_argument(raw: str, packet: dict) -> Argument:
    data = parse_json(raw)
    try:
        arg = Argument.model_validate(data)
    except ValidationError as e:
        raise ValidationFailure(f"argument does not match schema: {e.errors()[0]['msg']} at {e.errors()[0]['loc']}") from e
    if not arg.claims:
        raise ValidationFailure("argument must contain at least one claim")
    for c in arg.claims:
        if not c.evidence_ids:
            raise ValidationFailure(f"claim without evidence: {c.text[:80]!r}")
        _check_ids(c.evidence_ids, packet, "claim")
    return arg


def _matches(packet: dict, side: str, resolved: str) -> bool:
    expected = packet["sides"][side]
    if packet["reason"] == "stale":
        return resolved.strip().lower() == str(expected["value"]).lower()
    fieldname = packet["field"]
    return values_equal(fieldname, normalize_field(fieldname, resolved), expected["normalized"], 0.005)


def validate_verdict(raw: str, packet: dict) -> Verdict:
    data = parse_json(raw)
    try:
        v = Verdict.model_validate(data)
    except ValidationError as e:
        raise ValidationFailure(f"verdict does not match schema: {e.errors()[0]['msg']} at {e.errors()[0]['loc']}") from e
    if not v.evidence_ids:
        raise ValidationFailure("verdict must cite at least one evidence ID")
    _check_ids(v.evidence_ids, packet, "verdict")
    if v.winner in ("A", "B"):
        if not _matches(packet, v.winner, v.resolved_value):
            raise ValidationFailure(
                f"resolved_value {v.resolved_value!r} is not side {v.winner}'s value {packet['sides'][v.winner]['value']!r}")
        v.resolved_value = packet["sides"][v.winner]["value"]  # canonical display form
    else:
        v.resolved_value = ""
        v.needs_human_review = True
    return v
