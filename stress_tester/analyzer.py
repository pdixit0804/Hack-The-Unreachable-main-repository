"""Stability math.

For each concept we have k wordings (original + variants), each scored by the
panel, plus a repeat run of the original wording.

* Wording spread: highest minus lowest mean across the k wordings (1-10 scale).
* Noise baseline: how big a spread pure run-to-run randomness would produce
  for k means. We estimate the standard error of one run's mean (from
  per-persona answers if the panel returns them, otherwise from the
  original-vs-repeat gaps pooled across all concepts), then multiply by the
  expected range of k normal draws (d2 constant: 2.326 for k=5).
* Wording Stability Score (WSS) = spread / noise baseline. Near 1 means the
  wording changes act like noise; well above 1 means wording itself moves the answer.
* Permutation p-value (only with per-persona answers): shuffle answers across
  the k wordings and count how often a spread this large appears by chance.
"""
from __future__ import annotations

import math
import zlib

import numpy as np

from . import config

# Expected range of k iid standard normals (Tippett / d2 constants).
D2 = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847}


def _se_from_personas(runs) -> float | None:
    sds = [(r.sd, r.n) for r in runs if r.sd is not None and r.n > 1]
    if not sds:
        return None
    pooled_var = sum((n - 1) * sd**2 for sd, n in sds) / sum(n - 1 for _, n in sds)
    n_bar = sum(n for _, n in sds) / len(sds)
    return math.sqrt(pooled_var / n_bar)


def pooled_repeat_se(concept_runs: list[dict]) -> float | None:
    """SE of a run mean from original-vs-repeat gaps, pooled over concepts: Var(a-b)=2*SE^2."""
    gaps = [c["original"].mean - c["repeat"].mean for c in concept_runs if c.get("repeat")]
    if not gaps:
        return None
    return math.sqrt(sum(g * g for g in gaps) / (2 * len(gaps)))


def permutation_p(groups: list[list[int]], observed_spread: float, iters: int = 2000, seed: int = 0) -> float | None:
    if any(not g for g in groups):
        return None
    rng = np.random.default_rng(seed)
    pooled = np.concatenate([np.asarray(g, float) for g in groups])
    sizes = np.cumsum([len(g) for g in groups])[:-1]
    hits = 0
    for _ in range(iters):
        rng.shuffle(pooled)
        means = [part.mean() for part in np.split(pooled, sizes)]
        if max(means) - min(means) >= observed_spread - 1e-9:
            hits += 1
    return (hits + 1) / (iters + 1)


def analyze_concept(c: dict, fallback_se: float | None) -> dict:
    """c = {"concept", "original", "repeat", "variants": {kind: PanelResult}}"""
    wordings = {"original": c["original"], **c["variants"]}
    means = {k: r.mean for k, r in wordings.items()}
    spread = max(means.values()) - min(means.values())
    k = len(means)
    se = _se_from_personas([c["original"], c["repeat"], *c["variants"].values()]) or fallback_se
    noise_range = D2.get(k, 2.326) * se if se else None
    wss = spread / noise_range if noise_range else None
    p = None
    if all(r.responses for r in wordings.values()):
        p = permutation_p([r.responses for r in wordings.values()], spread, seed=zlib.crc32(c["concept"].id.encode()))
    unstable = bool(
        wss is not None and wss >= config.UNSTABLE_WSS and spread >= config.MIN_SPREAD and (p is None or p < config.UNSTABLE_P)
    )
    hi = max(means, key=means.get)
    lo = min(means, key=means.get)
    return {
        "id": c["concept"].id,
        "text": c["concept"].text,
        "means": means,
        "repeat_mean": c["repeat"].mean if c.get("repeat") else None,
        "spread": spread,
        "noise_range": noise_range,
        "se": se,
        "wss": wss,
        "p": p,
        "unstable": unstable,
        "best": hi,
        "worst": lo,
        "n": c["original"].n,
    }


def rank_flips(results: list[dict]) -> dict:
    """Rank concepts under each wording set; how much does a concept's rank move?"""
    kinds = list(results[0]["means"].keys())
    ranks: dict[str, dict[str, int]] = {}
    winners = {}
    for kind in kinds:
        order = sorted(results, key=lambda r: -r["means"].get(kind, r["means"]["original"]))
        winners[kind] = order[0]["id"]
        for pos, r in enumerate(order, 1):
            ranks.setdefault(r["id"], {})[kind] = pos
    moves = {cid: max(rk.values()) - min(rk.values()) for cid, rk in ranks.items()}
    return {"ranks": ranks, "max_move": moves, "winners": winners, "winner_changes": len(set(winners.values())) > 1}


def analyze_batch(concept_runs: list[dict]) -> dict:
    fallback_se = pooled_repeat_se(concept_runs)
    results = [analyze_concept(c, fallback_se) for c in concept_runs]
    return {"concepts": results, "flips": rank_flips(results), "pooled_repeat_se": fallback_se}
