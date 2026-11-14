# Wording Stress-Tester

**Before you trust a synthetic answer, stress-test it.**

Built at *Hack the Unreachable* (Fordham Gabelli, Nov 14 2026, powered by Flashpoint.AI and Anthropic), Self-Improving AI track.

Brands increasingly test ads and messages on synthetic respondents (AI personas): instant and cheap. But a synthetic panel can give a different answer when the *same* idea is worded differently, and nobody can tell whether the wording or the idea produced the score. This agent finds out, learns which wording patterns make synthetic answers unreliable, and gets better at predicting it with every batch.

## How it works

```
concepts.csv ─► Claude writes 4 same-meaning wordings ─► Claude checks meaning held
             ─► Flashpoint synthetic panel scores every wording (+ the original asked twice = noise check)
             ─► Wording Stability Score per concept (spread vs. noise, permutation test)
             ─► learner: which wording features move the score?  ─► memory/rules.json
             ─► next batch: memory predicts fragile concepts BEFORE any panel run
             ─► Claude rewrites fragile concepts to avoid the fragile patterns, re-tests them
             ─► report: trust / use the rewrite / test in market (route to real people)
```

**Self-improving:** rules are learned on batch 1, then tested on a held-out batch 2 that the agent never learned from. Observations accumulate in `memory/`, so each new batch refits on everything seen so far.

## Run it

```bash
pip install -r requirements.txt
python run.py --open            # mock panel, works with no keys at all
```

With keys (copy `.env.example` to `.env`, which git ignores):

```bash
python scripts/flashpoint_probe.py    # list Flashpoint MCP tools + argument schemas
python run.py --panel flashpoint      # real Flashpoint synthetic panel over MCP
python run.py --panel claude-mcp      # Claude drives Flashpoint via the API's MCP connector
python run.py --panel import          # paste in panel results run from Claude Desktop
```

Claude (`claude-opus-5-5`) is used automatically when `ANTHROPIC_API_KEY` is set; `--claude off` forces the offline rules. Every Claude answer and every panel run is cached under `outputs/`, so nothing is paid for twice.

Output: `outputs/report.html` (the demo screen), `outputs/results.json`, `memory/rules.json`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Covers the stability math, the Flashpoint response parser, the learner (recovers the mock panel's planted effects) and an offline end-to-end run. Tests run in a temp directory and never touch `outputs/` or `memory/`.

## How the numbers work

| Metric | Definition |
|---|---|
| Wording spread | highest minus lowest mean score across the original and its variants (1–10 scale) |
| Noise baseline | spread pure run-to-run randomness would produce for k wordings: SE of one run's mean (from per-persona answers, or pooled original-vs-repeat gaps) × expected range of k normal draws (2.33 for k=5) |
| Wording Stability Score (WSS) | spread ÷ noise baseline. ~1 = wording acts like noise; well above 1 = wording moves the answer |
| Unstable | WSS ≥ 1.5 **and** spread ≥ 1 point **and** permutation p < 0.05 (answers shuffled across wordings 2,000×) |
| Rules | least-squares fit of each variant's score shift on the features it added/removed; 90% bootstrap CI over concepts |
| Improvement | on held-out batch 2: did memory flag the unstable concepts before running the panel (vs. no memory)? and are rewrites more stable than originals? |

## Honest limits

* **Stable is not correct.** This says when a synthetic answer depends on wording, not whether real people agree. Unstable concepts get routed to a real-world test (e.g. a Flashpoint Market Experiment).
* 8 + 8 concepts is a proof of method, not a benchmark. Counts and intervals are always shown.
* Every number is labeled by source. The mock panel (`stress_tester/panel/mock.py`) has **planted** wording effects so the pipeline can be tested offline; mock results say nothing about real panels.

## Repo map

```
run.py                     one command for the whole loop
data/concepts.csv          16 banking concepts (batch 1 = learn, batch 2 = held-out)
stress_tester/
  variants.py              Claude writes variants + meaning check (offline rules fallback)
  features.py              Claude tags wording features (regex fallback)
  panel/                   mock · flashpoint (MCP) · claude_mcp · imported — same score() call
  analyzer.py              spread, noise baseline, WSS, permutation test, rank flips
  learner.py               fits rules, bootstrap CIs, memory
  rewriter.py              Claude rewrites fragile concepts
  pipeline.py              learn → predict → verify → rewrite
  report.py                static HTML report
memory/                    rules.json + observations.json (what the agent has learned)
```

Built by our team with Claude (see contributors).
