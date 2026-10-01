import math

import pytest

from app.engine.confidence import combine, freshness, reliability, reliability_table, validity_days
from app.engine.gate import conflict_hash, route

W = {"F": 0.5, "R": 0.15, "A": 0.35}


def test_freshness_is_one_when_new_and_half_at_half_life():
    assert freshness(0, 14) == 1.0
    assert math.isclose(freshness(14, 14), 0.5, rel_tol=1e-9)
    assert math.isclose(freshness(28, 14), 0.25, rel_tol=1e-9)


def test_freshness_decays_monotonically_and_stays_in_bounds():
    prev = 1.1
    for age in range(0, 400, 5):
        f = freshness(age, 30)
        assert 0.0 <= f <= 1.0
        assert f < prev
        prev = f


def test_negative_age_is_clamped():
    assert freshness(-3, 14) == 1.0


def test_reliability_floor():
    assert reliability(0, 10) == 1.0
    assert reliability(1, 10) == pytest.approx(0.9)
    assert reliability(9, 10) == 0.5  # floored
    assert reliability(0, 0) == 1.0


def test_reliability_table_counts_corrections_and_arbiter_syncs():
    rows = [{"source": "pipeline", "field": "stage", "reason": r} for r in
            ["sync", "sync", "import", "correction", "arbiter_sync", "sync", "sync", "sync", "sync", "sync"]]
    assert reliability_table(rows)[("pipeline", "stage")] == pytest.approx(0.8)


def test_combine_bounds_and_weights():
    assert combine(1, 1, 1, W) == 1.0
    assert combine(0, 0, 0, W) == 0.0
    assert combine(1, 0, 0, W) == pytest.approx(0.5)


def test_stale_agreeing_fact_drops_below_threshold():
    # 70 days old stage (half-life 14) - all systems agree, perfect reliability
    c = combine(freshness(70, 14), 1.0, 1.0, W)
    assert c < 0.60


def test_fresh_agreeing_fact_stays_above_threshold():
    assert combine(freshness(10, 14), 0.95, 1.0, W) > 0.60


@pytest.mark.parametrize("conflicted,conf,expected", [
    (True, 0.95, ("debate", "conflict")),
    (False, 0.40, ("debate", "stale")),
    (False, 0.90, ("direct", "clean")),
    (True, 0.20, ("debate", "conflict")),
])
def test_gate_routing_table(conflicted, conf, expected):
    assert route(conflicted, conf, 0.60) == expected


def test_gate_budget_exhausted_goes_provisional():
    assert route(True, 0.9, 0.6, can_debate=False) == ("provisional", "conflict")
    assert route(False, 0.9, 0.6, can_debate=False) == ("direct", "clean")


def test_conflict_hash_is_order_independent_and_value_sensitive():
    a = conflict_hash("D1", "stage", "conflict", [("crm", "closed_won"), ("finance", "negotiation")])
    b = conflict_hash("D1", "stage", "conflict", [("finance", "negotiation"), ("crm", "closed_won")])
    c = conflict_hash("D1", "stage", "conflict", [("crm", "closed_won"), ("finance", "proposal")])
    assert a == b != c


def test_validity_window_shrinks_for_volatile_fields():
    assert validity_days(7, 1.0, 1.0, W, 0.6) < validity_days(30, 1.0, 1.0, W, 0.6)
