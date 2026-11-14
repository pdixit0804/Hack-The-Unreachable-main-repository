"""Batch 3: a fresh held-out test of the memory, on 8 ads it has never seen.

Pre-registered order, so the test is clean:
  1. Load memory as it stands after batches 1+2 (memory/rules.json, observations.json).
  2. Claude rewrites the 8 new ads (data/concepts_batch3.csv) and tags their wording.
  3. Memory predicts which ads will be shaky. Predictions are SAVED to
     outputs/batch3/predictions.json before any panel answer is read.
  4. The panel scores every wording (same 30-persona Flashpoint panel as before).
  5. Compare predictions with what happened; add the multiple-testing correction.

Nothing in the main results (outputs/results.json, report.html, memory/) is changed.

    python3 scripts/batch3.py --panel flashpoint --personas 30
    python3 scripts/batch3.py --panel mock            # offline dry run
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from stress_tester import analyzer, config, features, learner, llm  # noqa: E402
from stress_tester.loader import load_concepts  # noqa: E402
from stress_tester.pipeline import Runner, _spearman  # noqa: E402

OUT = config.OUT_DIR / "batch3"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default="flashpoint")
    ap.add_argument("--personas", type=int, default=30)
    args = ap.parse_args()
    features.USE_REGEX = args.panel == "mock"
    if args.panel != "mock" and not llm.available():
        raise SystemExit("Needs ANTHROPIC_API_KEY in .env to write the new wordings.")
    OUT.mkdir(parents=True, exist_ok=True)

    concepts = load_concepts(config.DATA_DIR / "concepts_batch3.csv")
    obs, mem = learner.load_memory()
    rules = mem.get("rules", [])
    prev = json.loads((config.OUT_DIR / "results.json").read_text())
    if prev.get("adapter") != args.panel:
        print(f"note: memory comes from a '{prev.get('adapter')}' run, panel here is '{args.panel}'")
    old = prev["batch1"]["concepts"] + prev["batch2"]["concepts"]
    noise_ref = statistics.median(c["noise_range"] for c in old if c["noise_range"])
    se_ref = statistics.median(c["se"] for c in old if c["se"])
    cut = max(config.MIN_SPREAD, config.UNSTABLE_WSS * noise_ref)
    print(f"Memory: {len(obs)} observations from {len(old)} ads; saved rules: "
          + (", ".join(f"{r['feature']} {r['effect']:+.2f}" for r in rules if r["status"] == "fragile") or "none"))

    runner = Runner(args.panel, args.personas)
    print("Batch 3: writing and checking new wordings")
    p3 = runner.prepare(concepts)

    zero = [{"feature": f, "effect": 0.0} for f in learner.FEATS]
    preds = {}
    for cid, p in p3["prep"].items():
        t0 = p3["tags"][p["concept"].text]
        vt = [p3["tags"][t] for t in p["variants"].values()]
        a = learner.predict_spread(rules, t0, vt, se_ref)
        b = learner.predict_spread(zero, t0, vt, se_ref)
        preds[cid] = {"pred_spread": round(a, 3), "pred_unstable": a >= cut,
                      "pred_spread_no_memory": round(b, 3), "pred_unstable_no_memory": b >= cut}
    (OUT / "predictions.json").write_text(json.dumps({"cut": cut, "predictions": preds}, indent=2))
    print(f"Predictions saved BEFORE the panel: {sum(v['pred_unstable'] for v in preds.values())} of "
          f"{len(preds)} called shaky (cut {cut:.2f} points)")

    print("Batch 3: running panel")
    runner.prefetch(p3)
    runs = runner.run_panel(p3)
    a3 = analyzer.analyze_batch(runs)
    wrap = {"batch1": {"concepts": a3["concepts"]}, "batch2": {"concepts": []}}
    analyzer.apply_fdr(wrap)

    def conf(key):
        cs = a3["concepts"]
        tp = sum(c["unstable"] and preds[c["id"]][key] for c in cs)
        fp = sum((not c["unstable"]) and preds[c["id"]][key] for c in cs)
        fn = sum(c["unstable"] and not preds[c["id"]][key] for c in cs)
        tn = len(cs) - tp - fp - fn
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "accuracy": (tp + tn) / len(cs)}

    ev = {"memory": conf("pred_unstable"), "no_memory": conf("pred_unstable_no_memory"),
          "spearman": _spearman([preds[c["id"]]["pred_spread"] for c in a3["concepts"]],
                                [c["spread"] for c in a3["concepts"]]),
          "n_unstable": sum(c["unstable"] for c in a3["concepts"]), "fdr": wrap["fdr"], "cut": cut}
    rows = [{"id": c["id"], "text": c["text"], "spread": round(c["spread"], 2), "wss": round(c["wss"] or 0, 2),
             "p": round(c["p"], 4), "p_bh": c["p_bh"], "unstable": c["unstable"], "means": c["means"],
             **preds[c["id"]]} for c in a3["concepts"]]
    (OUT / "results.json").write_text(json.dumps({"adapter": args.panel, "personas": args.personas,
                                                  "evaluation": ev, "concepts": rows}, indent=2, default=str))

    print("\n=== Batch 3: 8 new ads ===")
    for r in rows:
        print(f"  {r['id']} swing {r['spread']:.2f}  p {r['p']:.3f}  {'SHAKY' if r['unstable'] else 'steady':6s}  "
              f"memory said {'shaky' if r['pred_unstable'] else 'steady'} (predicted {r['pred_spread']:.2f})")
    m, n = ev["memory"], ev["no_memory"]
    print(f"Shaky: {ev['n_unstable']} of {len(rows)} ({wrap['fdr']['n_survive']} survive the correction)")
    print(f"Memory caught {m['tp']} of {ev['n_unstable']}, {m['fp']} false alarms, accuracy {m['accuracy']:.0%} "
          f"(no memory: {n['accuracy']:.0%}); rank correlation {ev['spearman']}")
    print(f"Saved: {OUT / 'results.json'}")


if __name__ == "__main__":
    main()
