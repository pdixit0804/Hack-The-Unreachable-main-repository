"""Rewrites fragile concepts so they avoid the wording patterns memory flags."""
from __future__ import annotations

import json
import re

from . import llm
from .variants import _LOSS_TO_GAIN, _PLAIN, _POSITIVE, _apply

_SCHEMA = {
    "type": "object",
    "properties": {"rewrite": {"type": "string"}, "changed": {"type": "string"}, "same_meaning": {"type": "boolean"}},
    "required": ["rewrite", "changed", "same_meaning"],
    "additionalProperties": False,
}

_URGENCY = [(r"^Act now:\s*", ""), (r"\s*Limited time only\.?", ""), (r"\btoday\b\s*", "")]


def rewrite(text: str, rules: list[dict]) -> dict:
    fragile = [r for r in rules if r["status"] == "fragile"]
    if llm.available():
        out = llm.ask_json(
            system=(
                "You are a copywriter fixing marketing copy whose synthetic-panel score is unstable. "
                "Keep the offer identical: same facts, numbers, conditions. Change only wording."
            ),
            prompt=(
                f"Concept:\n{text}\n\nWording patterns our memory says make synthetic answers swing:\n"
                + json.dumps([{k: r[k] for k in ("feature", "definition", "effect")} for r in fragile], indent=2)
                + "\n\nRewrite the concept to avoid these patterns where you can without changing the offer. "
                "If a number is essential to the offer, keep it. Say what you changed, and whether the meaning is the same."
            ),
            schema=_SCHEMA,
        )
        new = out["rewrite"].strip()
        return {"text": new, "changed": out["changed"], "same_meaning": out["same_meaning"], "source": "claude",
                "no_change": new == text.strip()}
    new = _apply(_LOSS_TO_GAIN, _apply(_POSITIVE, _apply(_PLAIN, text)))
    new = _apply(_URGENCY, new).strip()
    new = new[:1].upper() + new[1:]
    if new == text:
        return {"text": text, "changed": "", "same_meaning": True, "source": "rules", "no_change": True}
    return {"text": new, "changed": "offline rules: plain words, positive phrasing, gain framing, no urgency",
            "same_meaning": True, "source": "rules", "no_change": False}
