"""Real Flashpoint synthetic panel over MCP (Streamable HTTP, plain JSON-RPC).

We speak the MCP wire protocol directly with httpx instead of depending on a
specific MCP SDK version. Configure with .env:

    FLASHPOINT_MCP_URL     default https://api.flashpoint.ai/mcp
    FLASHPOINT_TOKEN       bearer token, if the server needs one
    FLASHPOINT_PANEL_TOOL  tool name (default "panel")
    FLASHPOINT_PANEL_ARGS  JSON template; {text} {question} {n} {segment} are filled in

Run `python scripts/flashpoint_probe.py` first to print the real tool names and
argument schemas, then set FLASHPOINT_PANEL_TOOL / FLASHPOINT_PANEL_ARGS to match.
"""
from __future__ import annotations

import itertools
import json
import os
import re
from typing import Any

import httpx

from .. import config
from . import PanelResult, summarize

PROTOCOL = "2025-06-18"


class MCPClient:
    def __init__(self, url: str | None = None, token: str | None = None, timeout: float = 600):
        self.url = url or os.getenv("FLASHPOINT_MCP_URL", "https://api.flashpoint.ai/mcp")
        token = token if token is not None else os.getenv("FLASHPOINT_TOKEN", "")
        self.headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(timeout=timeout)
        self.session_id: str | None = None
        self._ids = itertools.count(1)
        self._initialized = False

    def _post(self, payload: dict) -> Any:
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
            headers["MCP-Protocol-Version"] = PROTOCOL
        r = self.http.post(self.url, json=payload, headers=headers)
        if r.status_code in (401, 403):
            raise RuntimeError(
                f"Flashpoint MCP returned {r.status_code}. Set FLASHPOINT_TOKEN in .env, "
                f"or use --panel claude-mcp / --panel import. Body: {r.text[:300]}"
            )
        r.raise_for_status()
        if sid := r.headers.get("mcp-session-id"):
            self.session_id = sid
        if "id" not in payload:  # notification
            return None
        ctype = r.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            msg = None
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    try:
                        m = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if m.get("id") == payload["id"]:
                        msg = m
            if msg is None:
                raise RuntimeError(f"no response for request {payload['id']} in event stream")
        else:
            msg = r.json()
        if "error" in msg:
            raise RuntimeError(f"MCP error: {msg['error']}")
        return msg.get("result")

    def request(self, method: str, params: dict | None = None) -> Any:
        if not self._initialized and method != "initialize":
            self.initialize()
        return self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}})

    def initialize(self):
        res = self._post(
            {
                "jsonrpc": "2.0",
                "id": next(self._ids),
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {},
                    "clientInfo": {"name": "wording-stress-tester", "version": "0.1"},
                },
            }
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True
        return res

    def list_tools(self) -> list[dict]:
        return self.request("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments})


_client: MCPClient | None = None


def _fill(template: Any, values: dict) -> Any:
    if isinstance(template, dict):
        return {k: _fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, values) for v in template]
    if isinstance(template, str):
        m = re.fullmatch(r"\{(\w+)\}", template)
        if m and m.group(1) in values:
            return values[m.group(1)]  # keep native type (e.g. int for {n})
        return template.format(**values) if "{" in template else template
    return template


def result_payload(result: dict) -> Any:
    """Pull the JSON out of an MCP tool result (structuredContent or text blocks)."""
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}|\[.*\]", joined, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return joined


_SCORE_KEYS = ("score", "rating", "answer", "response", "value", "appeal")


def extract_scores(obj: Any) -> tuple[list[int] | None, float | None]:
    """Find per-persona 1-10 answers (preferred) or a mean in an arbitrary payload."""
    found: list[float] = []
    mean: float | None = None

    def as_score(v):
        if isinstance(v, (int, float)) and 1 <= v <= 10:
            return float(v)
        if isinstance(v, str):
            m = re.match(r"\s*(10|[1-9])(?:\.\d+)?\b", v)
            if m:
                return float(m.group(1))
        return None

    def walk(o):
        nonlocal mean
        if isinstance(o, dict):
            for k, v in o.items():
                kl = k.lower()
                if kl in ("mean", "average", "avg", "mean_score") and isinstance(v, (int, float)):
                    mean = float(v)
                elif any(s in kl for s in _SCORE_KEYS) and (s := as_score(v)) is not None:
                    found.append(s)
                else:
                    walk(v)
        elif isinstance(o, list):
            if o and all(isinstance(x, (int, float)) and 1 <= x <= 10 for x in o):
                found.extend(float(x) for x in o)
            else:
                for x in o:
                    walk(x)

    walk(obj)
    return ([int(round(x)) for x in found] or None), mean


def score(text: str, segment: str, n: int, run_label: str) -> PanelResult:
    global _client
    _client = _client or MCPClient()
    tool = os.getenv("FLASHPOINT_PANEL_TOOL", "panel")
    template = json.loads(
        os.getenv(
            "FLASHPOINT_PANEL_ARGS",
            '{"stimulus": "{text}", "question": "{question}", "n_personas": "{n}", "audience": "{segment}"}',
        )
    )
    args = _fill(template, {"text": text, "question": config.QUESTION, "n": n, "segment": segment})
    result = _client.call_tool(tool, args)
    if result.get("isError"):
        raise RuntimeError(f"Flashpoint tool error: {result_payload(result)}")
    payload = result_payload(result)
    responses, mean = extract_scores(payload)
    if responses:
        return summarize(text, run_label, responses, adapter="flashpoint", source="Flashpoint synthetic panel")
    if mean is not None:
        return PanelResult(text=text, run_label=run_label, mean=mean, n=n, adapter="flashpoint",
                           source="Flashpoint synthetic panel (mean only)")
    raise RuntimeError(f"Could not find scores in Flashpoint response: {str(payload)[:500]}")


# ------------------------------------------------------------------ batch mode
# Flashpoint panel runs take minutes, so we bundle every wording that shares a
# run_label (original, repeat, plain, alt, ...) into ONE survey: one question per
# concept. Each persona sees exactly one version of each concept per survey.
import time  # noqa: E402

STATE_PATH = config.OUT_DIR / "flashpoint_state.json"
_ID = r"[A-Za-z0-9_\-]{6,}"


def _state() -> dict:
    return json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}


def _save_state(st: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, indent=2))


def _find(obj: Any, keys: tuple[str, ...]) -> str | None:
    """Find an id like survey_id / job_id / panel_id in a payload (dict or text)."""
    if isinstance(obj, dict):
        for k in keys:
            if isinstance(obj.get(k), (str, int)):
                return str(obj[k])
        for v in obj.values():
            if (r := _find(v, keys)) is not None:
                return r
        return None
    if isinstance(obj, list):
        for v in obj:
            if (r := _find(v, keys)) is not None:
                return r
        return None
    if isinstance(obj, str):
        for k in keys:
            m = re.search(k.replace("_", r"[_ ]?") + r"[\"'`*\s:=]+(" + _ID + ")", obj, re.I)
            if m:
                return m.group(1)
    return None


def _call(tool: str, args: dict, log) -> Any:
    global _client
    _client = _client or MCPClient()
    res = _client.call_tool(tool, args)
    payload = result_payload(res)
    if res.get("isError"):
        raise RuntimeError(f"Flashpoint {tool} error: {str(payload)[:800]}")
    return payload


def _survey_agent(brief: str, log, survey_id: str | None = None, conv: str | None = None) -> tuple[Any, str | None]:
    args: dict = {"brief": brief}
    if survey_id:
        args["survey_id"] = survey_id
    if conv:
        args["conversation_id"] = conv
    out = _call("tool_survey", args, log)
    return out, _find(out, ("conversation_id",)) or conv


def ensure_panel(segment: str, n: int, log) -> str:
    st = _state()
    key = f"{segment}|{n}"
    if key in st.get("panels", {}):
        return st["panels"][key]
    log(f"  flashpoint: creating synthetic panel ({n} personas: {segment})")
    out = _call(
        "panel",
        {
            "action": "create",
            "name": f"Stress-Tester panel {n}",
            "num_respondents": n,
            # Keep the objective neutral: in the trial, an objective that mentioned a rating made the
            # generator bake an "appeal rating" attribute into every persona.
            "research_objective": "Understand how people react to short consumer-banking marketing messages.",
            "context": f"Audience: {segment}.",
        },
        log,
    )
    pid = _find(out, ("panel_id", "id"))
    if not pid:
        raise RuntimeError(f"No panel_id in Flashpoint reply: {str(out)[:600]}")
    st.setdefault("panels", {})[key] = pid
    _save_state(st)
    return pid


def build_survey(label: str, texts: list[str], log) -> str:
    st = _state()
    skey = hashlib_key(label, texts)
    if skey in st.get("surveys", {}):
        return st["surveys"][skey]
    codes = [f"W{i + 1:02d}" for i in range(len(texts))]
    listing = "\n".join(f'{c}: "{t}"' for c, t in zip(codes, texts))
    brief = (
        f"Build a new survey named 'Stress-Tester {label} {skey[:6]}' for a synthetic panel. Do not ask me "
        "clarifying questions, do not propose a blueprint, just build it.\n"
        f"It has exactly {len(texts)} questions, one per stimulus below, in this order, with these question codes. "
        f"Each question shows the stimulus text exactly as written (verbatim, in quotes) and then asks: "
        f"'{config.QUESTION}' as a single-choice question with answer options 1,2,3,4,5,6,7,8,9,10.\n"
        "No screeners, no demographics, no other questions, no randomisation. Then publish it.\n"
        f"{listing}\n\nReply with the survey_id."
    )
    log(f"  flashpoint: building survey '{label}' ({len(texts)} questions)")
    out, conv = _survey_agent(brief, log)
    sid = _find(out, ("survey_id",))
    for _ in range(2):
        if sid:
            break
        out, conv = _survey_agent("Yes, confirm. Build and publish it now, then reply with the survey_id.", log, conv=conv)
        sid = _find(out, ("survey_id",))
    if not sid:
        raise RuntimeError(f"Surveys agent didn't return a survey_id: {str(out)[:800]}")
    st.setdefault("surveys", {})[skey] = sid
    st.setdefault("survey_codes", {})[sid] = dict(zip(codes, texts))
    _save_state(st)
    return sid


def hashlib_key(label: str, texts: list[str]) -> str:
    import hashlib

    return hashlib.sha256(json.dumps([label, texts, config.QUESTION]).encode()).hexdigest()[:16]


def start_run(panel_id: str, survey_id: str, log) -> str:
    st = _state()
    if survey_id in st.get("jobs", {}):
        return st["jobs"][survey_id]
    out = _call("panel", {"action": "run", "panel_id": panel_id, "survey_id": survey_id}, log)
    jid = _find(out, ("job_id",))
    if not jid:
        raise RuntimeError(f"No job_id from panel run: {str(out)[:600]}")
    st.setdefault("jobs", {})[survey_id] = jid
    _save_state(st)
    return jid


_DONE = {"completed", "complete", "succeeded", "done"}
_FAILED = {"failed", "interrupted", "error"}


def _all_status(obj: Any, acc: list[str]) -> list[str]:
    if isinstance(obj, dict):
        if isinstance(obj.get("status"), str):
            acc.append(obj["status"].lower())
        for v in obj.values():
            _all_status(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _all_status(v, acc)
    return acc


def job_status(out: Any) -> str:
    """Flashpoint wraps replies in a task envelope whose own status is "completed" even while the
    panel job inside is still running, so only call a job done when every status in the reply is done."""
    found = _all_status(out, [])
    if not found:
        return ""
    if any(s in _FAILED for s in found):
        return next(s for s in found if s in _FAILED)
    if all(s in _DONE for s in found):
        return "completed"
    return next(s for s in found if s not in _DONE)


def wait_jobs(jobs: dict[str, str], log, poll: int = 45, limit_min: int = 45) -> dict[str, Any]:
    done: dict[str, Any] = {}
    t0 = time.time()
    while len(done) < len(jobs):
        for sid, jid in jobs.items():
            if sid in done:
                continue
            out = _call("panel", {"action": "status", "job_id": jid}, log)
            status = job_status(out)
            if status in ("completed", "complete", "succeeded", "done"):
                done[sid] = out
            elif status in ("failed", "interrupted", "error"):
                raise RuntimeError(f"Panel job {jid} {status}: {str(out)[:600]}")
        if len(done) < len(jobs):
            log(f"  flashpoint: {len(done)}/{len(jobs)} panel runs finished ({(time.time() - t0) / 60:.0f} min)")
            if time.time() - t0 > limit_min * 60:
                raise RuntimeError("Flashpoint panel runs timed out; re-run later (finished work is cached).")
            time.sleep(poll)
    return done


def _per_question(obj: Any, codes: list[str]) -> dict[str, list[int]]:
    """Pull {code: [answers]} out of whatever the status result or export looks like."""
    out: dict[str, list[int]] = {}
    if isinstance(obj, dict):
        for c in codes:
            if c in obj:
                resp, _ = extract_scores(obj[c])
                if resp:
                    out[c] = resp
        if len(out) == len(codes):
            return out
        for v in obj.values():
            sub = _per_question(v, codes)
            if len(sub) > len(out):
                out = sub
    elif isinstance(obj, list):
        for v in obj:
            sub = _per_question(v, codes)
            if len(sub) > len(out):
                out = sub
    elif isinstance(obj, str):
        for m in re.finditer(r"\{.*\}", obj, re.S):
            try:
                sub = _per_question(json.loads(m.group(0)), codes)
                if len(sub) > len(out):
                    out = sub
            except json.JSONDecodeError:
                pass
    return out


def fetch_answers(survey_id: str, status_out: Any, log) -> dict[str, list[int]]:
    codes = list(_state()["survey_codes"][survey_id].keys())
    got = _per_question(status_out, codes)
    if len(got) == len(codes):
        return got
    brief = (
        "Export every completed response to this survey. Reply with ONLY a JSON object, no prose: one key per "
        f"question code ({', '.join(codes)}), each value a list of the integer answers (1-10), one per respondent."
    )
    out, _ = _survey_agent(brief, log, survey_id=survey_id)
    got = _per_question(out, codes)
    if not got:
        raise RuntimeError(f"Couldn't read answers for survey {survey_id}: {str(out)[:800]}")
    return got


def score_batch(items: list[tuple[str, str, str]], n: int, log=print):
    """items: (text, segment, run_label). Yields (PanelResult, item)."""
    by_label: dict[tuple[str, str], list[str]] = {}
    for text, segment, label in items:
        by_label.setdefault((segment, label), [])
        if text not in by_label[(segment, label)]:
            by_label[(segment, label)].append(text)
    surveys = {}
    for (segment, label), texts in by_label.items():
        pid = ensure_panel(segment, n, log)
        sid = build_survey(label, texts, log)
        surveys[sid] = (pid, segment, label)
    jobs = {sid: start_run(pid, sid, log) for sid, (pid, _, _) in surveys.items()}
    log(f"  flashpoint: {len(jobs)} panel runs started; polling")
    finished = wait_jobs(jobs, log)
    codes_all = _state()["survey_codes"]
    for sid, status_out in finished.items():
        _, segment, label = surveys[sid]
        answers = fetch_answers(sid, status_out, log)
        for code, text in codes_all[sid].items():
            if code in answers:
                yield summarize(text, label, answers[code], adapter="flashpoint",
                                source="Flashpoint synthetic panel"), (text, segment, label)
            else:
                log(f"  flashpoint: no answers for {code} in survey {sid}")
