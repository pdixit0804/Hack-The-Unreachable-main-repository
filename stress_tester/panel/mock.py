"""Offline mock panel with PLANTED wording effects.

This is not real data. It exists so the whole pipeline (and the demo) runs with
no keys and no network. Each simulated persona has a few traits and reacts to
surface wording features, so the learner has something real to find. The
planted effects are listed in PLANTED so anyone can check whether the learner
recovered them.
"""
from __future__ import annotations

import hashlib

import numpy as np

from ..features import regex_tags
from . import summarize

# Average effect (points on 1-10) each feature has on the simulated panel.
# Heterogeneous by persona: e.g. jargon helps finance-savvy personas and hurts the rest.
PLANTED = {
    "jargon": -0.9,
    "negation": -0.6,
    "loss_frame": -0.8,
    "many_numbers": -0.7,
    "long": -0.3,
    "urgency": -0.5,
}


def _seed(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _personas(segment: str, n: int) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(_seed("personas", segment, n))
    return {
        "literacy": rng.uniform(0, 1, n),     # financial literacy
        "skeptic": rng.uniform(0, 1, n),      # distrust of marketing claims
        "loss_averse": rng.uniform(0, 1, n),
        "baseline": rng.normal(0, 0.8, n),    # some people just rate everything higher
    }


def _concept_appeal(text: str) -> float:
    # A stable "true appeal" per underlying offer: keyed on the digits and key nouns,
    # so paraphrases of the same offer share roughly the same base.
    rng = np.random.default_rng(_seed("appeal", "".join(sorted(set(c for c in text.lower() if c.isdigit())))))
    return float(6.0 + rng.uniform(-1.0, 1.2))


def score(text: str, segment: str, n: int, run_label: str):
    p = _personas(segment, n)
    f = regex_tags(text)
    rng = np.random.default_rng(_seed("run", text, run_label, n))
    x = np.full(n, _concept_appeal(text)) + p["baseline"]
    x += f["jargon"] * (PLANTED["jargon"] + 1.6 * (p["literacy"] - 0.5))
    x += f["negation"] * (PLANTED["negation"] - 0.8 * (p["skeptic"] - 0.5))
    x += f["loss_frame"] * (PLANTED["loss_frame"] + 1.2 * (p["loss_averse"] - 0.5))
    x += f["many_numbers"] * (PLANTED["many_numbers"] + 0.8 * (p["literacy"] - 0.5))
    x += f["long"] * PLANTED["long"]
    x += f["urgency"] * (PLANTED["urgency"] - 1.0 * (p["skeptic"] - 0.5))
    x += rng.normal(0, 1.1, n)  # run-to-run answer noise
    responses = np.clip(np.rint(x), 1, 10).astype(int).tolist()
    return summarize(text, run_label, responses, adapter="mock", source="mock (simulated, planted effects)")
