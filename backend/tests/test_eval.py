from app.services.evaluation import run_evaluation


def test_evaluation_meets_prd_targets(now):
    r = run_evaluation(now=now, save=False)
    m = r["metrics"]
    assert m["conflict_recall"] >= 0.95
    assert m["false_conflict_rate"] <= 0.05
    assert m["reconciliation_accuracy"] >= 0.80
    assert m["clean_debate_rate"] == 0.0
    assert m["citation_validity"] == 1.0
    assert m["avg_calls_standard"] <= 3.0          # PRD: <= 3 calls per conflict
    assert m["avg_calls_per_debate"] <= 4.0        # + one swap re-judge on high-stakes conflicts only
    assert m["consistency_checks"] >= 1 and m["consistency_agreement"] == 1.0
    assert m["reconciliation_accuracy"] > m["baseline_accuracy"]  # the debate beats majority+recency
