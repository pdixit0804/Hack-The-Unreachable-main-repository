import math

import numpy as np

from stress_tester import analyzer, config
from stress_tester.loader import Concept
from stress_tester.panel import PanelResult, summarize


def _res(label, responses):
    return summarize("t", label, responses, adapter="test")


def _concept(means_by_wording, n=40, sd=1.0, seed=0):
    """Concept whose wordings have given true means and per-persona noise sd."""
    rng = np.random.default_rng(seed)
    mk = lambda label, m: _res(label, np.clip(np.rint(rng.normal(m, sd, n)), 1, 10).astype(int).tolist())
    runs = {k: mk(k, m) for k, m in means_by_wording.items()}
    return {
        "concept": Concept("T1", 1, "seg", "text"),
        "original": runs.pop("original"),
        "repeat": mk("repeat", means_by_wording["original"]),
        "variants": runs,
    }


def test_spread_and_noise_baseline_match_hand_calculation():
    c = {
        "concept": Concept("T", 1, "s", "x"),
        "original": PanelResult("x", "original", mean=6.0, n=40, sd=None),
        "repeat": PanelResult("x", "repeat", mean=6.2, n=40, sd=None),
        "variants": {"a": PanelResult("x", "a", mean=5.0, n=40), "b": PanelResult("x", "b", mean=7.0, n=40),
                     "c": PanelResult("x", "c", mean=6.0, n=40), "d": PanelResult("x", "d", mean=6.1, n=40)},
    }
    out = analyzer.analyze_concept(c, fallback_se=0.5)
    assert out["spread"] == 2.0  # 7.0 - 5.0
    assert math.isclose(out["noise_range"], analyzer.D2[5] * 0.5)  # k = 5 wordings
    assert math.isclose(out["wss"], 2.0 / (analyzer.D2[5] * 0.5))
    assert out["p"] is None  # no per-persona answers -> no permutation test
    assert out["unstable"]  # wss 1.72 >= 1.5 and spread >= 1


def test_real_wording_effect_is_flagged_unstable():
    c = _concept({"original": 6.0, "plain": 6.0, "alt": 6.0, "frame_flip": 3.5, "reordered": 6.0})
    out = analyzer.analyze_concept(c, fallback_se=None)
    assert out["unstable"] and out["p"] < config.UNSTABLE_P and out["worst"] == "frame_flip"


def test_pure_noise_is_not_flagged():
    flagged = 0
    for seed in range(20):
        c = _concept({k: 6.0 for k in ("original", "plain", "alt", "frame_flip", "reordered")}, seed=seed)
        flagged += analyzer.analyze_concept(c, fallback_se=None)["unstable"]
    assert flagged <= 2  # false-alarm rate stays small (permutation p < 0.05 + WSS + spread gates)


def test_permutation_p_is_large_for_identical_groups_and_small_for_separated():
    same = [[5, 6, 7, 6, 5, 6] for _ in range(3)]
    assert analyzer.permutation_p(same, observed_spread=0.0) > 0.9
    apart = [[2, 2, 3, 2, 3, 2], [8, 9, 8, 9, 8, 9], [5, 5, 6, 5, 6, 5]]
    assert analyzer.permutation_p(apart, observed_spread=6.0) < 0.01


def test_pooled_repeat_se():
    runs = [{"original": PanelResult("x", "o", 6.0, 40), "repeat": PanelResult("x", "r", 6.4, 40)},
            {"original": PanelResult("x", "o", 5.0, 40), "repeat": PanelResult("x", "r", 4.6, 40)}]
    assert math.isclose(analyzer.pooled_repeat_se(runs), math.sqrt((0.16 + 0.16) / 4))


def test_apply_fdr_benjamini_hochberg():
    from stress_tester.analyzer import apply_fdr

    ps = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
    res = {"batch1": {"concepts": [{"id": f"C{i}", "p": p, "unstable": p < 0.05} for i, p in enumerate(ps[:4])]},
           "batch2": {"concepts": [{"id": f"C{i + 4}", "p": p, "unstable": p < 0.05} for i, p in enumerate(ps[4:])]}}
    apply_fdr(res)
    # Textbook BH at q=0.05 with m=8: only the two smallest p-values are discoveries.
    assert res["fdr"]["n_flagged"] == 5 and res["fdr"]["survivors"] == ["C0", "C1"]
    adj = [c["p_bh"] for b in ("batch1", "batch2") for c in res[b]["concepts"]]
    assert adj == sorted(adj) and abs(adj[0] - 0.008) < 1e-9
