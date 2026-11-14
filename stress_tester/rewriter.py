"""Rewrites fragile concepts so they avoid the wording patterns memory flags."""
from __future__ import annotations

import json
import re

from . import features, llm
from .variants import _LOSS_TO_GAIN, _PLAIN, _POSITIVE, _apply

_SCHEMA = {
    "type": "object",
    "properties": {"rewrite": {"type": "string"}, "changed": {"type": "string"}, "same_meaning": {"type": "boolean"}},
    "required": ["rewrite", "changed", "same_meaning"],
    "additionalProperties": False,
}

_URGENCY = [(r"^Act now:\s*", ""), (r"\s*Limited time only\.?", ""), (r"\btoday\b\s*", "")]


def fragile_left(text: str, fragile_ids: list[str]) -> list[str]:
    """Fragile patterns still present in `text`, using the same tagger as the pipeline."""
    tags = features.tag_many([text])[0]
    return [f for f in fragile_ids if tags.get(f)]


_CHECK_SCHEMA = {
    "type": "object",
    "properties": {"same_meaning": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["same_meaning", "reason"],
    "additionalProperties": False,
}


def check_meaning(original: str, new: str) -> dict:
    """Independent meaning check (a separate call from the one that wrote the rewrite)."""
    if not llm.available():
        return {"same_meaning": True, "reason": "offline rules (not checked by Claude)"}
    return llm.ask_json(
        system="You are a strict copy editor checking that a rewrite did not change the offer.",
        prompt=(
            f"Original:\n{original}\n\nRewrite:\n{new}\n\n"
            "Is the offer the same (same facts, numbers, conditions, and promise)? "
            "Changes in tone, order, framing or word choice are allowed. Added or dropped facts are not."
        ),
        schema=_CHECK_SCHEMA,
    )


def rewrite(text: str, rules: list[dict], max_tries: int = 2) -> dict:
    """Rewrite `text` to avoid the fragile patterns in memory.

    Live: Claude rewrites; we tag the result and, if fragile patterns are still in it,
    ask once more with that feedback (no panel runs spent). The candidate with the fewest
    fragile patterns left is kept, then a separate call checks the meaning held.
    """
    fragile = [r for r in rules if r["status"] == "fragile"]
    fragile_ids = [r["feature"] for r in fragile]
    if llm.available():
        base_prompt = (
            f"Concept:\n{text}\n\nWording patterns our memory says make synthetic answers swing:\n"
            + json.dumps([{k: r[k] for k in ("feature", "definition", "effect")} for r in fragile], indent=2)
            + "\n\nRewrite the concept to avoid these patterns where you can without changing the offer. "
            "If a number is essential to the offer, keep it. Say what you changed, and whether the meaning is the same."
        )
        best, feedback = None, ""
        for attempt in range(1, max_tries + 1):
            out = llm.ask_json(
                system=(
                    "You are a copywriter fixing marketing copy whose synthetic-panel score is unstable. "
                    "Keep the offer identical: same facts, numbers, conditions. Change only wording."
                ),
                prompt=base_prompt + feedback,
                schema=_SCHEMA,
            )
            new = out["rewrite"].strip()
            cand = {"text": new, "changed": out["changed"], "self_check": out["same_meaning"], "source": "claude",
                    "fragile_left": fragile_left(new, fragile_ids), "attempts": attempt}
            if best is None or len(cand["fragile_left"]) < len(best["fragile_left"]):
                best = cand
            if not best["fragile_left"]:
                break
            feedback = (
                f"\n\nA previous rewrite still had these patterns: {', '.join(cand['fragile_left'])}.\n"
                f"Previous rewrite: {new}\nTry again and remove them if you can without changing the offer."
            )
        best["attempts"] = attempt
        chk = check_meaning(text, best["text"])
        best["meaning_check"] = chk
        best["same_meaning"] = bool(best.pop("self_check") and chk["same_meaning"])
        best["no_change"] = best["text"] == text.strip()
        return best
    new = _apply(_LOSS_TO_GAIN, _apply(_POSITIVE, _apply(_PLAIN, text)))
    new = _apply(_URGENCY, new).strip()
    new = new[:1].upper() + new[1:]
    offline_check = {"same_meaning": True, "reason": "offline rules (not checked by Claude)"}
    if new == text:
        return {"text": text, "changed": "", "same_meaning": True, "source": "rules", "no_change": True,
                "fragile_left": fragile_left(text, fragile_ids), "attempts": 1, "meaning_check": offline_check}
    return {"text": new, "changed": "offline rules: plain words, positive phrasing, gain framing, no urgency",
            "same_meaning": True, "source": "rules", "no_change": False,
            "fragile_left": fragile_left(new, fragile_ids), "attempts": 1, "meaning_check": offline_check}
