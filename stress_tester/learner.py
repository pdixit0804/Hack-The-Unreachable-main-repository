"""Learns which wording features move the panel, and keeps them in memory.

Every variant gives one observation:
    delta = variant mean - reference mean   (reference = average of original and repeat)
    x     = features(variant) - features(original)   (each entry -1, 0 or +1)

We fit delta ~ x . beta by least squares (tiny ridge for stability), so beta[f]
is "how many points appeal moves when the wording adds feature f". Confidence
intervals come from a bootstrap over concepts. Observations accumulate in
memory/observations.json, so every new batch refits on everything seen so far:
that is the self-improving part.
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np

from . import config, llm

FEATS = list(config.FEATURES)


def observations_from(concept_runs: list[dict], tags: dict[str, dict], batch_label: str) -> list[dict]:
    obs = []
    for c in concept_runs:
        ref = (c["original"].mean + c["repeat"].mean) / 2 if c.get("repeat") else c["original"].mean
        f0 = tags[c["concept"].text]
        for kind, r in c["variants"].items():
            fv = tags[r.text]
            obs.append(
                {
                    "concept": c["concept"].id,
                    "batch": batch_label,
                    "kind": kind,
                    "delta": r.mean - ref,
                    "x": {f: fv[f] - f0[f] for f in FEATS},
                }
            )
    return obs


def _fit(obs: list[dict], ridge: float = 0.1) -> np.ndarray:
    X = np.array([[o["x"][f] for f in FEATS] for o in obs], float)
    y = np.array([o["delta"] for o in obs], float)
    A = X.T @ X + ridge * np.eye(len(FEATS))
    return np.linalg.solve(A, X.T @ y)


def fit_rules(obs: list[dict], boot: int = 1000, seed: int = 7) -> list[dict]:
    beta = _fit(obs)
    concepts = sorted({o["concept"] for o in obs})
    by_c = {c: [o for o in obs if o["concept"] == c] for c in concepts}
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(boot):
        sample = [o for c in rng.choice(concepts, len(concepts)) for o in by_c[c]]
        draws.append(_fit(sample))
    draws = np.array(draws)
    lo, hi = np.percentile(draws, [5, 95], axis=0)  # 90% interval
    rules = []
    for i, f in enumerate(FEATS):
        n_var = sum(1 for o in obs if o["x"][f] != 0)
        n_con = len({o["concept"] for o in obs if o["x"][f] != 0})
        solid = n_var >= 3 and abs(beta[i]) >= config.MIN_RULE_EFFECT and (lo[i] > 0 or hi[i] < 0)
        rules.append(
            {
                "feature": f,
                "definition": config.FEATURES[f],
                "effect": round(float(beta[i]), 2),
                "ci90": [round(float(lo[i]), 2), round(float(hi[i]), 2)],
                "n_variants": n_var,
                "n_concepts": n_con,
                "status": "fragile" if solid else ("weak evidence" if n_var else "not seen yet"),
            }
        )
    return rules


def predict_deltas(rules: list[dict], x: dict[str, int]) -> float:
    eff = {r["feature"]: r["effect"] for r in rules}
    return sum(eff[f] * x[f] for f in FEATS)


def predict_spread(rules: list[dict], orig_tags: dict, variant_tags: list[dict], se: float = 0.0,
                   sims: int = 4000, seed: int = 11) -> float:
    """Expected observed spread: range of (predicted wording shifts + run noise with this SE)."""
    preds = np.array([0.0] + [predict_deltas(rules, {f: v[f] - orig_tags[f] for f in FEATS}) for v in variant_tags])
    if se <= 0:
        return float(preds.max() - preds.min())
    draws = preds + np.random.default_rng(seed).normal(0, se, (sims, len(preds)))
    return float((draws.max(1) - draws.min(1)).mean())


_RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"feature": {"type": "string"}, "rule": {"type": "string"}, "advice": {"type": "string"}},
                "required": ["feature", "rule", "advice"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rules"],
    "additionalProperties": False,
}


def _template_text(r: dict) -> tuple[str, str]:
    direction = "drops" if r["effect"] < 0 else "rises"
    rule = (
        f"When a wording adds {r['feature'].replace('_', ' ')}, synthetic appeal {direction} by about "
        f"{abs(r['effect']):.1f} points (90% CI {r['ci90'][0]:+.1f} to {r['ci90'][1]:+.1f}; "
        f"{r['n_variants']} variants, {r['n_concepts']} concepts)."
    )
    advice = f"Concepts that depend on {r['feature'].replace('_', ' ')} are fragile; reword without it or test in market."
    return rule, advice


def describe(rules: list[dict]) -> list[dict]:
    fragile = [r for r in rules if r["status"] == "fragile"]
    texts = {}
    if fragile and llm.available():
        out = llm.ask_json(
            system="You explain survey-methods findings to marketing teams in one plain sentence each. Never overstate.",
            prompt=(
                "These wording effects were measured on a synthetic (AI persona) panel scoring appeal on 1-10. "
                "For each, write `rule` (what happens, with the number, CI and counts) and `advice` "
                "(what a copywriter should do). Keep each under 35 words.\n\n"
                + json.dumps(fragile, indent=2)
            ),
            schema=_RULE_SCHEMA,
        )
        texts = {r["feature"]: (r["rule"], r["advice"]) for r in out["rules"]}
    for r in rules:
        if r["status"] == "fragile":
            r["rule"], r["advice"] = texts.get(r["feature"], _template_text(r))
    return rules


def load_memory() -> tuple[list[dict], dict]:
    obs = json.loads(config.OBS_PATH.read_text()) if config.OBS_PATH.exists() else []
    mem = json.loads(config.RULES_PATH.read_text()) if config.RULES_PATH.exists() else {"rules": [], "history": []}
    return obs, mem


def save_memory(obs: list[dict], rules: list[dict], history_entry: dict) -> dict:
    _, mem = load_memory()
    mem["rules"] = rules
    mem["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    mem["n_observations"] = len(obs)
    mem.setdefault("history", []).append(history_entry)
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    config.OBS_PATH.write_text(json.dumps(obs, indent=1))
    config.RULES_PATH.write_text(json.dumps(mem, indent=2))
    return mem
