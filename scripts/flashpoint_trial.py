"""One small end-to-end trial of Flashpoint's synthetic panel, to learn the response format.

    python3 scripts/flashpoint_trial.py

1. Prints the full descriptions of the `panel` and `tool_survey` tools.
2. Creates a small synthetic panel (free, AI personas only).
3. Asks the surveys agent to run ONE rating question on that panel and return
   every persona's answer.
Everything is saved to outputs/flashpoint_trial.json. Paste the Terminal output
to Claude. Nothing here buys real respondents: payment needs a separate
`payment_confirmation` call, which this script never makes.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stress_tester import config  # noqa: E402
from stress_tester.panel.flashpoint import MCPClient, result_payload  # noqa: E402

N = 10
WORDING = "Earn 4.25% APY on your savings with no monthly fees and no minimum balance."
log = {}


def show(title, obj):
    text = obj if isinstance(obj, str) else json.dumps(obj, indent=2)
    print(f"\n===== {title} =====\n{text[:4000]}")


client = MCPClient()
client.initialize()
tools = {t["name"]: t for t in client.list_tools()}
for name in ("panel", "tool_survey"):
    show(f"{name} description", tools.get(name, {}).get("description", "(missing)"))
log["descriptions"] = {k: tools[k].get("description") for k in ("panel", "tool_survey") if k in tools}

t0 = time.time()
res = client.call_tool(
    "panel",
    {
        "action": "create",
        "name": "Stress-Tester trial panel",
        "num_respondents": N,
        "research_objective": "Rate how appealing short banking offers are, on a 1-10 scale.",
        "audience": {"description": "US adults 25-44 with a checking account", "country": "US"},
    },
)
panel_out = result_payload(res)
log["panel_create"] = {"seconds": round(time.time() - t0, 1), "isError": res.get("isError"), "result": panel_out}
show(f"panel create ({log['panel_create']['seconds']}s)", panel_out)

panel_id = None
if isinstance(panel_out, dict):
    panel_id = panel_out.get("panel_id") or panel_out.get("id") or (panel_out.get("panel") or {}).get("id")

brief = (
    "Using ONLY the free synthetic panel"
    + (f" with panel_id {panel_id}" if panel_id else " 'Stress-Tester trial panel' I just created")
    + f" (AI personas, no paid recruitment, no payment), run a one-question survey.\n"
    f"Show each respondent this exact text: \"{WORDING}\"\n"
    f"Question (single choice, 1-10): {config.QUESTION}\n"
    "Field it to the synthetic panel now, then return every respondent's numeric answer as JSON: "
    '{"responses": [..], "mean": .., "n": ..}, plus the survey_id.'
)
t0 = time.time()
res = client.call_tool("tool_survey", {"brief": brief})
survey_out = result_payload(res)
log["tool_survey"] = {"seconds": round(time.time() - t0, 1), "isError": res.get("isError"), "brief": brief, "result": survey_out}
show(f"tool_survey ({log['tool_survey']['seconds']}s)", survey_out)

out = ROOT / "outputs" / "flashpoint_trial.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(log, indent=2, default=str))
print(f"\nSaved to {out}")
