import json

import pytest

from app.agents.debate import run_debate
from app.agents.llm import MockClient
from app.agents.validate import ValidationFailure, validate_argument, validate_verdict


@pytest.fixture
def packet(svc):
    facts = svc.assess_one("D1042", ["stage"])
    return svc.packets_for("D1042", facts)[0]


def _verdict(packet, **over):
    v = {"winner": "A", "resolved_value": packet["sides"]["A"]["value"], "reasoning": "r",
         "evidence_ids": [packet["candidates"][0]["id"]], "residual_uncertainty": "u", "needs_human_review": False}
    v.update(over)
    return json.dumps(v)


def test_valid_verdict_passes(packet):
    v = validate_verdict(_verdict(packet), packet)
    assert v.winner == "A"


def test_hallucinated_evidence_id_is_rejected(packet):
    with pytest.raises(ValidationFailure, match="do not exist"):
        validate_verdict(_verdict(packet, evidence_ids=["A9999"]), packet)


def test_malformed_json_is_rejected(packet):
    with pytest.raises(ValidationFailure, match="not valid JSON"):
        validate_verdict('{"winner": "A", ', packet)


def test_extra_keys_are_rejected(packet):
    raw = json.loads(_verdict(packet))
    raw["confidence"] = 0.99  # LLM self-assessed confidence is not accepted
    with pytest.raises(ValidationFailure):
        validate_verdict(json.dumps(raw), packet)


def test_resolved_value_must_match_winner(packet):
    with pytest.raises(ValidationFailure, match="resolved_value"):
        validate_verdict(_verdict(packet, resolved_value=packet["sides"]["B"]["value"]), packet)


def test_equivalent_spelling_of_value_is_accepted(packet):
    v = validate_verdict(_verdict(packet, resolved_value="closed_won"), packet)
    assert v.resolved_value == packet["sides"]["A"]["value"]


def test_neither_forces_human_review(packet):
    v = validate_verdict(_verdict(packet, winner="neither", resolved_value="whatever"), packet)
    assert v.resolved_value == "" and v.needs_human_review


def test_fenced_json_is_accepted(packet):
    assert validate_verdict("```json\n" + _verdict(packet) + "\n```", packet).winner == "A"


def test_argument_claims_need_real_evidence(packet):
    arg = {"position": "p", "claims": [{"text": "t", "evidence_ids": ["NOPE-1"]}], "weaknesses_of_other_side": []}
    with pytest.raises(ValidationFailure):
        validate_argument(json.dumps(arg), packet)


# ---------------------------------------------------------------- debate paths
def test_happy_path_costs_three_calls(packet):
    rec = run_debate(packet, MockClient(), max_calls=4)
    assert rec.llm_calls == 3 and not rec.fallback_used and rec.verdict.winner == "A"
    assert set(rec.verdict.evidence_ids) <= packet["_evidence_ids"]


def test_bad_judge_citation_is_repaired_with_one_retry(packet):
    llm = MockClient(fail_plan={"judge": ["bad_citation"]})
    rec = run_debate(packet, llm, max_calls=4)
    assert rec.llm_calls == 4 and not rec.fallback_used
    assert llm.calls.count("judge") == 2


def test_persistent_judge_failure_falls_back_and_flags_review(packet):
    llm = MockClient(fail_plan={"judge": ["invalid_json", "bad_citation"]})
    rec = run_debate(packet, llm, max_calls=4)
    assert rec.fallback_used and rec.verdict.needs_human_review
    assert rec.llm_calls == 4  # hard cap respected
    assert set(rec.verdict.evidence_ids) <= packet["_evidence_ids"]


def test_provider_error_does_not_crash(packet):
    llm = MockClient(fail_plan={"proponent": ["error"], "challenger": ["error"], "judge": ["error", "error"]})
    rec = run_debate(packet, llm, max_calls=4)
    assert rec.fallback_used and "proponent" in rec.degraded_roles or "challenger" in rec.degraded_roles
    assert rec.llm_calls <= 4


def test_wrong_value_from_judge_is_caught(packet):
    llm = MockClient(fail_plan={"judge": ["wrong_value"]})
    rec = run_debate(packet, llm, max_calls=4)
    assert rec.verdict.resolved_value in (packet["sides"]["A"]["value"], packet["sides"]["B"]["value"])
