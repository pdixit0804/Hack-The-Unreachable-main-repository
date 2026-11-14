"""Wording Stress-Tester: one command runs the whole loop.

    python run.py                    # mock panel, no keys needed
    python run.py --panel flashpoint # real Flashpoint synthetic panel over MCP
    python run.py --panel claude-mcp # Claude drives Flashpoint via the MCP connector
    python run.py --panel import     # results pasted in from Claude Desktop runs
"""
from __future__ import annotations

import argparse
import webbrowser

from stress_tester import llm, pipeline, report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--panel", default="mock", choices=["mock", "flashpoint", "claude-mcp", "import"])
    ap.add_argument("--personas", type=int, default=40, help="synthetic personas per panel run")
    ap.add_argument("--claude", default="auto", choices=["auto", "on", "off"],
                    help="use Claude for variants/tags/rules/rewrites (auto = if ANTHROPIC_API_KEY is set)")
    ap.add_argument("--keep-memory", action="store_true", help="start from memory/ instead of a blank slate")
    ap.add_argument("--open", action="store_true", help="open the HTML report when done")
    args = ap.parse_args()

    llm.set_mode(args.claude)
    print(f"Claude: {'on' if llm.available() else 'off (offline rules)'} | panel: {args.panel}")
    results = pipeline.run(adapter=args.panel, n=args.personas, fresh_memory=not args.keep_memory)
    path = report.build(results)
    ev, imp = results["evaluation"], results["improvement"]
    print("\n=== Held-out batch 2 ===")
    print(f"Unstable concepts (actual): {ev['n_unstable_actual']} of {len(results['batch2']['concepts'])}")
    a = ev["after"]
    print(f"Memory predicted them before any panel run: {a['tp']} caught, {a['fn']} missed, {a['fp']} false alarms "
          f"(accuracy {a['accuracy']:.0%}; with no memory: {ev['before']['accuracy']:.0%})")
    if imp:
        print(f"Rewrites: avg wording spread {imp['spread_before']:.2f} -> {imp['spread_after']:.2f} points "
              f"({imp['still_unstable']} of {imp['n']} still unstable)")
    print(f"Report: {path}")
    if args.open:
        webbrowser.open(path.as_uri())


if __name__ == "__main__":
    main()
