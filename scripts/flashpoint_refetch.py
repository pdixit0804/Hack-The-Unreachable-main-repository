"""Re-read every finished Flashpoint panel run and save ALL persona answers.

Some answers came back with only 10 of the 30 personas (the surveys agent's JSON
export got cut short). This asks for per-question answer counts instead, which
are short enough to come back whole, and rewrites the cached panel results.

Costs: one `panel status` call per survey, plus one surveys-agent call
(about $0.50) for each survey whose status reply doesn't already hold every answer.
Raw replies are saved to outputs/flashpoint_raw/ so nothing needs re-buying.

    python3 scripts/flashpoint_refetch.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tester import config  # noqa: E402
from stress_tester.loader import load_concepts  # noqa: E402
from stress_tester.panel import save, summarize  # noqa: E402
from stress_tester.panel import flashpoint as fp  # noqa: E402
from stress_tester.variants import KINDS  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 30
RAW = config.OUT_DIR / "flashpoint_raw"
RAW.mkdir(parents=True, exist_ok=True)
LABELS = ["original", "repeat", *KINDS]


def counts_to_answers(obj) -> dict[str, list[int]]:
    """Find {code: {"1": count, ..., "10": count}} anywhere in a reply (dict or JSON inside text)."""
    out: dict[str, list[int]] = {}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if re.fullmatch(r"W\d{2}", str(k)) and isinstance(v, dict):
                    ans = []
                    for val, cnt in v.items():
                        m = re.fullmatch(r"\s*(10|[1-9])\s*", str(val))
                        if m and isinstance(cnt, (int, float)):
                            ans += [int(m.group(1))] * int(cnt)
                    if ans:
                        out[k] = ans
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            for m in re.finditer(r"\{.*\}", o, re.S):
                try:
                    walk(json.loads(m.group(0)))
                except json.JSONDecodeError:
                    pass

    walk(obj)
    return out


def main():
    st = fp._state()
    segment = load_concepts()[0].segment
    label_of = {}
    for skey, sid in st["surveys"].items():
        texts = list(st["survey_codes"][sid].values())
        label_of[sid] = next((lab for lab in LABELS if fp.hashlib_key(lab, texts) == skey), None)
    fixed = 0
    for sid, jid in st["jobs"].items():
        label, codes = label_of.get(sid), st["survey_codes"][sid]
        if not label:
            print(f"skip {sid}: unknown wording type")
            continue
        status = fp._call("panel", {"action": "status", "job_id": jid}, print)
        (RAW / f"{sid}_status.json").write_text(json.dumps(status, indent=2, default=str))
        got = fp._per_question(status, list(codes))
        if min((len(got.get(c, [])) for c in codes), default=0) < N:
            brief = (
                "For this survey's completed synthetic-panel responses, give the answer counts for every question. "
                "Reply with ONLY a JSON object, no prose: one key per question code "
                f"({', '.join(codes)}), each value an object mapping each answer 1..10 to how many respondents chose it."
            )
            out, _ = fp._survey_agent(brief, print, survey_id=sid)
            (RAW / f"{sid}_counts.json").write_text(json.dumps(out, indent=2, default=str))
            got = counts_to_answers(out) or got
        n_min = min((len(got.get(c, [])) for c in codes), default=0)
        print(f"{label:10s} {sid[:8]}: {len(got)}/{len(codes)} questions, answers per question {n_min}"
              f"..{max((len(v) for v in got.values()), default=0)}")
        for code, text in codes.items():
            if code in got and len(got[code]) >= 2:
                save("flashpoint", segment, N, summarize(text, label, got[code], adapter="flashpoint",
                                                         source="Flashpoint synthetic panel"))
                fixed += 1
    print(f"\nSaved {fixed} panel results. Now run:\n  python3 run.py --panel flashpoint --personas {N} --skip-rewrites --open")


if __name__ == "__main__":
    main()
