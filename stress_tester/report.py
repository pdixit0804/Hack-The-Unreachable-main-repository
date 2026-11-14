"""Builds outputs/report.html from results.json. One static file, no installs."""
from __future__ import annotations

import html
from pathlib import Path

from . import config, feud

e = html.escape

CSS = """
/* Same theme as the FlashFeud page: cream floor, warm-black board, gold numbers, coral for bad news. */
:root{--bg:#f2ebdd;--bg2:#e8dfcc;--fg:#1a1714;--muted:#5b5348;--faint:#8a8172;--card:#f8f2e4;--line:#d6cab3;
--board:#1d1a16;--board2:#2b2620;--gold:#e3a20f;--accent:#1a1714;--bad:#c22f47;--good:#2e7d4a;--warn:#8a5a00;--chip:#e8dfcc;
--display:"Bricolage Grotesque",Georgia,serif;--body:"Atkinson Hyperlegible",system-ui,-apple-system,"Segoe UI",sans-serif;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#16130f;--bg2:#231f19;--fg:#f2ebdd;--muted:#b8ad9b;--faint:#8a8172;--card:#1f1b16;--line:#3a332a;
--board:#0c0a08;--board2:#211d18;--accent:#f2ebdd;--bad:#ef5a70;--good:#4fb974;--warn:#e3a20f;--chip:#2b2620;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 var(--body)}
main{max-width:1120px;margin:0 auto;padding:36px 20px 72px}
h1,h2,h3,.big,.score{font-family:var(--display);letter-spacing:-.02em}
h1{font-size:40px;font-weight:800;margin:0 0 6px;line-height:1.05}h1 small{font:400 18px var(--body);color:var(--faint);letter-spacing:0;margin-left:8px}
h1 em{font-style:normal;color:var(--bad)}
h2{font-size:26px;font-weight:800;margin:48px 0 12px}h3{font-size:16px;margin:0 0 6px}
.sub{color:var(--muted);margin:0 0 18px}
.banner{padding:4px 0 4px 12px;border-left:4px solid var(--bad);font-size:15px;color:var(--muted)}.banner b{color:var(--fg)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:16px 18px}
.big{font-size:34px;font-weight:800;line-height:1.1;color:var(--fg)}.muted{color:var(--muted)}.small{font-size:13.5px}
.hook{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:700px){.hook{grid-template-columns:1fr}}
.quote{font-size:17px;margin:8px 0}.score{font-size:44px;font-weight:800}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:6px;overflow:hidden;font-size:14.5px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.05em;background:var(--board);color:var(--gold);font-weight:700;white-space:nowrap}
th[title]{cursor:help}
.wrap{overflow-x:auto}.pill{display:inline-block;padding:2px 9px;border-radius:3px;font-size:12px;font-weight:700;background:var(--chip);white-space:nowrap}
.bad{color:var(--bad)}.good{color:var(--good)}.warn{color:var(--warn)}
.bar{position:relative;height:8px;background:var(--bg2);border-radius:2px;min-width:90px;margin-top:6px}.bar i{position:absolute;left:0;top:0;bottom:0;border-radius:2px;background:var(--gold)}
.bar b{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--bad)}
tr.drow>td{padding:0 12px 12px;background:var(--card)}
tr.crow>td{border-bottom:0}
details{margin:0}summary{cursor:pointer;color:var(--fg);font-weight:700;font-size:13.5px;padding:2px 0;display:inline-block;border-bottom:2px solid var(--gold)}
details[open] summary{margin-bottom:10px}
.inner{border:1px solid var(--line);border-radius:6px;font-size:14px;background:var(--bg)}
.inner th{background:var(--board2)}
.inner td{padding:10px 12px}.inner td.wtxt{min-width:280px;max-width:420px}.inner td.why{min-width:240px;color:var(--muted);font-size:13.5px}
.inner .why b{color:var(--fg);font-weight:700}
.tag{display:inline-block;font-size:11.5px;padding:1px 7px;border-radius:3px;background:var(--chip);margin:1px 2px 1px 0}
code{background:var(--chip);padding:1px 6px;border-radius:3px;font-size:13px}
.legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:8px 18px;margin:0 0 12px;padding:14px 16px;
background:var(--card);border:1px solid var(--line);border-radius:6px;font-size:13.5px}
.legend dt{font-weight:700;font-family:var(--display);font-size:14.5px}.legend dd{margin:2px 0 0;color:var(--muted)}
.legend .lh{grid-column:1/-1;font-weight:700;font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--faint)}
.flegend{margin-top:8px;font-size:13px;color:var(--muted)}.flegend b{color:var(--fg)}
"""


# Why each wording is in the dropdown (what it tests).
KIND_WHY = {
    "original": "The ad as written. Every other wording is compared with this one.",
    "plain": "Plain everyday words, with jargon spelled out. Tests whether jargon moves the score.",
    "alt": "A second natural paraphrase, as a copywriter might write it. Tests ordinary rewording.",
    "frame_flip": "Same offer with the framing flipped: a gain becomes avoiding a loss, or the reverse. Tests framing.",
    "reordered": "Same claims in a different order. Tests whether what comes first matters.",
    "repeat": "The original, asked a second time. Shows how much the score moves by chance alone.",
}

COLUMNS = [
    ("Concept", "The ad's id and original text. Open the dropdown below it to see every wording that was scored."),
    ("Original", "Average appeal score (1–10) the panel gave the original wording."),
    ("Spread", "Highest minus lowest average score across the same-meaning wordings. Bigger means the wording mattered more."),
    ("Noise", "How big a spread chance alone would produce for this many wordings, based on asking the same wording twice."),
    ("Stability (WSS)", "Spread ÷ noise. The bar's red line is the 1.5 cutoff: past it, the wording moved the score more than chance would."),
    ("p", "Chance of a spread this big if wording didn't matter (answers shuffled across wordings 2,000 times). Small means real."),
    ("BH p", "The p-value corrected for testing many ads at once (Benjamini-Hochberg). \"holds\" means it's still unstable after the correction."),
    ("Verdict", "Unstable = spread at least 1 point, at least 1.5× noise, and p below 0.05. Otherwise stable."),
    ("Predicted", "Batch 2 only: what memory predicted before any panel run, with its predicted spread."),
    ("Recommendation", "What to do: trust the score, reword it, use the rewrite, or test it in market with real people."),
]


def _legend(batch2: bool) -> str:
    items = "".join(f"<div><dt>{e(n)}</dt><dd>{e(d)}</dd></div>" for n, d in COLUMNS if batch2 or n != "Predicted")
    return f"<dl class='legend'><div class='lh'>How to read this table</div>{items}</dl>"


def _th(name: str) -> str:
    tip = dict(COLUMNS).get(name, "")
    return f'<th title="{e(tip)}">{e(name)}</th>'


def _changes(orig: dict, var: dict) -> str:
    added = [k for k in var if var.get(k) and not orig.get(k)]
    removed = [k for k in orig if orig.get(k) and not var.get(k)]
    parts = []
    if added:
        parts.append("adds " + ", ".join(added))
    if removed:
        parts.append("removes " + ", ".join(removed))
    return ("Compared with the original, it " + " and ".join(parts) + ".") if parts else "Same wording features as the original."


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
    cols = ["Concept", "Original", "Spread", "Noise", "Stability (WSS)", "p", "BH p", "Verdict"]
    cols += ["Predicted"] if batch2 else []
    cols += ["Recommendation"]
    head = "<tr>" + "".join(_th(c) for c in cols) + "</tr>"
    body = []
    for r in rows:
        verdict = '<span class="pill bad">unstable</span>' if r["unstable"] else '<span class="pill good">stable</span>'
        pred = ""
        if batch2:
            pred = (
                f'<td>{"<span class=\'pill bad\'>fragile</span>" if r.get("pred_unstable") else "<span class=\'pill good\'>ok</span>"}'
                f'<div class="small muted">pred. spread {_fmt(r.get("pred_spread"))}</div></td>'
            )
        orig_tags = r["tags"].get(r["text"], {})
        wrows = []
        for k, m in r["means"].items():
            text = r["variants"].get(k, r["text"])
            tags = r["tags"].get(text, {})
            why = f"<b>{e(KIND_WHY.get(k, 'A same-meaning rewording.'))}</b>"
            if k != "original":
                why += f"<br>{e(_changes(orig_tags, tags))}"
            wrows.append(
                f"<tr><td><code>{e(k)}</code></td><td class='wtxt'>{e(text)}</td><td>{_fmt(m)}</td>"
                f"<td>{_tags(tags)}</td><td class='why'>{why}</td></tr>"
            )
        wrows.append(
            f"<tr><td><code>repeat</code></td><td class='wtxt muted'>{e(r['text'])}</td><td>{_fmt(r['repeat_mean'])}</td>"
            f"<td></td><td class='why'><b>{e(KIND_WHY['repeat'])}</b></td></tr>"
        )
        for k in r.get("dropped", []):
            chk = r.get("checks", {}).get(k) or {}
            if chk.get("same_meaning", True):
                why = "<b class='warn'>Dropped before scoring: it came out identical to the original wording.</b>"
            else:
                why = ("<b class='warn'>Dropped before scoring: the meaning check said it changed the offer.</b>"
                       + (f"<br>{e(chk.get('reason', ''))}" if chk.get("reason") else ""))
            wrows.append(
                f"<tr><td><code>{e(k)}</code></td><td class='wtxt muted'><i>not scored</i></td><td>–</td><td></td>"
                f"<td class='why'>{why}</td></tr>"
            )
        used = sorted({f for t in r["tags"].values() for f, v in t.items() if v})
        flegend = ("<div class='flegend'><b>Wording features:</b> "
                   + " · ".join(f"<b>{e(f)}</b> = {e(config.FEATURES.get(f, ''))}" for f in used) + "</div>") if used else ""
        n_shown = len(r["means"]) + 1
        dropdown = (
            f"<details><summary>Show the {n_shown} wordings scored for {e(r['id'])} and why each is here</summary>"
            f"<div class='wrap'><table class='inner'><tr><th>Kind</th><th>Wording</th><th>Mean</th><th>Features</th><th>Why it's here</th></tr>"
            f"{''.join(wrows)}</table></div>{flegend}</details>"
        )
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
            f"<tr class='crow'><td><b>{e(r['id'])}</b> {e(r['text'])}<div>{_tags(orig_tags)}</div>{rewrite}</td>"
            f"<td>{_fmt(r['means']['original'])}</td><td><b>{_fmt(r['spread'])}</b></td><td>{_fmt(r['noise_range'])}</td>"
            f"<td>{_fmt(r['wss'])}{_wss_bar(r['wss'])}</td><td>{_fmt(r['p'], 3)}</td><td>{_fmt(r.get('p_bh'), 3)}{' <span class=\"small muted\">holds</span>' if r.get('survives_fdr') else ''}</td><td>{verdict}</td>{pred}"
            f"<td>{_rec_pill(r['recommendation'])}</td></tr>"
            f"<tr class='drow'><td colspan='{len(cols)}'>{dropdown}</td></tr>"
        )
    return f"{_legend(batch2)}<div class='wrap'><table>{head}{''.join(body)}</table></div>"


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
    from .analyzer import apply_fdr

    if "fdr" not in res:
        apply_fdr(res)
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
<title>FlashFeud: technical report</title><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&display=swap"><style>{CSS}</style></head><body><main>
<h1>Flash<em>Feud</em> <small>technical report</small></h1>
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
<b>WSS</b> = spread ÷ noise. A concept is <b>unstable</b> when WSS ≥ {config.UNSTABLE_WSS}, the spread is at least {config.MIN_SPREAD} point (big enough to change a decision), and a permutation test (answers shuffled across wordings, 2,000 times) gives p &lt; {config.UNSTABLE_P}. <b>Multiple testing</b>: {res['fdr']['n_tested']} concepts were tested at once, so about one could pass p &lt; {config.UNSTABLE_P} by chance. With a Benjamini-Hochberg correction (false discovery rate {res['fdr']['q']}), {res['fdr']['n_survive']} of the {res['fdr']['n_flagged']} unstable concepts still hold: {e(', '.join(res['fdr']['survivors'])) or 'none'}. The "BH p" column shows each concept's adjusted p.</p>
<p><b>Prediction</b>: for batch 2, Claude writes the variants and tags their features, and the rules from batch 1 predict each concept's spread before any panel run. "No memory" predicts no wording effects, so it flags nothing.</p>
<p><b>Limits</b>: {len(b1)}+{n2} concepts is a proof of method, not a benchmark. Stable is not the same as correct: this tool says when a synthetic answer depends on wording, not whether real people agree. Question asked: <i>{e(res['question'])}</i></p>
</div>
</main></body></html>"""
    config.OUT_DIR.mkdir(exist_ok=True)
    # Technical detail page (every number, every rewrite) sits behind the FlashFeud page.
    (config.OUT_DIR / "report_details.html").write_text(html_out, encoding="utf-8")
    path = config.OUT_DIR / "report.html"
    path.write_text(_standalone(feud.render(res)), encoding="utf-8")
    return path


def _standalone(body: str) -> str:
    """Wrap the FlashFeud fragment so it opens as a normal page in any browser."""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>'
            + body + "</body></html>")
