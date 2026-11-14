"""Rewrite the unstable held-out ads from a saved run, without re-running the panel.

    python scripts/rewrite_flagged.py            # uses Claude if ANTHROPIC_API_KEY is set
    python scripts/rewrite_flagged.py --claude off

Reads outputs/results.json (e.g. the committed live Flashpoint run), takes every
batch-2 concept the panel measured as unstable, and rewrites it with the rules
memory had learned after batch 1 (the same rewriter the pipeline uses: retry if
fragile patterns remain, separate meaning check).

Writes only NEW files, so the saved results are never touched:
  outputs/rewrites_suggested.json   every rewrite, what changed, patterns left, meaning check
  outputs/rewrite_requests.csv      the accepted rewrites in panel_requests.csv format
                                    (original + repeat + variants come later via --panel import)

These rewrites have NOT been scored on any panel. Present them as suggestions.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tester import config, features, llm, rewriter  # noqa: E402
from stress_tester.loader import load_concepts  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--claude", default="auto", choices=["auto", "on", "off"])
    ap.add_argument("--results", default=str(config.OUT_DIR / "results.json"))
    args = ap.parse_args()
    llm.set_mode(args.claude)

    res = json.loads(Path(args.results).read_text())
    # Tag text the same way the saved run did: regexes for mock, Claude otherwise.
    features.USE_REGEX = res["adapter"] == "mock"
    rules1 = res["rules_after_batch1"]
    targets = [c for c in res["batch2"]["concepts"] if c["unstable"]]
    print(f"Claude: {'on' if llm.available() else 'off (offline rules)'} | source run: {res['adapter']} "
          f"| fragile rules: {[r['feature'] for r in rules1 if r['status'] == 'fragile'] or 'none'}")
    print(f"Rewriting {len(targets)} unstable held-out concept(s)")

    out = []
    for c in targets:
        rw = rewriter.rewrite(c["text"], rules1)
        status = "no change needed" if rw.get("no_change") else ("rejected: meaning changed" if not rw["same_meaning"] else "accepted")
        out.append({
            "id": c["id"],
            "original": c["text"],
            "spread_measured": c["spread"],
            "rewrite": rw["text"],
            "status": status,
            "changed": rw.get("changed", ""),
            "fragile_left": rw.get("fragile_left", []),
            "attempts": rw.get("attempts", 1),
            "meaning_check": rw.get("meaning_check", {}),
            "source": rw.get("source"),
        })
        print(f"  {c['id']} [{status}] {rw['text']}")

    config.OUT_DIR.mkdir(exist_ok=True)
    note = "Suggestions only: these rewrites have not been scored on any panel."
    (config.OUT_DIR / "rewrites_suggested.json").write_text(
        json.dumps({"note": note, "source_run": res["adapter"], "generated_from": res["generated"], "rewrites": out}, indent=2)
    )
    accepted = [r for r in out if r["status"] == "accepted"]
    segment = {c.id: c.segment for c in load_concepts()}
    with open(config.OUT_DIR / "rewrite_requests.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "text", "segment"])
        for r in accepted:
            w.writerow([r["id"] + "-R", r["rewrite"], segment.get(r["id"]) or ""])
    print(f"\n{len(accepted)} accepted. Wrote outputs/rewrites_suggested.json and outputs/rewrite_requests.csv. {note}")


if __name__ == "__main__":
    main()
