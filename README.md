# FlashFeud

**Is your synthetic score about the idea, or just the wording?**

FlashFeud stress-tests synthetic panels. It rewords each ad without changing what it says, has a synthetic panel score every version, and tells you which scores you can trust. Before you trust a synthetic answer, stress-test it.

Built at *Hack the Unreachable* (Fordham Gabelli, Nov 14 2026, powered by Flashpoint.AI and Anthropic), Self-Improving AI track. The code package is still called `stress_tester` (the project's working name was Wording Stress-Tester).

## Why it matters

Marketing and insights teams test ads on synthetic panels (AI personas) because they're instant and cheap. But a synthetic panel can give a different score when the *same* offer is worded differently, and nobody can tell whether the wording or the idea produced the number. A good idea gets dropped, or a weak one shipped, because of phrasing.

Example from the live run (concept C03, a bank's overdraft ad, 30 Flashpoint personas per wording):

| Wording | Appeal (1–10) |
|---|---|
| "Stop losing money to overdraft fees. Our account never charges you $35 for going $5 over." (original) | **8.43** |
| "Our account never charges you $35 for going $5 over. So you can stop losing money to overdraft fees." | 7.17 |
| "Say goodbye to costly overdraft fees. Go $5 over with our account and you'll never get hit with a $35 charge." | 6.47 |

Same offer, a 1.97-point swing. Asking the original twice moved it only 0.17 (8.43 vs 8.27), so the swing is 2.5× the noise (p = 0.002). That's wording, not luck.

## Results: live Flashpoint panel

16 consumer-banking ads, 30 synthetic personas per wording, 87 panel runs (`outputs/results.json`, adapter `flashpoint`).

* **8 of 16 ads changed score with wording alone.** Their swings ran 1.4 to 2.8 points on the 10-point scale. Asking the identical wording twice moves the score about 0.5 points on average.
* **It held on the held-out batch:** 4 of 8 in batch 1 and 4 of 8 in batch 2. In both batches, the top-scoring ad changed with the wording, so a single run can rank ads in the wrong order.
* **Worst case, C06:** a 2.83-point swing, 3.1× the noise, p < 0.001.
* **Memory learned one rule:** copy over about 22 words scores about 0.4 points lower (90% interval −0.65 to −0.1).
* **Memory did not predict which unseen ads would be shaky.** It flagged 0 of the 4 shaky held-out ads in advance. Accuracy was 50%, the same as no memory, and the rank correlation between predicted and actual swing was about −0.05. Jargon and loss framing hurt scores on the simulated panel, where we built those effects in, but showed no clear effect on the live one. So you can't skip the stress test by eyeballing copy.
* **Rewrites were not re-tested** in the live run (`--skip-rewrites`). To get suggested rewrites for the shaky held-out ads without touching the saved results, run `python scripts/rewrite_flagged.py`. It writes `outputs/rewrites_suggested.json` and `outputs/rewrite_requests.csv`. Those rewrites are unscored suggestions until someone runs them on a panel.

| Wording pattern (learned from batch 1) | Simulated panel | Live panel |
|---|---|---|
| Jargon (APY, CD) | −1.27 | +0.30 (weak) |
| Loss framing | −0.81 | +0.08 (weak) |
| Negation ("no fees") | −0.45 | −0.64 (weak) |
| Long wording | −0.43 | −0.42 (fragile) |

Effects are in points on the 1–10 scale. "Weak" means the interval includes zero. "Fragile" means the effect is clear enough to save to memory.

## See the results

Open `outputs/report.html` in any browser; no server is needed. It's the FlashFeud board:

* a scoreboard with three numbers: offers that changed score with wording, shaky new offers called before testing, and round 2 accuracy;
* a board for each offer, with every wording ranked by score and a verdict: **Trust**, **Reword**, **Use the rewrite**, or **Test with real people**;
* the wording habits that cost points;
* round 2 predictions next to what actually happened.

`outputs/report_details.html` has every number, test and rewrite. The main page's footer links to it. To rebuild both pages from the saved results without running the panel again:

```bash
python -c "import json; from stress_tester import report; report.build(json.load(open('outputs/results.json')))"
```

## How it works

```
concepts.csv ─► Claude writes 4 same-meaning wordings ─► Claude checks meaning held
             ─► Flashpoint synthetic panel scores every wording (+ the original asked twice = noise check)
             ─► Wording Stability Score per concept (spread vs. noise, permutation test)
             ─► learner: which wording features move the score?  ─► memory/rules.json
             ─► next batch: memory predicts fragile concepts BEFORE any panel run
             ─► Claude rewrites fragile concepts to avoid the fragile patterns (retries once if any remain;
                a separate strict meaning check rejects rewrites that change the offer), re-tests them
             ─► report: the FlashFeud board (trust / reword / use the rewrite / test with real people)
```

**Self-improving:** rules are learned on batch 1, then tested on a held-out batch 2 that the agent never learned from. Observations accumulate in `memory/`, so each new batch refits on everything seen so far.

Like checking that a weighing scale reads the same every time before you trust the number.

## Run it

```bash
pip install -r requirements.txt
python run.py --open            # simulated panel, works with no keys at all
```

That runs the whole loop on the simulated panel and opens the report. **It overwrites the live results in `outputs/` and `memory/`**, so don't commit those files afterwards (see the heads-up below).

With keys (copy `.env.example` to `.env`, which git ignores):

```bash
python scripts/flashpoint_login.py    # sign in to Flashpoint in the browser; saves FLASHPOINT_TOKEN to .env
python scripts/flashpoint_probe.py    # list Flashpoint MCP tools + argument schemas
python scripts/flashpoint_trial.py    # one free 10-persona rating question; saves outputs/flashpoint_trial.json
python run.py --panel flashpoint --personas 30 --skip-rewrites   # the live run, as committed
python scripts/flashpoint_refetch.py  # re-read finished Flashpoint runs if some answers came back short
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

Every Claude answer is cached in `outputs/cache/` and every panel result in `outputs/runs/<adapter>/`, so nothing is paid for twice. The Claude cache and the live panel answers (`outputs/runs/flashpoint/`, raw replies in `outputs/flashpoint_raw/`) are committed. Re-running the live command with the same keys reads the cache instead of buying new panel runs. Without an Anthropic key, Claude is off, the offline wordings differ, and the cache doesn't match.

Output: `outputs/report.html` (the FlashFeud page), `outputs/report_details.html` (technical detail), `outputs/results.json`, `memory/rules.json`, `memory/observations.json`.

> **Heads-up:** `outputs/` and `memory/` are tracked in git and every run overwrites them. Right now they hold the **live Flashpoint results**. Don't commit them after a test run unless you mean to replace those.

### Panel adapters

| Adapter | How it reaches the panel | Status |
|---|---|---|
| `mock` | simulated personas with **planted** wording effects (`stress_tester/panel/mock.py`) | works offline; for building and testing only |
| `flashpoint` | talks MCP (JSON-RPC over HTTP) to `FLASHPOINT_MCP_URL` with `FLASHPOINT_TOKEN`. **Batch mode:** creates one synthetic panel per segment with the `panel` tool, then asks the `tool_survey` agent to build one survey per wording type (one question per concept, about 6 surveys in all), starts every run, polls until done, and reads per-question answers. Both batches are scored in one round; batch-2 answers are still read only after the prediction is made. Panel and survey ids are kept in `outputs/flashpoint_state.json`. | **used for the live run** (16 concepts, 30 personas, 87 panel runs). If the surveys agent cuts an export short, `scripts/flashpoint_refetch.py` re-reads per-question counts (about $0.50 per survey that needs it) |
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
* 8 + 8 banking ads is a proof of method, not a benchmark. Counts and intervals are always shown.
* **Memory did not beat no-memory on unseen ads** on the live panel (0 of 4 flagged). It learned one rule, long copy. What makes a score unstable on a real panel isn't explained by obvious wording traits. Don't tune the predictor after seeing batch 2, because that would break the held-out test.
* Rewrites weren't re-tested on the live panel, and no shaky held-out ad was rewritten.
* The rewriter's retry and independent meaning check have been tested with a fake Claude, but they haven't run against live Claude yet.
* The Market Experiment cost in the report ($4,500) is a 2025 podcast figure and may be out of date.
* Every number is labeled by source. The mock panel (`stress_tester/panel/mock.py`) has **planted** wording effects so the pipeline can be tested offline; mock results say nothing about real panels.

**Next:** test a larger, more varied set of ads; find what does predict instability on real panels; confirm flagged ads with real-world testing; add an interactive interface (today the output is a static report page).

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
  report.py                writes report.html (FlashFeud page) + report_details.html
  feud.py                  the FlashFeud page
scripts/
  flashpoint_login.py      Flashpoint sign-in (MCP OAuth 2.1 + PKCE), writes FLASHPOINT_TOKEN to .env
  flashpoint_probe.py      prints the Flashpoint MCP server's tools and argument schemas
  flashpoint_trial.py      one small free synthetic-panel trial to learn the reply format
  flashpoint_refetch.py    re-reads finished Flashpoint runs and saves every persona's answer
tests/                     pytest suite (runs in a temp dir)
memory/                    rules.json + observations.json (what the agent has learned)
outputs/                   report.html, report_details.html, results.json, cache/ (Claude), runs/ (panel results),
                           flashpoint_raw/ + flashpoint_state.json (live run replies and ids)
requirements.txt           runtime deps (anthropic, httpx, python-dotenv, numpy)
requirements-dev.txt       + pytest
```

Built by our team with Claude (see contributors).
