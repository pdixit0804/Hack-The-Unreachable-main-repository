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
