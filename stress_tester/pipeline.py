"""End-to-end run: learn on batch 1, predict and verify on held-out batch 2, rewrite."""
from __future__ import annotations

import datetime as dt
import json
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import numpy as np

from . import analyzer, config, features, learner, panel, rewriter, variants
from .loader import Concept, load_concepts
from .panel.imported import MissingPanelData


class Runner:
    def __init__(self, adapter: str, n: int, workers: int = 4, log=print):
        self.adapter, self.n, self.workers, self.log = adapter, n, workers, log
        self.missing = 0

    def _score(self, text, segment, label):
        try:
            return panel.score(self.adapter, text, segment, self.n, label)
        except MissingPanelData:
            self.missing += 1
            return None

    def prepare(self, concepts: list[Concept]) -> dict:
        """Variants + meaning check + feature tags. Cheap (Claude only, no panel)."""
        prep = {}
        for c in concepts:
            v = variants.make_variants(c.text)
            kept = {k: t for k, t in v["variants"].items() if v["checks"][k]["same_meaning"] and t.strip() != c.text}
            prep[c.id] = {"concept": c, "variants": kept, "all_variants": v["variants"], "checks": v["checks"], "source": v["source"]}
        texts = sorted({c.text for c in concepts} | {t for p in prep.values() for t in p["variants"].values()})
        tag_list = features.tag_many(texts)
        tags = dict(zip(texts, tag_list))
        return {"prep": prep, "tags": tags}

    @staticmethod
    def jobs_for(prepared: dict) -> list[tuple[str, str, str, str]]:
        jobs = []
        for cid, p in prepared["prep"].items():
            c = p["concept"]
            jobs.append((cid, "original", c.text, c.segment))
            jobs.append((cid, "repeat", c.text, c.segment))
            for kind, t in p["variants"].items():
                jobs.append((cid, kind, t, c.segment))
        return jobs

    def prefetch(self, *prepared: dict) -> None:
        items = [(t, seg, label) for p in prepared for (_, label, t, seg) in self.jobs_for(p)]
        panel.prefetch(self.adapter, items, self.n, log=self.log)

    def run_panel(self, prepared: dict) -> list[dict]:
        jobs = []
        for cid, p in prepared["prep"].items():
            c = p["concept"]
            jobs.append((cid, "original", c.text, c.segment))
            jobs.append((cid, "repeat", c.text, c.segment))
            for kind, t in p["variants"].items():
                jobs.append((cid, kind, t, c.segment))
        self.log(f"  panel: {len(jobs)} runs on '{self.adapter}' ({self.n} personas each)")
        with ThreadPoolExecutor(self.workers) as ex:
            results = list(ex.map(lambda j: self._score(j[2], j[3], j[1]), jobs))
        by_c: dict[str, dict] = {}
        for (cid, label, _, _), r in zip(jobs, results):
            d = by_c.setdefault(cid, {"concept": prepared["prep"][cid]["concept"], "variants": {}})
            if label in ("original", "repeat"):
                d[label] = r
            else:
                d["variants"][label] = r
        if self.missing:
            return []
        return list(by_c.values())


def _spearman(a, b) -> float | None:
    if len(a) < 3:
        return None
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def _dedupe(obs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for o in obs:
        key = (o["concept"], o["kind"], o["batch"])
        if key not in seen:
            seen.add(key)
            out.append(o)
    return out


def run(adapter: str = "mock", n: int = 40, fresh_memory: bool = True, skip_rewrites: bool = False, log=print) -> dict:
    features.USE_REGEX = adapter == "mock"
    concepts = load_concepts()
    b1 = [c for c in concepts if c.batch == 1]
    b2 = [c for c in concepts if c.batch == 2]
    if adapter == "import":
        (config.OUT_DIR / "panel_requests.csv").unlink(missing_ok=True)
    runner = Runner(adapter, n, log=log)

    prior_obs, prior_mem = ([], {"rules": []}) if fresh_memory else learner.load_memory()
    rules_before = prior_mem.get("rules", [])

    # ---- Batch 1: learn
    log("Batch 1 (learn): writing variants and checking meaning")
    p1 = runner.prepare(b1)
    # ---- Batch 2: prepare early so slow panels can score both batches in one round.
    # Batch 2's panel results are not looked at until after the prediction below.
    log("Batch 2 (held-out): writing variants")
    p2 = runner.prepare(b2)
    runner.prefetch(p1, p2)
    log("Batch 1: running panel")
    runs1 = runner.run_panel(p1)
    if runner.missing:
        runner.run_panel(p2)
        raise SystemExit(
            f"{runner.missing}+ panel results missing. Fill data/panel_import.csv from outputs/panel_requests.csv and re-run."
        )
    a1 = analyzer.analyze_batch(runs1)
    obs1 = learner.observations_from(runs1, p1["tags"], "batch1")
    obs_after1 = _dedupe(prior_obs + obs1)
    rules1 = learner.describe(learner.fit_rules(obs_after1))
    log("Learned rules: " + ", ".join(f"{r['feature']} {r['effect']:+.2f}" for r in rules1 if r["status"] == "fragile"))

    # ---- Predict batch 2 BEFORE running its panel
    noise_ref = statistics.median([c["noise_range"] for c in a1["concepts"] if c["noise_range"]])
    se_ref = statistics.median([c["se"] for c in a1["concepts"] if c["se"]])
    cut = max(config.MIN_SPREAD, config.UNSTABLE_WSS * noise_ref)
    preds = {}
    for cid, p in p2["prep"].items():
        tags0 = p2["tags"][p["concept"].text]
        vt = [p2["tags"][t] for t in p["variants"].values()]
        ps_after = learner.predict_spread(rules1, tags0, vt, se_ref)
        ps_before = learner.predict_spread(rules_before if rules_before else [{"feature": f, "effect": 0.0} for f in learner.FEATS], tags0, vt, se_ref)
        preds[cid] = {
            "pred_spread": ps_after,
            "pred_unstable": ps_after >= cut,
            "pred_spread_before": ps_before,
            "pred_unstable_before": ps_before >= cut,
        }

    log("Batch 2: running panel")
    runs2 = runner.run_panel(p2)
    a2 = analyzer.analyze_batch(runs2)

    # ---- Evaluate predictions on held-out batch 2
    def confusion(key):
        tp = sum(1 for c in a2["concepts"] if c["unstable"] and preds[c["id"]][key])
        fp = sum(1 for c in a2["concepts"] if not c["unstable"] and preds[c["id"]][key])
        fn = sum(1 for c in a2["concepts"] if c["unstable"] and not preds[c["id"]][key])
        tn = len(a2["concepts"]) - tp - fp - fn
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "accuracy": (tp + tn) / len(a2["concepts"])}

    actual = [c["spread"] for c in a2["concepts"]]
    evaluation = {
        "after": confusion("pred_unstable"),
        "before": confusion("pred_unstable_before"),
        "spearman_after": _spearman([preds[c["id"]]["pred_spread"] for c in a2["concepts"]], actual),
        "n_unstable_actual": sum(c["unstable"] for c in a2["concepts"]),
        "noise_ref": noise_ref,
        "pred_cut": cut,
    }
    mean_abs_err = statistics.fmean(abs(preds[c["id"]]["pred_spread"] - c["spread"]) for c in a2["concepts"])
    mean_abs_err_before = statistics.fmean(abs(preds[c["id"]]["pred_spread_before"] - c["spread"]) for c in a2["concepts"])
    evaluation["mae_after"], evaluation["mae_before"] = mean_abs_err, mean_abs_err_before

    # ---- Rewrite unstable batch 2 concepts and stress-test the rewrites
    log("Rewriting unstable held-out concepts")
    targets = [] if skip_rewrites else [c for c in a2["concepts"] if c["unstable"] or preds[c["id"]]["pred_unstable"]]
    rewrites = {}
    rw_concepts = []
    for c in targets:
        rw = rewriter.rewrite(c["text"], rules1)
        if rw.get("no_change"):  # nothing to fix with the known rules: don't re-run the panel on an identical text
            continue
        rewrites[c["id"]] = rw
        orig = p2["prep"][c["id"]]["concept"]
        rw_concepts.append(Concept(id=c["id"] + "-R", batch=2, segment=orig.segment, text=rw["text"]))
    a_rw = {"concepts": []}
    if rw_concepts:
        prw = runner.prepare(rw_concepts)
        runner.prefetch(prw)
        runs_rw = runner.run_panel(prw)
        a_rw = analyzer.analyze_batch(runs_rw)
        p2["prep"].update(prw["prep"])
        p2["tags"].update(prw["tags"])
    rw_by = {c["id"][:-2]: c for c in a_rw["concepts"]}

    # How we judge a rewrite (see README "How the numbers work"):
    # * Only concepts that were ACTUALLY unstable count toward the headline. Rewrites of
    #   false alarms (predicted fragile, measured stable) are reported separately, because
    #   re-testing an already-stable concept mostly measures noise and drags the average.
    # * Spread before/after is still reported, but the stress test deliberately re-adds
    #   fragile patterns (e.g. frame_flip adds a loss frame), so a rewrite cannot remove
    #   the concept's sensitivity to them. The rewrite's job is to stop the CHOSEN wording
    #   from carrying fragile patterns, so we also report fragile patterns removed and the
    #   appeal lift of the rewrite vs the original, compared with run-to-run noise.
    a2_by = {c["id"]: c for c in a2["concepts"]}
    fragile_feats = [r["feature"] for r in rules1 if r["status"] == "fragile"]

    def n_fragile(text: str) -> int:
        tags = p2["tags"].get(text, {})
        return sum(1 for f in fragile_feats if tags.get(f))

    def rewrite_summary(keys: list[str]) -> dict | None:
        if not keys:
            return None
        rows = []
        for k in keys:
            o, r = a2_by[k], rw_by[k]
            lift = r["means"]["original"] - o["means"]["original"]
            # Noise on a difference of two run means: sqrt(se_o^2 + se_r^2); 1.96x is ~95%.
            se_o, se_r = o.get("se"), r.get("se")
            noise = 1.96 * float(np.hypot(se_o, se_r)) if se_o is not None and se_r is not None else None
            rows.append({
                "id": k,
                "spread_before": o["spread"], "spread_after": r["spread"],
                "appeal_before": o["means"]["original"], "appeal_after": r["means"]["original"],
                "appeal_lift": lift, "lift_noise_95": noise,
                "lift_beyond_noise": bool(noise is not None and lift > noise),
                "fragile_before": n_fragile(o["text"]), "fragile_after": n_fragile(r["text"]),
                "unstable_after": r["unstable"],
            })
        mean = lambda key: statistics.fmean(x[key] for x in rows)  # noqa: E731
        return {
            "n": len(rows),
            "spread_before": mean("spread_before"),
            "spread_after": mean("spread_after"),
            "still_unstable": sum(x["unstable_after"] for x in rows),
            "appeal_before": mean("appeal_before"),
            "appeal_after": mean("appeal_after"),
            "appeal_lift": mean("appeal_lift"),
            "n_lift_beyond_noise": sum(x["lift_beyond_noise"] for x in rows),
            "fragile_before": sum(x["fragile_before"] for x in rows),
            "fragile_after": sum(x["fragile_after"] for x in rows),
            "per_concept": rows,
        }

    improvement = rewrite_summary([k for k in rw_by if a2_by[k]["unstable"]])
    improvement_false_alarms = rewrite_summary([k for k in rw_by if not a2_by[k]["unstable"]])
    lift_by = {x["id"]: x for s in (improvement, improvement_false_alarms) if s for x in s["per_concept"]}

    # ---- Keep learning: fold batch 2 into memory too
    obs2 = learner.observations_from(runs2, p2["tags"], "batch2")
    obs_all = _dedupe(obs_after1 + obs2)
    rules_final = learner.describe(learner.fit_rules(obs_all))
    learner.save_memory(
        obs_all,
        rules_final,
        {
            "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "adapter": adapter,
            "personas": n,
            "batches": ["batch1", "batch2"],
            "fragile_after_batch1": [r["feature"] for r in rules1 if r["status"] == "fragile"],
            "fragile_after_batch2": [r["feature"] for r in rules_final if r["status"] == "fragile"],
        },
    )

    # ---- Recommendations
    def recommend(c, batch):
        if not c["unstable"]:
            return "trust"
        rw = rw_by.get(c["id"])
        if batch == 1:
            return "reword (not re-tested)"
        if rw is not None and not rw["unstable"]:
            return "use the rewrite"
        lift = lift_by.get(c["id"])
        if lift and lift["lift_beyond_noise"] and lift["fragile_after"] < lift["fragile_before"]:
            # Rewrite scores higher and drops fragile patterns, but the idea is still wording-sensitive.
            return "use the rewrite + test in market"
        return "test in market"

    def pack(prepared, analysis, batch):
        rows = []
        for c in analysis["concepts"]:
            p = prepared["prep"][c["id"]]
            row = dict(c)
            row["variants"] = p["variants"]
            row["checks"] = p["checks"]
            row["dropped"] = [k for k in p["all_variants"] if k not in p["variants"]]
            row["tags"] = {t: prepared["tags"][t] for t in [c["text"], *p["variants"].values()]}
            row["recommendation"] = recommend(c, batch)
            if c["id"] in preds:
                row.update(preds[c["id"]])
            if c["id"] in rewrites:
                row["rewrite"] = rewrites[c["id"]]
                row["rewrite_result"] = rw_by.get(c["id"])
            rows.append(row)
        return rows

    sources = {r.source for runs in (runs1, runs2) for c in runs for r in [c["original"]]}
    results = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "adapter": adapter,
        "data_source": sorted(sources),
        "claude_used": any(p["source"] == "claude" for p in p1["prep"].values()),
        "model": config.MODEL,
        "personas": n,
        "question": config.QUESTION,
        "batch1": {"concepts": pack(p1, a1, 1), "flips": a1["flips"], "pooled_repeat_se": a1["pooled_repeat_se"]},
        "batch2": {"concepts": pack(p2, a2, 2), "flips": a2["flips"], "pooled_repeat_se": a2["pooled_repeat_se"]},
        "rules_before": rules_before,
        "rules_after_batch1": rules1,
        "rules_final": rules_final,
        "evaluation": evaluation,
        "improvement": improvement,
        "improvement_false_alarms": improvement_false_alarms,
        "panel_runs": sum(2 + len(p["variants"]) for p in list(p1["prep"].values()) + list(p2["prep"].values())),
        "planted": _planted() if adapter == "mock" else None,
        "market_experiment_cost": config.MARKET_EXPERIMENT_COST,
    }
    config.OUT_DIR.mkdir(exist_ok=True)
    (config.OUT_DIR / "results.json").write_text(json.dumps(results, indent=2, default=_jsonable))
    return results


def _planted():
    from .panel.mock import PLANTED

    return PLANTED


def _jsonable(o):
    if hasattr(o, "__dataclass_fields__"):
        return asdict(o)
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o))
