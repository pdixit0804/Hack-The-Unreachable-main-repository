"""Builds outputs/report.html from results.json. One static file, no installs."""
from __future__ import annotations

import html
from pathlib import Path

from . import config

e = html.escape

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b70;--card:#fff;--line:#e6e3dc;--accent:#2f5bd3;--bad:#c2410c;--good:#15803d;--warn:#a16207;--chip:#f1efe9}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececef;--muted:#9a9aa2;--card:#1d1d21;--line:#2e2e34;--accent:#7aa2ff;--bad:#fb923c;--good:#4ade80;--warn:#facc15;--chip:#26262b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:1080px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:30px;margin:0 0 4px}h2{font-size:20px;margin:40px 0 12px}h3{font-size:16px;margin:0 0 6px}
.sub{color:var(--muted);margin:0 0 18px}.banner{padding:10px 14px;border-radius:10px;border:1px solid var(--line);background:var(--chip);font-size:14px}
.banner b{color:var(--warn)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.big{font-size:30px;font-weight:700;line-height:1.1}.muted{color:var(--muted)}.small{font-size:13px}
.hook{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:700px){.hook{grid-template-columns:1fr}}
.quote{font-size:17px;margin:8px 0}.score{font-size:40px;font-weight:700}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.wrap{overflow-x:auto}.pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600;background:var(--chip);white-space:nowrap}
.bad{color:var(--bad)}.good{color:var(--good)}.warn{color:var(--warn)}
.bar{position:relative;height:8px;background:var(--chip);border-radius:4px;min-width:90px}.bar i{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:var(--accent)}
.bar b{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--bad)}
details{margin-top:6px}summary{cursor:pointer;color:var(--accent);font-size:13px}
.tag{display:inline-block;font-size:11px;padding:0 6px;border-radius:4px;background:var(--chip);margin:1px}
code{background:var(--chip);padding:1px 5px;border-radius:4px}
"""


def _fmt(x, d=2, sign=False):
    if x is None:
        return "–"
    return f"{x:+.{d}f}" if sign else f"{x:.{d}f}"


def _tags(t: dict) -> str:
    on = [k for k, v in t.items() if v]
    return "".join(f'<span class="tag">{e(k)}</span>' for k in on) or '<span class="tag">none</span>'


def _rec_pill(r: str) -> str:
    cls = {"trust": "good", "use the rewrite": "good", "test in market": "bad"}.get(r, "warn")
    return f'<span class="pill {cls}">{e(r)}</span>'


def _wss_bar(wss):
    if wss is None:
        return "–"
    w = min(wss / 4, 1) * 100
    t = config.UNSTABLE_WSS / 4 * 100
    return f'<div class="bar" title="WSS {wss:.2f}"><i style="width:{w:.0f}%"></i><b style="left:{t:.0f}%"></b></div>'


def _concept_table(rows, batch2=False):
    head = "<tr><th>Concept</th><th>Original</th><th>Spread</th><th>Noise</th><th>Stability (WSS)</th><th>p</th><th>Verdict</th>"
    head += "<th>Predicted</th>" if batch2 else ""
    head += "<th>Recommendation</th></tr>"
    body = []
    for r in rows:
        verdict = '<span class="pill bad">unstable</span>' if r["unstable"] else '<span class="pill good">stable</span>'
        pred = ""
        if batch2:
            pred = (
                f'<td>{"<span class=\'pill bad\'>fragile</span>" if r.get("pred_unstable") else "<span class=\'pill good\'>ok</span>"}'
                f'<div class="small muted">pred. spread {_fmt(r.get("pred_spread"))}</div></td>'
            )
        variants = "".join(
            f"<tr><td><code>{e(k)}</code></td><td>{e(r['variants'].get(k, r['text']))}</td><td>{_fmt(m)}</td>"
            f"<td>{_tags(r['tags'].get(r['variants'].get(k, r['text']), {}))}</td></tr>"
            for k, m in r["means"].items()
        )
        dropped = f"<div class='small warn'>Dropped by meaning check: {', '.join(r['dropped'])}</div>" if r.get("dropped") else ""
        rewrite = ""
        if r.get("rewrite_rejected"):
            rj = r["rewrite_rejected"]
            rewrite = (
                f"<div class='small warn' style='margin-top:6px'><b>Rewrite rejected (offer changed):</b> {e(rj['text'])}<br>"
                f"<span class='muted'>{e((rj.get('meaning_check') or {}).get('reason', ''))}</span></div>"
            )
        if r.get("rewrite"):
            rr = r.get("rewrite_result") or {}
            rewrite = (
                f"<div class='small' style='margin-top:6px'><b>Rewrite:</b> {e(r['rewrite']['text'])}<br>"
                f"<span class='muted'>{e(r['rewrite']['changed'])}</span><br>"
                + (f"<span class='muted'>Fragile patterns left: {e(', '.join(r['rewrite']['fragile_left']) or 'none')}"
                   f" ({r['rewrite'].get('attempts', 1)} attempt(s)). Meaning check: "
                   f"{e((r['rewrite'].get('meaning_check') or {}).get('reason', ''))}</span><br>")
                + f"Spread {_fmt(r['spread'])} → <b>{_fmt(rr.get('spread'))}</b>, WSS {_fmt(r['wss'])} → <b>{_fmt(rr.get('wss'))}</b>"
                f", appeal {_fmt(r['means']['original'])} → {_fmt((rr.get('means') or {}).get('original'))}</div>"
            )
        body.append(
            f"<tr><td><b>{e(r['id'])}</b> {e(r['text'])}<div>{_tags(r['tags'][r['text']])}</div>"
            f"<details><summary>{len(r['means'])} wordings</summary><div class='wrap'><table><tr><th>Kind</th><th>Wording</th><th>Mean</th><th>Features</th></tr>"
            f"{variants}<tr><td><code>repeat</code></td><td class='muted'>original, asked again (noise check)</td><td>{_fmt(r['repeat_mean'])}</td><td></td></tr></table></div>{dropped}</details>"
            f"{rewrite}</td>"
            f"<td>{_fmt(r['means']['original'])}</td><td><b>{_fmt(r['spread'])}</b></td><td>{_fmt(r['noise_range'])}</td>"
            f"<td>{_wss_bar(r['wss'])}<div class='small'>{_fmt(r['wss'])}</div></td><td>{_fmt(r['p'], 3)}</td><td>{verdict}</td>{pred}"
            f"<td>{_rec_pill(r['recommendation'])}</td></tr>"
        )
    return f"<div class='wrap'><table>{head}{''.join(body)}</table></div>"


def _rules_table(rules, planted=None):
    head = "<tr><th>Wording feature</th><th>Effect (pts)</th><th>90% CI</th><th>Seen in</th><th>Status</th><th>What memory says</th>"
    head += "<th>Planted in mock</th>" if planted else ""
    head += "</tr>"
    rows = []
    for r in sorted(rules, key=lambda r: r["effect"]):
        st = {"fragile": "bad", "weak evidence": "warn"}.get(r["status"], "muted")
        rows.append(
            f"<tr><td><b>{e(r['feature'])}</b><div class='small muted'>{e(r['definition'])}</div></td>"
            f"<td><b>{_fmt(r['effect'], 2, True)}</b></td><td>{_fmt(r['ci90'][0], 2, True)} to {_fmt(r['ci90'][1], 2, True)}</td>"
            f"<td>{r['n_variants']} variants / {r['n_concepts']} concepts</td><td><span class='pill {st}'>{e(r['status'])}</span></td>"
            f"<td class='small'>{e(r.get('rule', ''))}<br><span class='muted'>{e(r.get('advice', ''))}</span></td>"
            + (f"<td>{_fmt(planted.get(r['feature']), 1, True)}</td>" if planted else "")
            + "</tr>"
        )
    return f"<div class='wrap'><table>{head}{''.join(rows)}</table></div>"


def build(res: dict) -> Path:
    b1, b2 = res["batch1"]["concepts"], res["batch2"]["concepts"]
    ev, imp = res["evaluation"], res["improvement"]
    fa = res.get("improvement_false_alarms")
    is_mock = res["adapter"] == "mock"
    every = b1 + b2
    hook = max(every, key=lambda r: r["spread"])
    best_t = hook["variants"].get(hook["best"], hook["text"])
    worst_t = hook["variants"].get(hook["worst"], hook["text"])

    banner = (
        "<b>MOCK DATA.</b> These numbers come from a simulated panel with planted wording effects, "
        "used to test the pipeline. They say nothing about real people or Flashpoint's panel."
        if is_mock
        else f"<b>SYNTHETIC DATA.</b> Every score here is from AI personas ({e(', '.join(res['data_source']))}), "
        "not real people. A stable answer is not proof of a correct one."
    )
    a, bf = ev["after"], ev["before"]
    n2 = len(b2)
    cards = f"""
<div class="grid">
 <div class="card"><div class="muted small">Held-out batch 2: fragile concepts caught <i>before</i> any panel run</div>
  <div class="big">{a['tp']} of {ev['n_unstable_actual']}</div>
  <div class="small">{a['fp']} false alarm(s). Accuracy {a['accuracy']:.0%} vs {bf['accuracy']:.0%} with no memory.
  Rank correlation of predicted vs actual spread: {_fmt(ev['spearman_after'])}.</div></div>
 <div class="card"><div class="muted small">Rewrites of unstable held-out concepts: appeal of the chosen wording</div>
  <div class="big">{_fmt(imp['appeal_before']) if imp else '–'} → {_fmt(imp['appeal_after']) if imp else '–'}</div>
  <div class="small">{(str(imp['n']) + ' rewritten; ' + str(imp['n_lift_beyond_noise']) + ' scored higher by more than run-to-run noise. Fragile patterns in the wording: ' + str(imp['fragile_before']) + ' → ' + str(imp['fragile_after']) + '. Wording spread ' + _fmt(imp['spread_before']) + ' → ' + _fmt(imp['spread_after']) + ' (' + str(imp['still_unstable']) + ' still wording-sensitive: the stress test re-adds fragile patterns, so a rewrite fixes the wording, not the idea).') if imp else 'No unstable concepts were rewritten.'}{(' False-alarm rewrites reported separately: ' + str(fa['n']) + '.') if fa else ''}</div></div>
 <div class="card"><div class="muted small">Did the winning concept change with wording?</div>
  <div class="big">{'Yes' if res['batch1']['flips']['winner_changes'] or res['batch2']['flips']['winner_changes'] else 'No'}</div>
  <div class="small">Batch 1 winners by wording set: {e(', '.join(sorted(set(res['batch1']['flips']['winners'].values()))))}. Batch 2: {e(', '.join(sorted(set(res['batch2']['flips']['winners'].values()))))}.</div></div>
 <div class="card"><div class="muted small">Panel runs used</div>
  <div class="big">{res['panel_runs']}</div><div class="small">{res['personas']} personas each, {n2 + len(b1)} concepts + rewrites. Mean prediction error on spread: {_fmt(ev['mae_after'])} pts (vs {_fmt(ev['mae_before'])} with no memory).</div></div>
</div>"""

    market = [r for r in every if "test in market" in r["recommendation"]]
    html_out = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wording Stress-Tester</title><style>{CSS}</style></head><body><main>
<h1>Wording Stress-Tester</h1>
<p class="sub">Before you trust a synthetic answer, stress-test it. Generated {e(res['generated'])} · panel: <code>{e(res['adapter'])}</code> · Claude: {'<code>' + e(res['model']) + '</code>' if res['claude_used'] else 'off (offline rules)'}</p>
<div class="banner">{banner}</div>

<h2>Same offer, two wordings</h2>
<div class="hook">
 <div class="card"><div class="muted small">{e(hook['id'])} · wording <code>{e(hook['best'])}</code></div><div class="quote">“{e(best_t)}”</div><div class="score good">{_fmt(hook['means'][hook['best']], 1)}</div></div>
 <div class="card"><div class="muted small">{e(hook['id'])} · wording <code>{e(hook['worst'])}</code></div><div class="quote">“{e(worst_t)}”</div><div class="score bad">{_fmt(hook['means'][hook['worst']], 1)}</div></div>
</div>
<p class="small muted">Asking the identical wording twice moved this concept by {_fmt(abs(hook['means']['original'] - (hook['repeat_mean'] or hook['means']['original'])))} points; noise alone would explain a spread of about {_fmt(hook['noise_range'])} across {len(hook['means'])} wordings. Observed spread: <b>{_fmt(hook['spread'])}</b> (WSS {_fmt(hook['wss'])}).</p>

<h2>Did it get better? (held-out batch 2)</h2>
{cards}

<h2>What it learned (memory after batch 1)</h2>
<p class="small muted">Least-squares fit of each variant's score shift on the wording features it added or removed; 90% bootstrap intervals over concepts. Used to predict batch 2 before running it.</p>
{_rules_table(res['rules_after_batch1'], res.get('planted'))}

<h2>Batch 1 · learn</h2>
{_concept_table(b1)}

<h2>Batch 2 · held-out test</h2>
{_concept_table(b2, batch2=True)}

<h2>Route to real people</h2>
<p>{len(market)} concept(s) stay unstable even after rewriting, so no synthetic answer about them should be trusted: {e(', '.join(r['id'] for r in market)) or 'none'}.
Recommended next step: a real-world Market Experiment for each (about ${res['market_experiment_cost']:,} each, 2025 figure, may be out of date).</p>

<h2>How the numbers work</h2>
<div class="card small">
<p><b>Wording spread</b>: highest minus lowest mean score across the original and its same-meaning variants (1–10 scale).
<b>Noise</b>: the spread pure run-to-run randomness would produce for that many wordings: the standard error of one run's mean (from per-persona answers, or pooled original-vs-repeat gaps) × the expected range of k normal draws (2.33 for k=5).
<b>WSS</b> = spread ÷ noise. A concept is <b>unstable</b> when WSS ≥ {config.UNSTABLE_WSS}, the spread is at least {config.MIN_SPREAD} point (big enough to change a decision), and a permutation test (answers shuffled across wordings, 2,000 times) gives p &lt; {config.UNSTABLE_P}.</p>
<p><b>Prediction</b>: for batch 2, Claude writes the variants and tags their features, and the rules from batch 1 predict each concept's spread before any panel run. "No memory" predicts no wording effects, so it flags nothing.</p>
<p><b>Limits</b>: {len(b1)}+{n2} concepts is a proof of method, not a benchmark. Stable is not the same as correct: this tool says when a synthetic answer depends on wording, not whether real people agree. Question asked: <i>{e(res['question'])}</i></p>
</div>
</main></body></html>"""
    path = config.OUT_DIR / "report.html"
    path.parent.mkdir(exist_ok=True)
    path.write_text(html_out, encoding="utf-8")
    return path
