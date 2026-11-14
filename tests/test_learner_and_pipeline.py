import json

import pytest

from stress_tester import config, learner, llm, pipeline, rewriter, variants
from stress_tester.panel.mock import PLANTED


def test_pipeline_smoke_and_learner_recovers_planted_effects(offline_workspace):
    res = pipeline.run(adapter="mock", n=40, log=lambda *_: None)
    for key in ("batch1", "batch2", "evaluation", "rules_final", "improvement"):
        assert key in res
    assert (offline_workspace / "outputs" / "results.json").exists()
    assert json.loads((offline_workspace / "memory" / "rules.json").read_text())["rules"]
    fragile = {r["feature"]: r for r in res["rules_final"] if r["status"] == "fragile"}
    assert {"jargon", "loss_frame"} <= set(fragile)  # strongest planted effects are found...
    for f, r in fragile.items():
        assert r["effect"] * PLANTED[f] > 0  # ...with the right sign


def test_memory_beats_no_memory_on_heldout_batch(offline_workspace):
    res = pipeline.run(adapter="mock", n=40, log=lambda *_: None)
    ev = res["evaluation"]
    assert ev["mae_after"] < ev["mae_before"]
    assert ev["after"]["accuracy"] >= ev["before"]["accuracy"]


def test_rewrites_always_change_the_text(offline_workspace):
    res = pipeline.run(adapter="mock", n=40, log=lambda *_: None)
    for c in res["batch2"]["concepts"]:
        if "rewrite" in c:
            assert c["rewrite"]["text"] != c["text"]
            assert c["rewrite_result"] is not None


def test_rewriter_reports_no_change_instead_of_faking_one():
    out = rewriter.rewrite("Get paid up to two days early with direct deposit.", rules=[])
    assert out["no_change"] and out["text"] == "Get paid up to two days early with direct deposit."


def test_rewriter_fixes_jargon_and_urgency():
    out = rewriter.rewrite("Act now: lock in a 12-month CD at 4.5% APY before rates drop.", rules=[])
    assert not out["no_change"]
    assert "CD" not in out["text"] and "APY" not in out["text"] and "Act now" not in out["text"]


def test_offline_variants_have_no_doubled_words_and_can_drop_urgency():
    v = variants.rule_variants("High-yield savings at 4.10% APY, compounded daily, with zero fees.")
    assert v["plain"].count(" with ") <= 1
    assert v["plain"].startswith("A savings account paying 4.10%")
    v2 = variants.rule_variants("Open an account today and get a $200 bonus. Limited time only.")
    assert "today" not in v2["alt"] and "Limited" not in v2["alt"]


def test_rewrite_scoring_counts_only_actually_unstable_concepts(offline_workspace):
    res = pipeline.run(adapter="mock", n=40, log=lambda *_: None)
    b2 = {c["id"]: c for c in res["batch2"]["concepts"]}
    imp, fa = res["improvement"], res["improvement_false_alarms"]
    for summary, want_unstable in ((imp, True), (fa, False)):
        if summary:
            assert summary["n"] == len(summary["per_concept"])
            for row in summary["per_concept"]:
                assert b2[row["id"]]["unstable"] is want_unstable
                assert row["lift_noise_95"] is None or row["lift_noise_95"] > 0
    if imp:
        # On the mock panel the rewrites drop planted fragile patterns, so the chosen wording should not get worse.
        assert imp["fragile_after"] <= imp["fragile_before"]
