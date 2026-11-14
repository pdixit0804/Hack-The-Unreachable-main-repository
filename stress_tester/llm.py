"""Thin wrapper around the Claude API with a JSON cache.

Every Claude answer is cached under outputs/cache/claude/ keyed by the exact
request, so re-running the pipeline never pays twice and the demo can replay
offline.
"""
from __future__ import annotations

import hashlib
import json
import os

from . import config

_client = None
_mode = "auto"  # "auto" | "on" | "off"


def set_mode(mode: str) -> None:
    global _mode
    _mode = mode


def available() -> bool:
    if _mode == "off":
        return False
    has_key = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    if _mode == "on" and not has_key:
        raise RuntimeError("--claude on but no ANTHROPIC_API_KEY is set (put it in .env)")
    return has_key


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def _cache_path(payload: dict):
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
    d = config.CACHE_DIR / "claude"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def ask_json(system: str, prompt: str, schema: dict, max_tokens: int = 8000, effort: str = "low") -> dict:
    """Ask Claude for JSON matching `schema` (structured outputs)."""
    payload = {"model": config.MODEL, "system": system, "prompt": prompt, "schema": schema}
    path = _cache_path(payload)
    if path.exists():
        return json.loads(path.read_text())

    import anthropic

    client = _get_client()
    kwargs = dict(
        model=config.MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    )
    try:
        # Server-side fallback: if a safety classifier declines, retry on a fallback model.
        resp = client.beta.messages.create(
            **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
        )
    except anthropic.BadRequestError:
        resp = client.messages.create(**kwargs)

    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined this request: {getattr(resp, 'stop_details', None)}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Claude hit max_tokens; raise max_tokens in llm.ask_json")
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    data = json.loads(text)
    path.write_text(json.dumps(data, indent=2))
    return data
