"""Rewriter loop: retry when fragile patterns remain, and an independent meaning check.

Claude is replaced by a fake, so these run offline with no key.
"""
from stress_tester import features, llm, pipeline, rewriter

RULES = [{"feature": "jargon", "definition": "acronyms like APY", "effect": -1.0, "status": "fragile"},
         {"feature": "urgency", "definition": "time pressure", "effect": -0.5, "status": "fragile"}]
TEXT = "Act now: lock in a 12-month CD at 4.5% APY before rates drop."


def _fake_claude(monkeypatch, rewrites, meaning_ok=True):
    calls = {"rewrite": 0, "check": 0}

    def ask_json(system, prompt, schema, **kw):
        if "rewrite" in schema["properties"]:
            calls["rewrite"] += 1
            return {"rewrite": rewrites[min(calls["rewrite"], len(rewrites)) - 1], "changed": "x", "same_meaning": True}
        calls["check"] += 1
        return {"same_meaning": meaning_ok, "reason": "ok" if meaning_ok else "dropped the 12-month term"}

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "ask_json", ask_json)
    monkeypatch.setattr(features, "USE_REGEX", True)  # tag with regexes so no tagging call is needed
    return calls


def test_retries_once_when_fragile_patterns_remain(monkeypatch):
    calls = _fake_claude(monkeypatch, ["Lock in 4.5% APY on a 12-month certificate.",
                                       "Lock in a 4.5% yearly rate on a 12-month savings certificate."])
    out = rewriter.rewrite(TEXT, RULES)
    assert calls["rewrite"] == 2 and out["attempts"] == 2
    assert out["fragile_left"] == [] and "APY" not in out["text"]
    assert out["same_meaning"] and calls["check"] == 1


def test_keeps_best_candidate_and_stops_at_max_tries(monkeypatch):
    calls = _fake_claude(monkeypatch, ["Act now: 4.5% on a 12-month savings certificate.",
                                       "Act now: 4.5% APY on a 12-month CD."])
    out = rewriter.rewrite(TEXT, RULES, max_tries=2)
    assert calls["rewrite"] == 2
    assert out["fragile_left"] == ["urgency"]  # first candidate (1 left) beats second (2 left)


def test_independent_meaning_check_can_reject(monkeypatch):
    _fake_claude(monkeypatch, ["Lock in a 4.5% yearly rate on a savings certificate."], meaning_ok=False)
    out = rewriter.rewrite(TEXT, RULES)
    assert out["same_meaning"] is False
    assert "12-month" in out["meaning_check"]["reason"]


def test_pipeline_never_panel_tests_a_rejected_rewrite(offline_workspace, monkeypatch):
    real = rewriter.rewrite

    def reject_all(text, rules, **kw):
        out = real(text, rules, **kw)
        out["same_meaning"] = False
        out["meaning_check"] = {"same_meaning": False, "reason": "test"}
        return out

    monkeypatch.setattr(rewriter, "rewrite", reject_all)
    res = pipeline.run(adapter="mock", n=40, log=lambda *_: None)
    b2 = res["batch2"]["concepts"]
    assert res["rewrites_rejected"] == sum("rewrite_rejected" in c for c in b2)
    assert not any("rewrite_result" in c for c in b2)
    assert all(c["recommendation"] in ("trust", "test in market") for c in b2)
