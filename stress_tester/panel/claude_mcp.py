"""Flashpoint panel driven by Claude through the API's MCP connector.

Claude connects to Flashpoint's MCP server, runs the synthetic panel tool, and
hands back the per-persona scores. Useful when the panel tool's arguments are
awkward to template by hand: Claude reads the tool schema itself.
"""
from __future__ import annotations

import json
import os
import re

from .. import config, llm
from .flashpoint import extract_scores
from . import PanelResult, summarize


def score(text: str, segment: str, n: int, run_label: str) -> PanelResult:
    if not llm.available():
        raise RuntimeError("--panel claude-mcp needs ANTHROPIC_API_KEY")
    client = llm._get_client()
    server = {
        "type": "url",
        "url": os.getenv("FLASHPOINT_MCP_URL", "https://api.flashpoint.ai/mcp"),
        "name": "flashpoint",
    }
    if tok := os.getenv("FLASHPOINT_TOKEN"):
        server["authorization_token"] = tok
    prompt = (
        f"Use the Flashpoint synthetic panel tool to ask {n} synthetic personas from this audience: "
        f"{segment}.\n\nShow them this exact text, word for word:\n\"{text}\"\n\n"
        f"Ask them exactly this question:\n{config.QUESTION}\n\n"
        "Use the free synthetic panel only. Do not buy real respondents or make any payment. "
        "When the panel returns, reply with only JSON: "
        '{"responses": [one integer 1-10 per persona], "mean": number, "notes": "anything odd"}'
    )
    resp = client.beta.messages.create(
        model=config.MODEL,
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
        mcp_servers=[server],
        tools=[{"type": "mcp_toolset", "mcp_server_name": "flashpoint"}],
        betas=["mcp-client-2025-11-20"],
        output_config={"effort": "low"},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined the panel request")
    out = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", out, re.S)
    payload = json.loads(m.group(0)) if m else {}
    responses, mean = extract_scores(payload)
    if responses:
        return summarize(text, run_label, responses, adapter="claude-mcp", source="Flashpoint synthetic panel via Claude")
    if mean is not None:
        return PanelResult(text=text, run_label=run_label, mean=mean, n=n, adapter="claude-mcp",
                           source="Flashpoint synthetic panel via Claude (mean only)")
    raise RuntimeError(f"No scores in Claude's reply: {out[:400]}")
