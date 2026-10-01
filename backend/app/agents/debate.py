"""Debate orchestration: proponent + challenger (in parallel) -> judge.

Small fixed state machine (no framework):
    1. proponent and challenger argue from the same evidence packet   (2 calls)
    2. judge reads both arguments + the packet and rules                (1 call)
    3. every reply is validated; ONE repair retry per conflict is shared
       across roles; a debater that still fails is replaced by an
       evidence-only summary; a judge that still fails yields the
       rule-based fallback verdict flagged needs_human_review.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from ..schemas import Argument, DebateRecord, DebateSide, Verdict
from . import prompts
from .llm import LLMClient, LLMError
from .validate import ValidationFailure, validate_argument, validate_verdict


def _side(label: str, s: dict) -> DebateSide:
    return DebateSide(label=label, claim=s["claim"], value=s["value"], normalized=s["normalized"], sources=s["sources"])


def evidence_only_argument(role: str, packet: dict) -> Argument:
    """Deterministic stand-in when a debater's output cannot be used."""
    me = "A" if role == "proponent" else "B"
    side = packet["sides"][me]
    cands = [c for c in packet["candidates"] if c["source"] in side["sources"]] or packet["candidates"][:2]
    return Argument.model_validate({
        "position": side["claim"],
        "claims": [{"text": f"{c['source']} records {c['field']} = {c['value']} (updated {c['updated_at'][:10]}).",
                    "evidence_ids": [c["id"]]} for c in cands[:3]],
        "weaknesses_of_other_side": ["(Debater output unavailable - evidence listed without argument.)"],
    })


def rule_based_verdict(packet: dict, why: str) -> Verdict:
    """Architecture §5.4 / §11: most-agreeing source wins, ties broken by recency."""
    if packet["reason"] == "stale":
        return Verdict(winner="B", resolved_value="reverify",
                       reasoning=f"Rule-based fallback ({why}): stale records default to re-verification.",
                       evidence_ids=[c["id"] for c in packet["candidates"]][:4],
                       residual_uncertainty="No debate was run; the record may well still be correct.",
                       needs_human_review=True)
    sides = packet["sides"]
    by_src = {c["source"]: c for c in packet["candidates"]}

    def key(label: str):
        s = sides[label]
        return (len(s["sources"]), max(by_src[x]["updated_at"] for x in s["sources"]))

    winner = "A" if key("A") >= key("B") else "B"
    loser = "B" if winner == "A" else "A"
    return Verdict(
        winner=winner, resolved_value=sides[winner]["value"],
        reasoning=(f"Rule-based fallback ({why}): chose {sides[winner]['value']} because it is held by the most "
                   f"systems ({', '.join(sides[winner]['sources'])}), breaking ties by the most recent update. "
                   f"{sides[loser]['value']} ({', '.join(sides[loser]['sources'])}) was not examined further."),
        evidence_ids=[by_src[s]["id"] for s in sides[winner]["sources"]],
        residual_uncertainty="Majority-and-recency rule only; audit history was not weighed.",
        needs_human_review=True,
    )


def swap_sides(packet: dict) -> dict:
    swapped = dict(packet)
    swapped["sides"] = {"A": packet["sides"]["B"], "B": packet["sides"]["A"]}
    return swapped


FLIP = {"A": "B", "B": "A", "neither": "neither"}


def run_debate(packet: dict, llm: LLMClient, max_calls: int = 4, consistency_check: bool = False,
               on_stage: Optional[Callable[[str], None]] = None) -> DebateRecord:
    t0 = time.perf_counter()
    ctx = {"packet": packet}
    calls = 0
    retries_left = max(0, max_calls - 3)
    errors: list[str] = []
    degraded: list[str] = []
    stage = on_stage or (lambda _s: None)
    stage("arguing")

    def attempt(role: str, prompt: str, schema: dict, validator: Callable, context: dict):
        raw = None
        try:
            raw = llm.generate(role, prompts.SYSTEM, prompt, schema, context)
            return validator(raw, packet), None, raw
        except (LLMError, ValidationFailure) as e:
            return None, f"{role}: {e}", raw

    # --- round 1: both debaters in parallel ------------------------------------
    debater_prompts = {r: prompts.debater_prompt(r, packet) for r in ("proponent", "challenger")}
    arg_schema = prompts.argument_schema(packet)
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {r: ex.submit(attempt, r, debater_prompts[r], arg_schema, validate_argument, ctx)
                for r in ("proponent", "challenger")}
        results = {r: f.result() for r, f in futs.items()}
    calls += 2

    args: dict[str, Optional[Argument]] = {}
    for role in ("proponent", "challenger"):
        arg, err, raw = results[role]
        if arg is None:
            errors.append(err)
            if retries_left > 0:
                retries_left -= 1
                calls += 1
                repair = prompts.repair_prompt(debater_prompts[role], raw or "", err)
                arg, err2, _ = attempt(role, repair, arg_schema, validate_argument, ctx)
                if err2:
                    errors.append(err2 + " (after repair)")
        if arg is None:
            degraded.append(role)
            arg = evidence_only_argument(role, packet)
        args[role] = arg

    # --- round 2: judge ---------------------------------------------------------
    stage("judging")
    pro, cha = args["proponent"].model_dump(), args["challenger"].model_dump()
    judge_p = prompts.judge_prompt(packet, pro, cha)
    v_schema = prompts.verdict_schema(packet)
    judge_ctx = {**ctx, "proponent": pro, "challenger": cha}
    verdict, err, raw = attempt("judge", judge_p, v_schema, validate_verdict, judge_ctx)
    calls += 1
    if verdict is None:
        errors.append(err)
        if retries_left > 0:
            retries_left -= 1
            calls += 1
            verdict, err2, _ = attempt("judge", prompts.repair_prompt(judge_p, raw or "", err), v_schema,
                                       validate_verdict, judge_ctx)
            if err2:
                errors.append(err2 + " (after repair)")
    fallback = verdict is None
    if fallback:
        verdict = rule_based_verdict(packet, "judge output invalid or unavailable")

    # --- round 3 (high stakes only): re-judge with the sides swapped -------------
    # LLM judges are known to favour whichever option is presented first; a verdict
    # that flips when A and B trade places is not trustworthy enough to act on.
    consistency = None
    if consistency_check and not fallback and packet["reason"] == "conflict":
        stage("verifying")
        swapped = swap_sides(packet)
        swap_ctx = {"packet": swapped, "proponent": cha, "challenger": pro}
        second, err2, _ = attempt("judge", prompts.judge_prompt(swapped, cha, pro), prompts.verdict_schema(swapped),
                                  lambda raw, _p: validate_verdict(raw, swapped), swap_ctx)
        calls += 1
        if second is None:
            consistency = {"checked": False, "agreed": None, "note": err2}
        else:
            mapped = FLIP[second.winner]
            agreed = mapped == verdict.winner
            consistency = {"checked": True, "agreed": agreed, "second_winner": mapped,
                           "note": "Same verdict with the sides swapped." if agreed else
                                   f"Swapping the sides changed the verdict to {mapped}: {second.reasoning}"}
            if not agreed:
                verdict.needs_human_review = True
                errors.append("judge: verdict changed when sides were swapped (position bias)")

    return DebateRecord(
        field=packet["field"], reason=packet["reason"], conflict_hash=packet["_hash"],
        side_a=_side("A", packet["sides"]["A"]), side_b=_side("B", packet["sides"]["B"]),
        proponent=args["proponent"], challenger=args["challenger"], verdict=verdict,
        llm_calls=calls, cache_hit=False, fallback_used=fallback, degraded_roles=degraded, errors=errors,
        consistency=consistency, provider=llm.provider, model=llm.model,
        duration_ms=int((time.perf_counter() - t0) * 1000),
    )


def provisional_record(packet: dict, why: str) -> DebateRecord:
    """No debate (budget exhausted): rule-based answer, clearly labelled provisional."""
    return DebateRecord(
        field=packet["field"], reason=packet["reason"], conflict_hash=packet["_hash"],
        side_a=_side("A", packet["sides"]["A"]), side_b=_side("B", packet["sides"]["B"]),
        proponent=None, challenger=None, verdict=rule_based_verdict(packet, why),
        llm_calls=0, cache_hit=False, fallback_used=True, provider="rules", model="majority+recency",
    )
