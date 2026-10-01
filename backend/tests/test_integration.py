"""Seeded dataset -> scan -> debates -> cards -> approval, all in-process."""
from dataclasses import replace

import pytest

from app.agents.llm import MockClient
from app.schemas import ApproveRequest, InjectRequest
from app.services.approvals import TransitionError
from app.services.arbiter import ArbiterService


def test_scan_detects_exactly_the_injected_conflicts(svc):
    facts_by_deal, _ = svc.assess_all()
    detected = {(d, f.field) for d, fs in facts_by_deal.items() for f in fs if f.reason == "conflict"}
    stale = {d for d, fs in facts_by_deal.items() for f in fs if f.reason == "stale"}
    truth = svc.truth
    assert detected == {(i["deal_id"], i["field"]) for i in truth["items"] if i["kind"] == "conflict"}
    assert stale == {i["deal_id"] for i in truth["items"] if i["kind"] == "stale"}


def test_clean_deals_never_reach_the_llm(svc):
    svc.scan()
    clean = set(svc.truth["clean_deals"])
    for card in svc.store.list_decisions(limit=1000):
        assert card["deal_id"] not in clean


def test_s1_clean_query_is_direct_and_free(svc):
    before = svc.budget.snapshot()["llm_calls"]
    res = svc.query("What is the status and value of deal D1007?")
    card = res["card"]
    assert card["path"] == "direct" and card["status"] == "informational"
    assert card["confidence"] >= 0.6 and card["debates"] == []
    assert svc.budget.snapshot()["llm_calls"] == before


def test_s2_conflict_is_debated_with_counterfactual(svc):
    res = svc.query("What is the status and value of deal D1042?")
    card = svc.get_decision(res["card"]["id"])
    assert card["path"] == "debate" and card["status"] == "pending_approval"
    assert card["answer"] == {"stage": "Closed Won", "value": "$48,000"}
    assert {c["rejected_value"] for c in card["counterfactuals"]} == {"Negotiation", "$45,000"}
    assert all(c["rejected_sources"] == ["finance"] for c in card["counterfactuals"])
    assert any(e["cited"] and e["kind"] == "audit" for e in card["evidence"])  # judge cites audit log
    assert card["risk_hint"]["value_at_stake"] > 0


def test_s3_stale_deal_gets_reverify_verdict(svc):
    res = svc.query("status of D1019")
    card = svc.get_decision(res["card"]["id"])
    assert card["reason"] == "stale" and card["confidence"] < 0.6
    assert card["debates"][0]["verdict"]["winner"] == "B"  # re-verify


def test_identical_conflict_never_spends_quota_twice(svc):
    first = svc.query("value of D1042")["card"]
    svc.decide(first["id"], ApproveRequest(action="reject", actor="Sam"))  # conflict stays unresolved
    calls = svc.budget.snapshot()["llm_calls"]
    res = svc.query("what is the value of D1042?")
    assert res["card"]["id"] != first["id"]
    assert svc.budget.snapshot()["llm_calls"] == calls
    assert svc.get_decision(res["card"]["id"])["debates"][0]["cache_hit"] is True


def test_approval_syncs_sources_and_clears_the_conflict(svc):
    svc.scan()
    card = next(c for c in svc.list_decisions() if c["deal_id"] == "D1042")
    out = svc.decide(card["id"], ApproveRequest(action="approve", actor="Priya (RevOps)", note="checked contract"))
    assert out["status"] == "approved" and "finance.stage" in out["status_note"]
    assert svc.store.source_row("finance", "D1042")["stage"] == "Closed - Won"
    assert svc.store.source_row("finance", "D1042")["value"] == "$48,000.00"
    facts = {f.field: f for f in svc.assess_one("D1042")}
    assert facts["stage"].route == "direct" and facts["value"].route == "direct"
    assert svc.store.approvals_for(card["id"])[0]["actor"] == "Priya (RevOps)"
    audit = svc.store.audit_for_deal("D1042")
    assert any(a["reason"] == "arbiter_sync" and a["source"] == "finance" for a in audit)


def test_rejection_changes_nothing(svc):
    svc.scan()
    card = next(c for c in svc.list_decisions() if c["deal_id"] == "D1042")
    before = svc.store.source_row("finance", "D1042")
    out = svc.decide(card["id"], ApproveRequest(action="reject", actor="Sam"))
    assert out["status"] == "rejected"
    assert svc.store.source_row("finance", "D1042") == before


def test_terminal_states_cannot_be_decided_again(svc):
    svc.scan()
    card = next(c for c in svc.list_decisions() if c["deal_id"] == "D1042")
    svc.decide(card["id"], ApproveRequest(action="reject", actor="Sam"))
    with pytest.raises(TransitionError):
        svc.decide(card["id"], ApproveRequest(action="approve", actor="Sam"))


def test_approving_supersedes_overlapping_open_cards(svc):
    q = svc.query("status of D1042")["card"]          # covers stage only
    svc.scan()                                         # scan card covers stage + value
    scan_card = next(c for c in svc.list_decisions() if c["deal_id"] == "D1042" and c["origin"] == "scan")
    svc.decide(scan_card["id"], ApproveRequest(action="approve", actor="Priya"))
    assert svc.get_decision(q["id"])["status"] == "superseded"


def test_budget_exhaustion_gives_provisional_answers(seeded, cfg):
    store, _ = seeded
    s = ArbiterService(store, replace(cfg, MAX_DEBATES_PER_SESSION=2), llm=MockClient(), async_debates=False)
    s.scan()
    cards = s.list_decisions()
    assert sum(1 for c in cards if c["path"] == "provisional") > 0
    prov = next(c for c in cards if c["path"] == "provisional")
    assert prov["status"] == "needs_review" and "Provisional" in prov["status_note"]
    assert s.budget.snapshot()["debates_run"] == 2


def test_s4_injected_drift_is_caught_on_next_scan(svc):
    svc.scan()
    before = {c["id"] for c in svc.list_decisions()}
    drift = svc.inject_drift(InjectRequest())
    summary = svc.scan()
    new = [c for c in svc.list_decisions() if c["id"] not in before]
    assert summary["new_decisions"] and new[0]["deal_id"] == drift["deal_id"]
    assert drift["field"] in new[0]["fields"]


def test_s5_priorities_flag_unreliable_deals_instead_of_ranking_them(svc):
    p = svc.priorities()
    flagged = {i["deal_id"] for i in p["flagged"]}
    assert "D1019" in flagged  # stale
    assert all(not i["flags"] for i in p["ranked"])
    assert [i["rank"] for i in p["ranked"]] == list(range(1, len(p["ranked"]) + 1))


def test_clock_fast_forward_decays_confidence(svc):
    c0 = {f.field: f.confidence for f in svc.assess_one("D1007")}
    svc.store.set_meta("clock_offset_days", 30)
    c1 = {f.field: f.confidence for f in svc.assess_one("D1007")}
    assert all(c1[k] < c0[k] for k in ("stage", "value", "close_date"))


def test_reset_restores_baseline(svc):
    svc.scan()
    svc.inject_drift(InjectRequest(deal_id="D1007", field="value"))
    svc.reset()
    assert svc.assess_one("D1007")[2].route == "direct"


def test_sunset_timer_reflects_current_age(svc):
    from datetime import datetime
    direct = svc.query("status of D1007")["card"]
    stale = svc.get_decision(svc.query("status of D1019")["card"]["id"])
    assert datetime.fromisoformat(direct["expires_at"]) > svc.now()
    assert stale["expired"] is True  # already decayed below threshold -> re-verify


def test_approval_restarts_the_sunset_timer(svc):
    from datetime import datetime
    svc.scan()
    card = next(c for c in svc.list_decisions() if c["deal_id"] == "D1042")
    out = svc.decide(card["id"], ApproveRequest(action="approve", actor="Priya"))
    assert datetime.fromisoformat(out["expires_at"]) > datetime.fromisoformat(card["expires_at"])
