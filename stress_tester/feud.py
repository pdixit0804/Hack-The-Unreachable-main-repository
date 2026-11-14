"""FlashFeud page: the main report as a game-show board. Built from results.json by report.build()."""
from __future__ import annotations

import html
import json

E = lambda x: html.escape(str(x))  # noqa: E731

KIND = {"original": "Original", "plain": "Plain words", "alt": "Reworded",
        "frame_flip": "Flipped framing", "reordered": "Reordered"}
FEAT = {"jargon": "Finance jargon", "negation": "Saying what's not there", "loss_frame": "Loss framing",
        "many_numbers": "Lots of numbers", "long": "Long copy", "urgency": "Time pressure"}
FEAT_EX = {"jargon": "APY, FDIC, compounding", "negation": "“no fees”, “never”, “zero”",
           "loss_frame": "“stop losing”, “don't miss out”", "many_numbers": "three or more numbers",
           "long": "over about 22 words", "urgency": "“act now”, “today”"}


def verdict(c):
    rec = c.get("recommendation", "")
    if rec.startswith("trust"):
        return "trust"
    if rec.startswith("reword"):
        return "reword"
    if "test in market" in rec:
        return "test"
    if rec.startswith("use the rewrite"):
        return "use"
    return "reword"


def render(r: dict) -> str:
    offers = []
    for rnd, key in ((1, "batch1"), (2, "batch2")):
        for c in r[key]["concepts"]:
            texts = {"original": c["text"], **c.get("variants", {})}
            o = {"id": c["id"], "round": rnd, "text": c["text"], "v": verdict(c),
                 "notRetested": "not re-tested" in c.get("recommendation", ""),
                 "appeal": round(c["means"]["original"], 2), "spread": round(c["spread"], 2), "wss": round(c["wss"], 2),
                 "unstable": c["unstable"],
                 "wordings": [{"k": KIND.get(k, k), "t": texts.get(k, ""), "s": round(v, 2)} for k, v in c["means"].items()],
                 "dropped": [KIND.get(d, d) for d in c.get("dropped", [])]}
            if rnd == 2:
                o["pred"] = c.get("pred_unstable")
            if c.get("rewrite"):
                rw = {"t": c["rewrite"]["text"]}
                rr = c.get("rewrite_result")
                if rr:
                    rw.update(spread=round(rr["spread"], 2), appeal=round(rr["means"].get("original", 0), 2))
                o["rewrite"] = rw
            offers.append(o)

    n_shaky = sum(o["unstable"] for o in offers)
    ev, a = r["evaluation"], r["evaluation"]["after"]
    imp = r.get("improvement") or {}
    mock = r.get("adapter") == "mock"
    n2 = sum(o["round"] == 2 for o in offers)
    gen = r["generated"][:16].replace("T", " ")

    rules = sorted(r["rules_after_batch1"], key=lambda x: x["effect"])
    maxeff = max(abs(x["effect"]) for x in rules) or 1
    rule_rows = "".join(f'''<li class="hab">
      <div><div class="hab-n">{E(FEAT.get(x["feature"], x["feature"]))}</div><div class="faint sm">{E(FEAT_EX.get(x["feature"], ""))}</div></div>
      <div class="hbar"><span class="{"on" if x["status"] == "fragile" else "off"}" style="width:{abs(x["effect"]) / maxeff * 100:.0f}%"></span></div>
      <div class="hab-v serif">{x["effect"]:+.2f}</div>
      <div class="sm {"brick" if x["status"] == "fragile" else "faint"}">{E({"fragile": "Saved to memory", "weak evidence": "Weak evidence", "not seen yet": "Not yet tested"}.get(x["status"], x["status"]))}<span class="faint"> · {x["n_variants"]} wordings</span></div>
    </li>''' for x in rules)

    data = json.dumps({"offers": offers}).replace("</", "<\\/")

    r2 = [o for o in offers if o["round"] == 2]
    hits = sum(bool(o.get("pred")) == bool(o["unstable"]) for o in r2)
    caught = sum(bool(o.get("pred")) and o["unstable"] for o in r2)
    n_un2 = sum(bool(o["unstable"]) for o in r2)
    hab = [x for x in rules if x["effect"] < 0 and x["status"] != "not seen yet"]
    hab_tiles = "".join(f'''<div class="hab{' weak' if x["status"] != "fragile" else ''}"><span class="hn">{E(FEAT.get(x["feature"], x["feature"]))}{' <small class="weaktag">weak</small>' if x["status"] != "fragile" else ''}</span><span class="hx">{E(FEAT_EX.get(x["feature"], ""))}</span><b class="hv">{x["effect"]:+.1f}</b></div>''' for x in hab)

    page = f'''<title>FlashFeud</title>
    <meta name="claude:viewport-fit-sides" content="cover">
    <link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&display=swap">
    <style>
    /* Game-show studio: warm cream floor, a warm-black answer board with cream tiles and gold numbers, coral for bad news. No gradients, no glow. */
    :root{{
      --paper:#f2ebdd; --paper-2:#e8dfcc; --ink:#1a1714; --muted:#5b5348; --faint:#8a8172; --line:#d6cab3;
      --board:#1d1a16; --board-2:#2b2620; --tile:#f8f2e4; --tile-ink:#1a1714; --tile-hi:#fff6d8;
      --coral:#d63a52; --gold:#e3a20f; --mint:#2e8a4f;
      --display:"Bricolage Grotesque",Georgia,serif; --body:"Atkinson Hyperlegible",system-ui,sans-serif;
      color-scheme:light;
    }}
    @media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{
      --paper:#16130f; --paper-2:#231f19; --ink:#f2ebdd; --muted:#b8ad9b; --faint:#8a8172; --line:#3a332a;
      --board:#0c0a08; --board-2:#211d18; --coral:#ef5a70; --mint:#4fb974; color-scheme:dark}}}}
    :root[data-theme="dark"]{{
      --paper:#16130f; --paper-2:#231f19; --ink:#f2ebdd; --muted:#b8ad9b; --faint:#8a8172; --line:#3a332a;
      --board:#0c0a08; --board-2:#211d18; --coral:#ef5a70; --mint:#4fb974; color-scheme:dark}}
    *{{box-sizing:border-box;margin:0}}
    body{{background:var(--paper);color:var(--ink);font:17px/1.5 var(--body)}}
    .bg{{min-height:100vh;padding:0 max(20px,env(safe-area-inset-right)) 56px max(20px,env(safe-area-inset-left))}}
    .wrap{{max-width:1040px;margin:0 auto}} .wrap>*{{min-width:0}}
    h1,h2,.num,.brand,.q,.t .rk,.t .s,.stamp,.chip,.hv,.c2 .top{{font-family:var(--display)}}
    .hero{{padding:44px 0 28px}}
    .brand{{display:flex;align-items:center;gap:14px;font-size:clamp(40px,7vw,68px);font-weight:800;line-height:1;letter-spacing:-.03em}}
    .brand svg{{width:clamp(60px,9vw,96px);height:auto;flex:none}}
    .brand em{{font-style:normal;color:var(--coral)}}
    .hero h1{{margin-top:22px;font-size:clamp(26px,3.8vw,42px);font-weight:800;line-height:1.1;letter-spacing:-.02em;max-width:20ch}}
    .hero p{{margin-top:12px;color:var(--muted);font-size:clamp(17px,1.7vw,20px);max-width:48ch}}
    .warn{{margin-top:18px;padding-left:12px;border-left:4px solid var(--coral);font-size:15px;color:var(--muted)}} .warn b{{color:var(--ink)}}
    /* scoreboard: one lit strip, not cards */
    .score{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));background:var(--board);color:#f2ebdd;border-radius:6px;border-bottom:6px solid var(--gold)}}
    .sc{{padding:20px 22px}} .sc+.sc{{border-left:2px dashed #3d362d}}
    .num{{font-size:clamp(40px,5.4vw,60px);font-weight:800;line-height:1;color:var(--gold);font-variant-numeric:tabular-nums;letter-spacing:-.02em}}
    .sc .l{{margin-top:8px;color:#cfc5b3;font-size:15px;line-height:1.35}}
    h2{{font-size:28px;font-weight:800;letter-spacing:-.02em;margin:52px 0 14px}}
    h2 small{{font:400 15px var(--body);color:var(--faint);margin-left:10px;letter-spacing:0}}
    .pick{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}}
    .pick .rl{{width:100%;font-size:13px;font-weight:700;color:var(--faint);margin-top:4px}}
    .chip{{all:unset;cursor:pointer;font-weight:600;font-size:15px;padding:6px 12px;border-radius:4px;background:var(--paper-2);display:inline-flex;align-items:center;gap:7px}}
    .chip i{{width:9px;height:9px;border-radius:2px}}
    .chip[aria-pressed="true"]{{background:var(--ink);color:var(--paper)}}
    .chip:focus-visible,.step:focus-visible{{outline:3px solid var(--gold);outline-offset:2px}}
    .board{{background:var(--board);color:#f2ebdd;border-radius:8px;padding:22px;border-top:6px solid var(--gold)}}
    .bh{{display:flex;gap:16px;align-items:flex-start;justify-content:space-between}}
    .q{{font-weight:600;font-size:clamp(19px,2.3vw,23px);line-height:1.25}}
    .q span{{display:block;font:700 13px var(--body);color:var(--gold);margin-bottom:6px}}
    .nav{{display:flex;gap:6px;flex:none}}
    .step{{all:unset;cursor:pointer;width:38px;height:38px;display:grid;place-items:center;border-radius:4px;background:var(--board-2);color:#f2ebdd;font-weight:700}}
    .tiles{{list-style:none;padding:0;margin-top:18px;display:grid;gap:6px}}
    .t{{display:grid;grid-template-columns:44px minmax(0,1fr) 68px;border-radius:4px;overflow:hidden;background:var(--tile);color:var(--tile-ink);animation:flip .35s ease both}}
    .t .rk{{display:grid;place-items:center;font-weight:800;font-size:20px;background:var(--gold);color:#1a1714}}
    .t .w{{padding:10px 14px}}
    .t .k{{font-weight:700;font-size:13px;color:#7a6f5f}}
    .t .tx{{font-size:15px;margin-top:1px}}
    .t .s{{display:grid;place-items:center;font-weight:800;font-size:24px;background:var(--board-2);color:var(--gold);font-variant-numeric:tabular-nums}}
    .t.orig{{background:var(--tile-hi)}} .t.orig .k{{color:var(--coral)}}
    @keyframes flip{{from{{transform:rotateX(80deg);opacity:0}}to{{transform:none;opacity:1}}}}
    @media (prefers-reduced-motion:reduce){{.t{{animation:none}}}}
    .res{{margin-top:18px;display:flex;flex-wrap:wrap;align-items:center;gap:12px 20px}}
    .stamp{{font-weight:800;font-size:19px;text-transform:uppercase;padding:6px 14px;border:3px solid;border-radius:3px;transform:rotate(-2deg)}}
    .stamp.trust,.stamp.use{{color:#6fd391}} .stamp.reword{{color:var(--gold)}} .stamp.test{{color:#ff7186}}
    .res .why{{color:#cfc5b3;font-size:16px}} .res .why b{{color:#fff}}
    .rw{{margin-top:14px;padding-top:12px;border-top:1px dashed #3d362d;color:#cfc5b3;font-size:15px}} .rw b{{color:#fff}}
    .habs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}
    .hab{{border-top:4px solid var(--coral);background:var(--paper-2);padding:14px 16px;display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:12px}}
    .hn{{font-weight:700}} .hx{{grid-column:1;color:var(--faint);font-size:14px}}
    .hv{{grid-column:2;grid-row:1/3;align-self:center;font-weight:800;font-size:32px;color:var(--coral)}}
    .weaktag{{font-weight:600;font-size:12px;color:var(--faint);text-transform:uppercase;letter-spacing:.04em;margin-left:6px}} .hab.weak{{border-top-color:var(--line)}} .hab.weak .hv{{color:var(--faint)}}
    .r2{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}}
    .c2{{background:var(--paper-2);padding:12px 14px;border-left:4px solid var(--mint)}} .c2.bad{{border-left-color:var(--coral)}}
    .c2 .top{{display:flex;justify-content:space-between;align-items:center;font-weight:800;font-size:18px}}
    .c2 .mk{{font-size:20px}} .ok{{color:var(--mint)}} .no{{color:var(--coral)}}
    .c2 .d{{margin-top:4px;font-size:14px;color:var(--muted)}}
    .lg{{display:flex;flex-wrap:wrap;gap:6px 16px;margin:-6px 0 12px;font-size:14px;color:var(--muted)}} .lg i{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:6px}}
    .foot a{{color:var(--ink)}}
.foot{{margin-top:40px;color:var(--faint);font-size:14px}}
    @media (max-width:760px){{.r2{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}
    @media (max-width:560px){{.score{{grid-template-columns:minmax(0,1fr)}} .sc{{display:flex;align-items:center;gap:14px;padding:14px 18px}} .sc+.sc{{border-left:0;border-top:2px dashed #3d362d}} .sc .l{{margin:0}}
      .t{{grid-template-columns:34px minmax(0,1fr) 54px}} .t .s{{font-size:20px}} .board{{padding:14px}}}}
    </style>
    <div class="bg"><div class="wrap">
    <header class="hero">
      <div class="brand"><svg viewBox="0 0 120 70" aria-hidden="true">
        <path d="M8 4h42a8 8 0 0 1 8 8v24a8 8 0 0 1-8 8H24l-12 10 3-10H8a8 8 0 0 1-8-8V12a8 8 0 0 1 8-8z" fill="#5b4ff0"/>
        <path d="M12 16h28M12 24h32M12 32h24" stroke="#e7e5ff" stroke-width="4" stroke-linecap="round"/>
        <path d="M72 14h40a8 8 0 0 1 8 8v24a8 8 0 0 1-8 8h-6l3 10-12-10H72a8 8 0 0 1-8-8V22a8 8 0 0 1 8-8z" fill="#f0506e"/>
        <path d="M80 28h28M80 36h24M80 44h28" stroke="#ffe3ea" stroke-width="4" stroke-linecap="round"/>
        <path d="M66 0 50 34h12l-8 28 22-36H64l8-26z" fill="#f5b521" stroke="#1a1714" stroke-width="2.5" stroke-linejoin="round"/>
      </svg><span>Flash<em>Feud</em></span></div>
      <h1>Is the panel scoring the idea, or just the words?</h1>
      <p>We ask about each offer five different ways. If the score jumps around, the score is about the wording, not the offer.</p>
      <p class="warn">{"<b>Practice round.</b> Simulated panel, not real customers." if mock else "<b>Live synthetic panel.</b> Still not real customers."}</p>
    </header>

    <section class="score" aria-label="Scoreboard">
      <div class="sc"><div class="num">{n_shaky}/{len(offers)}</div><div class="l">offers changed score when we changed the words</div></div>
      <div class="sc"><div class="num">{caught}/{n_un2}</div><div class="l">of the shaky new offers, we called before testing</div></div>
      <div class="sc"><div class="num">{round(a["accuracy"]*100)}%</div><div class="l">of round 2 calls were right</div></div>
    </section>


    <h2>The board <small>pick an offer</small></h2>
    <p class="lg"><span><i style="background:var(--mint)"></i>Trust (or use the rewrite)</span><span><i style="background:var(--gold)"></i>Reword</span><span><i style="background:var(--coral)"></i>Test with real people</span></p>
    <div class="pick" id="pick"></div>
    <section class="board" id="board" aria-live="polite"></section>

    <h2>Words that cost points <small>average hit, from round 1</small></h2>
    <div class="habs">{hab_tiles}</div>

    <h2>Round 2: did we call it? <small>{hits} of {len(r2)} right</small></h2>
    <div class="r2" id="r2"></div>

    <p class="foot"><a href="report_details.html">Full technical report</a> · {"Practice data. The simulated panel has wording effects built in on purpose." if mock else "Synthetic panel results. A steady score is not proof real customers agree."} "Shaky" means the score moved more than 1 point and more than 1.5× normal noise.{(" " + str(r["fdr"]["n_survive"]) + " of the " + str(r["fdr"]["n_flagged"]) + " shaky ads still hold after correcting for testing " + str(r["fdr"]["n_tested"]) + " ads at once (Benjamini-Hochberg): " + ", ".join(r["fdr"]["survivors"]) + ".") if r.get("fdr") else ""}</p>
    </div></div>
    <script>
    const D = {data};
    const O = D.offers;
    const V = {{trust:["Trust","var(--mint)","The score holds"], reword:["Reword","var(--gold)","The words moved the score"], use:["Use the rewrite","var(--mint)","The rewrite holds steady"], test:["Test with real people","var(--coral)","Still moves after a rewrite"]}};
    const esc = s => String(s).replace(/[&<>"]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
    let cur = 0;
    function pick() {{
      let h = "";
      [1,2].forEach(rd => {{
        h += `<span class="rl">Round ${{rd}}${{rd===2?" · new offers":""}}</span>`;
        O.forEach((o,i) => {{ if (o.round===rd) h += `<button class="chip" data-i="${{i}}" aria-pressed="${{i===cur}}" aria-label="${{o.id}}: ${{V[o.v][0]}}"><i style="background:${{V[o.v][1]}}"></i>${{o.id}}</button>`; }});
      }});
      document.getElementById("pick").innerHTML = h;
    }}
    function board() {{
      const o = O[cur], v = V[o.v];
      const ws = [...o.wordings].sort((a,b) => b.s - a.s);
      const tiles = ws.map((w,j) => `<li class="t${{w.k==="Original"?" orig":""}}" style="animation-delay:${{j*60}}ms"><span class="rk">${{j+1}}</span><div class="w"><div class="k">${{esc(w.k)}}</div><div class="tx">${{esc(w.t)}}</div></div><span class="s">${{w.s.toFixed(1)}}</span></li>`).join("");
      let rw = "";
      if (o.rewrite) rw = `<div class="rw"><b>Suggested rewrite:</b> ${{esc(o.rewrite.t)}}${{o.rewrite.spread!=null?` · swing ${{o.rewrite.spread.toFixed(1)}} pts`:" · not re-tested yet"}}</div>`;
      document.getElementById("board").innerHTML = `
      <div class="bh"><div class="q"><span>${{o.id}} · Round ${{o.round}} · appeal out of 10</span>${{esc(o.text)}}</div>
      <div class="nav"><button class="step" data-d="-1" aria-label="Previous offer">←</button><button class="step" data-d="1" aria-label="Next offer">→</button></div></div>
      <ol class="tiles">${{tiles}}</ol>
      <div class="res"><span class="stamp ${{o.v}}">${{o.v==="test"?"✕ ":o.v==="trust"?"✓ ":""}}${{v[0]}}</span>
      <span class="why"><b>${{o.spread.toFixed(1)}} pt swing</b> · ${{o.wss.toFixed(1)}}× normal noise · ${{v[2]}}</span></div>${{rw}}`;
    }}
    function r2() {{
      document.getElementById("r2").innerHTML = O.filter(o => o.round===2).map(o => {{
        const ok = !!o.pred === !!o.unstable;
        return `<div class="c2${{ok?"":" bad"}}"><div class="top">${{o.id}}<span class="mk ${{ok?"ok":"no"}}" aria-label="${{ok?"Right":"Wrong"}}">${{ok?"✓":"✕"}}</span></div><div class="d">We said ${{o.pred?"shaky":"steady"}}. It was ${{o.unstable?"shaky":"steady"}}.</div></div>`;
      }}).join("");
    }}
    function go(i) {{ cur = (i + O.length) % O.length; pick(); board(); }}
    document.addEventListener("click", e => {{
      const c = e.target.closest(".chip"); if (c) return go(+c.dataset.i);
      const s = e.target.closest(".step"); if (s) go(cur + +s.dataset.d);
    }});
    pick(); board(); r2();
    </script>'''
    return page
