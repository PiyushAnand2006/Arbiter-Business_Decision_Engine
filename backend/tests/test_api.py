"""HTTP contract: the dashboard's view of the system (runs against a temp DB)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        app.state.svc.async_debates = False
        app.state.svc.executor = None  # resolve debates inline for deterministic tests
        c.post("/api/demo/reset")
        yield c


def test_health_and_config(client):
    assert client.get("/api/health").json() == {"ok": True}
    cfg = client.get("/api/config").json()
    assert cfg["llm_provider"] == "mock" and cfg["thresh_low"] == 0.6


def test_scan_and_stats_split_direct_vs_debate(client):
    s = client.post("/api/scan").json()
    assert s["facts_scanned"] == 200 and s["direct"] > s["debate"] > 0
    stats = client.get("/api/stats").json()
    assert stats["open_conflicts"] == 15 and stats["budget"]["debates_cap"] == 25


def test_decision_list_and_detail(client):
    cards = client.get("/api/decisions").json()
    assert cards and all(not k.startswith("_") for k in cards[0])
    d1042 = next(c for c in cards if c["deal_id"] == "D1042")
    detail = client.get(f"/api/decisions/{d1042['id']}").json()
    assert detail["answer"]["stage"] == "Closed Won" and detail["counterfactuals"]


def test_query_endpoint(client):
    r = client.post("/api/query", json={"q": "What is the status and value of deal D1007?"}).json()
    assert r["type"] == "decision" and r["card"]["path"] == "direct"
    r = client.post("/api/query", json={"q": "Which open deals should we follow up on first?"}).json()
    assert r["type"] == "priorities" and r["ranked"]
    assert client.post("/api/query", json={"q": "hello"}).status_code == 400
    assert client.post("/api/query", json={"q": "status of D9999"}).status_code == 404


def test_approval_flow_and_409_on_repeat(client):
    card = next(c for c in client.get("/api/decisions?status=pending_approval").json())
    r = client.post(f"/api/decisions/{card['id']}/approve", json={"action": "approve", "actor": "tester"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = client.post(f"/api/decisions/{card['id']}/approve", json={"action": "reject", "actor": "tester"})
    assert r.status_code == 409


def test_live_edit_then_scan_finds_conflict(client):
    r = client.patch("/api/sources/finance/D1007", json={"field": "value", "value": "$1,000.00", "actor": "presenter"})
    assert r.status_code == 200
    s = client.post("/api/scan").json()
    assert s["new_decisions"]
    assert client.get("/api/deals/D1007").json()["facts"][2]["reason"] == "conflict"


def test_demo_controls(client):
    assert client.post("/api/demo/inject", json={}).json()["deal_id"]
    assert client.post("/api/demo/clock", json={"offset_days": 14}).json()["offset_days"] == 14
    assert client.post("/api/demo/clock", json={"offset_days": 0}).status_code == 200
    r = client.post("/api/demo/reset").json()
    assert r["deals"] == 50 and r["debate_cache_kept"]


def test_eval_endpoint(client):
    rep = client.post("/api/eval/run", json={}).json()
    assert rep["metrics"]["conflict_recall"] == 1.0
    assert client.get("/api/eval/latest").json()["metrics"]
