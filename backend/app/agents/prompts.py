"""Prompts and JSON schemas for the three debate roles.

Agents see only the evidence packet built by code (never raw tables, never the
ground truth) and must cite evidence by ID. Schemas are built per packet so a
provider with constrained decoding can only emit IDs and values that exist.
"""
from __future__ import annotations

import json

SYSTEM = """You are one role in Arbiter's evidence-bound debate. Arbiter reconciles business \
records (CRM, Finance, Pipeline tracker) that disagree, or re-checks records that have gone stale.

Rules:
- Use only the evidence packet. Do not assume facts that are not in it.
- Every claim must cite the IDs of the evidence items that support it, exactly as written in the \
packet (for example "CRM-D1042-stage" or "A0981"). Never invent an ID.
- Be concise: at most 4 claims, one or two sentences each.
- Do not estimate confidence scores; Arbiter computes confidence from the data itself.
- Reply with JSON only."""

JUDGE_GUIDE = """How to weigh evidence:
- A recent change made by a named person is stronger than an older copy of the previous value in another system.
- Values written by automated imports ("bulk_import_bot") that contradict human-maintained records are suspect.
- The billing system is authoritative for invoiced amounts.
- Agreement between systems only counts if the agreeing copies are not all stale copies of the same old value.
- Implausible jumps that appear in a single system (a value 10x larger, transposed digits, swapped day and month) are likely entry errors.
- Context fields (invoice status, forecast category, last contact date) can corroborate or undermine a side.
- For stale-record reviews: closed deals rarely change, while open deals whose close date has passed or that \
have not been contacted in weeks must be re-verified before anyone acts on them.
- If the evidence is insufficient to decide, choose "neither" and set needs_human_review to true."""


def _packet_json(packet: dict) -> str:
    public = {k: v for k, v in packet.items() if not k.startswith("_")}
    return json.dumps(public, indent=1, default=str)


def debater_prompt(role: str, packet: dict) -> str:
    mine, other = ("A", "B") if role == "proponent" else ("B", "A")
    s, o = packet["sides"][mine], packet["sides"][other]
    return (
        f"ROLE: {role.capitalize()} (side {mine}).\n"
        f"You defend side {mine}: {s['claim']}\n"
        f"The other side ({other}) argues: {o['claim']}\n\n"
        "Make the strongest honest case for your side using the evidence, and list concrete weaknesses "
        "of the other side's position.\n\n"
        "Return JSON: {\"position\": str, \"claims\": [{\"text\": str, \"evidence_ids\": [str]}], "
        "\"weaknesses_of_other_side\": [str]}\n\n"
        f"EVIDENCE PACKET:\n{_packet_json(packet)}"
    )


def judge_prompt(packet: dict, proponent: dict | None, challenger: dict | None) -> str:
    a, b = packet["sides"]["A"], packet["sides"]["B"]
    return (
        "ROLE: Judge. Decide which side the evidence supports.\n"
        f"Side A: {a['claim']}\nSide B: {b['claim']}\n\n"
        f"{JUDGE_GUIDE}\n\n"
        "Return JSON with:\n"
        f"- winner: \"A\", \"B\" or \"neither\"\n"
        f"- resolved_value: exactly \"{a['value']}\" if A wins, exactly \"{b['value']}\" if B wins, \"\" if neither\n"
        "- reasoning: 2-4 sentences explaining why the winner is right AND why the losing side lost\n"
        "- evidence_ids: the IDs you relied on\n"
        "- residual_uncertainty: what could still be wrong\n"
        "- needs_human_review: true if a human should look closely before approving\n\n"
        f"PROPONENT (side A) ARGUMENT:\n{json.dumps(proponent, indent=1) if proponent else 'unavailable'}\n\n"
        f"CHALLENGER (side B) ARGUMENT:\n{json.dumps(challenger, indent=1) if challenger else 'unavailable'}\n\n"
        f"EVIDENCE PACKET:\n{_packet_json(packet)}"
    )


def repair_prompt(original_prompt: str, bad_output: str, error: str) -> str:
    return (
        f"{original_prompt}\n\n"
        "Your previous reply was rejected by Arbiter's validator.\n"
        f"Validator error: {error}\n"
        f"Previous reply (truncated): {bad_output[:1500]}\n"
        "Reply again with corrected JSON only. Cite only IDs that appear in the evidence packet."
    )


# --------------------------------------------------------------------------- #
# Schemas (strict: every property required, no extra keys)
# --------------------------------------------------------------------------- #
def _id_items(packet: dict) -> dict:
    return {"type": "string", "enum": sorted(packet["_evidence_ids"])}


def argument_schema(packet: dict) -> dict:
    return {
        "type": "object",
        "properties": {
            "position": {"type": "string"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "evidence_ids": {"type": "array", "items": _id_items(packet)},
                    },
                    "required": ["text", "evidence_ids"],
                    "additionalProperties": False,
                },
            },
            "weaknesses_of_other_side": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["position", "claims", "weaknesses_of_other_side"],
        "additionalProperties": False,
    }


def verdict_schema(packet: dict) -> dict:
    allowed = [packet["sides"]["A"]["value"], packet["sides"]["B"]["value"], ""]
    return {
        "type": "object",
        "properties": {
            "winner": {"type": "string", "enum": ["A", "B", "neither"]},
            "resolved_value": {"type": "string", "enum": allowed},
            "reasoning": {"type": "string"},
            "evidence_ids": {"type": "array", "items": _id_items(packet)},
            "residual_uncertainty": {"type": "string"},
            "needs_human_review": {"type": "boolean"},
        },
        "required": ["winner", "resolved_value", "reasoning", "evidence_ids",
                     "residual_uncertainty", "needs_human_review"],
        "additionalProperties": False,
    }
