"""Research-driven features: discrepancy taxonomy, severity, position-swap check,
activity log, trends, source health, export, live debate progress."""
import pytest

from app.agents.debate import run_debate
from app.agents.llm import MockClient
from app.engine.classify import classify, severity
from app.schemas import ApproveRequest, InjectRequest


def _packet(svc, deal_id, field):
    facts = svc.assess_one(deal_id, [field])
    return svc.packets_for(deal_id, facts)[0]


def _pattern_deal(svc, pattern):
    return next(i for i in svc.truth["items"] if i["pattern"] == pattern)


@pytest.mark.parametrize("pattern,expected", [
    ("hero_crm_ahead", "lagging_system"),
    ("crm_ahead_minority", "lagging_system"),
    ("import_regression", "automated_overwrite"),
    ("finance_invoiced", "authoritative_update"),
    ("value_typo_x10", "entry_error"),
    ("value_typo_transpose", "entry_error"),
    ("date_import_swap", "entry_error"),
    ("date_slipped_minority", "lagging_system"),
])
def test_discrepancy_taxonomy(svc, pattern, expected):
    item = _pattern_deal(svc, pattern)
    assert classify(_packet(svc, item["deal_id"], item["field"]))["type"] == expected


def test_stale_records_are_classified(svc):
    facts = svc.assess_one("D1019")
    packet = svc.packets_for("D1019", facts)[-1]
    assert classify(packet)["type"] == "stale_record"


def test_severity_bands():
    assert severity(150_000, ["lagging_system"]) == "high"
    assert severity(60_000, ["unexplained"]) == "high"
    assert severity(60_000, ["entry_error"]) == "medium"
    assert severity(5_000, []) == "low"


def test_cards_carry_taxonomy_and_severity(svc):
    svc.scan()
    card = next(c for c in svc.list_decisions() if c["deal_id"] == "D1042")
    assert {d["type"] for d in card["discrepancies"]} == {"lagging_system"}
    assert card["severity"] in ("high", "medium", "low")


def test_position_swap_check_agrees_on_consistent_judge(svc):
    rec = run_debate(_packet(svc, "D1042", "stage"), MockClient(), consistency_check=True)
    assert rec.consistency["checked"] and rec.consistency["agreed"]
    assert rec.llm_calls == 4 and not rec.verdict.needs_human_review


def test_position_swap_disagreement_escalates_to_human(svc):
    rec = run_debate(_packet(svc, "D1042", "stage"), MockClient(fail_plan={"judge": ["ok", "flip"]}),
                     consistency_check=True)
    assert rec.consistency["agreed"] is False
    assert rec.verdict.needs_human_review
    assert any("position bias" in e for e in rec.errors)


def test_debate_reports_its_stages(svc):
    stages = []
    run_debate(_packet(svc, "D1042", "value"), MockClient(), consistency_check=True, on_stage=stages.append)
    assert stages == ["arguing", "judging", "verifying"]


def test_activity_timeline_records_the_loop(svc):
    svc.scan()
    card = next(c for c in svc.list_decisions() if c["deal_id"] == "D1042")
    svc.decide(card["id"], ApproveRequest(action="approve", actor="Priya"))
    svc.inject_drift(InjectRequest())
    kinds = [e["kind"] for e in svc.activity(200)]
    assert {"detected", "resolved", "approved", "drift"} <= set(kinds)
    assert kinds[0] == "drift"  # newest first


def test_trend_history_is_recorded(svc):
    svc.scan()
    hist = svc.stats()["history"]
    assert hist and {"direct", "conflicts", "stale"} <= set(hist[-1])


def test_source_health_scorecards(svc):
    svc.scan()
    health = {h["source"]: h for h in svc.source_health()}
    assert set(health) == {"crm", "finance", "pipeline"}
    # finance is the lagging system in most injected conflicts
    assert health["finance"]["debates_lost"] > health["crm"]["debates_lost"]
    assert 0 < health["finance"]["agreement_rate"] < 1


def test_review_metrics(svc):
    svc.scan()
    card = next(c for c in svc.list_decisions() if c["deal_id"] == "D1042")
    svc.decide(card["id"], ApproveRequest(action="approve", actor="Priya"))
    r = svc.stats()["review"]
    assert r["decided"] == 1 and r["approval_rate"] == 1.0
    assert r["by_type"].get("Lagging system")


def test_csv_export(svc):
    svc.scan()
    csv_text = svc.export_csv()
    header, first = csv_text.splitlines()[:2]
    assert header.startswith("decision_id,deal_id,company")
    assert first.split(",")[0] == "1"


def test_live_progress_is_visible_while_debating(svc):
    svc.scan()
    card = next(c for c in svc.store.list_decisions(limit=100))
    card["status"] = "debating"
    svc.store.save_decision(card, svc.now().isoformat())
    svc._progress(card["id"], None, "stage", "judging", 0, 2)
    assert svc.get_decision(card["id"])["progress"]["stage"] == "judging"


def test_query_reuses_the_open_decision_for_the_same_conflict(svc):
    svc.scan()
    scan_card = next(c for c in svc.list_decisions() if c["deal_id"] == "D1042")
    r = svc.query("status and value of D1042")
    assert r["reused"] and r["card"]["id"] == scan_card["id"]
    assert sum(1 for c in svc.list_decisions() if c["deal_id"] == "D1042") == 1
