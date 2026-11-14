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
             ─► Claude rewrites fragile concepts to avoid the fragile patterns (retries once if any remain;
                a separate strict meaning check rejects rewrites that change the offer), re-tests them
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
python scripts/flashpoint_login.py    # sign in to Flashpoint in the browser; saves FLASHPOINT_TOKEN to .env
python scripts/flashpoint_probe.py    # list Flashpoint MCP tools + argument schemas
python scripts/flashpoint_trial.py    # one free 10-persona rating question; saves outputs/flashpoint_trial.json
python run.py --panel flashpoint      # real Flashpoint synthetic panel over MCP (batch mode, below)
python run.py --panel claude-mcp      # Claude drives Flashpoint via the API's MCP connector
python run.py --panel import          # paste in panel results run from Claude Desktop
```

| Flag | Default | What it does |
|---|---|---|
| `--panel` | `mock` | `mock`, `flashpoint`, `claude-mcp` or `import` |
| `--personas` | `40` | synthetic personas per panel run |
| `--claude` | `auto` | `auto` uses Claude (`claude-opus-5-5`) when `ANTHROPIC_API_KEY` is set; `on` / `off` force it |
| `--keep-memory` | off | start from the rules already in `memory/` instead of a blank slate |
| `--skip-rewrites` | off | don't re-test rewrites on the panel (saves a round of panel runs) |
| `--open` | off | open the HTML report when done |

Every Claude answer is cached in `outputs/cache/` and every panel result in `outputs/runs/<adapter>/`, so nothing is paid for twice. The Claude cache for the sample concepts is committed, so the demo replays with Claude's real wordings even without a key.

Output: `outputs/report.html` (the demo screen), `outputs/results.json`, `memory/rules.json`, `memory/observations.json`.

> **Heads-up:** `outputs/` and `memory/` are tracked in git and every run overwrites them. Don't commit them after a test run unless you mean to replace the demo results.

### Panel adapters

| Adapter | How it reaches the panel | Status |
|---|---|---|
| `mock` | simulated personas with **planted** wording effects (`stress_tester/panel/mock.py`) | works offline; for building and testing only |
| `flashpoint` | talks MCP (JSON-RPC over HTTP) to `FLASHPOINT_MCP_URL` with `FLASHPOINT_TOKEN`. **Batch mode:** creates one synthetic panel per segment with the `panel` tool, then asks the `tool_survey` agent to build one survey per wording type (one question per concept, about 6 surveys in all), starts every run, polls until done, and reads per-question answers. Both batches are scored in one round; batch-2 answers are still read only after the prediction is made. Panel and survey ids are kept in `outputs/flashpoint_state.json`. | written against the tools the probe lists; first live run pending |
| `claude-mcp` | Claude connects to Flashpoint through the Anthropic API's MCP connector, reads the tool schema itself, and returns per-persona scores | needs both keys |
| `import` | writes `outputs/panel_requests.csv`; run those through Flashpoint in Claude Desktop, paste results into `data/panel_import.csv` (`text,run_label,mean,n`, optional `responses`), run again | manual fallback |

None of the scripts or adapters buy real respondents. Paid fielding needs a separate payment-confirmation call that the code never makes.

`.env` settings: `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` (optional), `FLASHPOINT_MCP_URL`, `FLASHPOINT_TOKEN`, and for the single-call path `FLASHPOINT_PANEL_TOOL` / `FLASHPOINT_PANEL_ARGS` (a JSON template with `{text}` `{question}` `{n}` `{segment}`). See `.env.example`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Covers the stability math (`test_analyzer.py`), the Flashpoint response parser (`test_flashpoint_parsing.py`), the learner recovering the mock panel's planted effects plus an offline end-to-end run (`test_learner_and_pipeline.py`), and the rewriter's retry and rejection logic with a fake Claude (`test_rewriter_loop.py`). Tests run in a temp directory and never touch `outputs/` or `memory/`.

## How the numbers work

| Metric | Definition |
|---|---|
| Wording spread | highest minus lowest mean score across the original and its variants (1–10 scale) |
| Noise baseline | spread pure run-to-run randomness would produce for k wordings: SE of one run's mean (from per-persona answers, or pooled original-vs-repeat gaps) × expected range of k normal draws (2.33 for k=5) |
| Wording Stability Score (WSS) | spread ÷ noise baseline. ~1 = wording acts like noise; well above 1 = wording moves the answer |
| Unstable | WSS ≥ 1.5 **and** spread ≥ 1 point **and** permutation p < 0.05 (answers shuffled across wordings 2,000×) |
| Wording features | `jargon`, `negation`, `loss_frame`, `many_numbers` (3+ numbers), `long` (over ~22 words), `urgency`. Claude tags them (regex fallback offline); definitions in `stress_tester/config.py` |
| Rules | least-squares fit of each variant's score shift on the features it added/removed; 90% bootstrap CI over concepts |
| Improvement | on held-out batch 2: did memory flag the unstable concepts before running the panel (vs. no memory)? |
| Rewrites | scored only on concepts that were actually unstable (false-alarm rewrites reported separately). Headline: appeal of the rewrite vs. the original, beyond 95% run-to-run noise, and fragile patterns removed. Wording spread is also shown, but the stress test re-adds fragile patterns, so a rewrite fixes the chosen wording, not the idea's sensitivity. |

## Honest limits

* **Stable is not correct.** This says when a synthetic answer depends on wording, not whether real people agree. Unstable concepts get routed to a real-world test (e.g. a Flashpoint Market Experiment).
* 8 + 8 concepts is a proof of method, not a benchmark. Counts and intervals are always shown.
* The Flashpoint adapters haven't completed a full live run yet. Tool names and reply formats come from the probe and may need adjusting.
* The rewriter's retry and independent meaning check have been tested with a fake Claude, but they haven't run against live Claude yet. The new prompts aren't in the cache.
* The Market Experiment cost in the report ($4,500) is a 2025 podcast figure and may be out of date.
* Every number is labeled by source. The mock panel (`stress_tester/panel/mock.py`) has **planted** wording effects so the pipeline can be tested offline; mock results say nothing about real panels.

## Repo map

```
run.py                     one command for the whole loop
data/concepts.csv          16 consumer-banking concepts (batch 1 = learn, batch 2 = held-out)
stress_tester/
  config.py                paths, model, question, wording features, thresholds, costs
  loader.py                reads concepts.csv
  llm.py                   Claude calls (structured output, cached) and the on/off switch
  variants.py              Claude writes variants + meaning check (offline rules fallback)
  features.py              Claude tags wording features (regex fallback)
  panel/                   mock · flashpoint (MCP, batch mode) · claude_mcp · imported: same score() call, cached
  analyzer.py              spread, noise baseline, WSS, permutation test, rank flips
  learner.py               fits rules, bootstrap CIs, memory
  rewriter.py              Claude rewrites fragile concepts, retry loop, independent meaning check
  pipeline.py              learn → predict → verify → rewrite
  report.py                static HTML report
scripts/
  flashpoint_login.py      Flashpoint sign-in (MCP OAuth 2.1 + PKCE), writes FLASHPOINT_TOKEN to .env
  flashpoint_probe.py      prints the Flashpoint MCP server's tools and argument schemas
  flashpoint_trial.py      one small free synthetic-panel trial to learn the reply format
tests/                     pytest suite (runs in a temp dir)
memory/                    rules.json + observations.json (what the agent has learned)
outputs/                   report.html, results.json, cache/ (Claude), runs/ (panel results)
requirements.txt           runtime deps (anthropic, httpx, python-dotenv, numpy)
requirements-dev.txt       + pytest
```

Built by our team with Claude (see contributors).
