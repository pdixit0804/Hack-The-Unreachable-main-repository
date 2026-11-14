"""Writes same-meaning versions of each concept, then checks the meaning held.

Live: Claude writes the variants and a second Claude call checks meaning.
Offline: simple rule-based rewrites so the pipeline runs with no keys.
"""
from __future__ import annotations

import re

from . import llm

KINDS = {
    "plain": "a paraphrase in plain everyday words a non-expert would use (spell out any acronyms or jargon)",
    "alt": "a second, different natural paraphrase, as a copywriter might write it",
    "frame_flip": "the same offer with the framing flipped: if it is framed as a gain, frame it as avoiding a loss; if it is framed as avoiding a loss, frame it as a gain",
    "reordered": "the same claims in a different order (lead with what the original mentions last)",
}

_VARIANT_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in KINDS},
    "required": list(KINDS),
    "additionalProperties": False,
}

_CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "same_meaning": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["kind", "same_meaning", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["checks"],
    "additionalProperties": False,
}


def make_variants(text: str) -> dict:
    """Return {"variants": {kind: text}, "checks": {kind: {...}}, "source": "claude"|"rules"}."""
    if llm.available():
        return _claude_variants(text)
    return {
        "variants": rule_variants(text),
        "checks": {k: {"same_meaning": True, "reason": "offline rules (not checked by Claude)"} for k in KINDS},
        "source": "rules",
    }


def _claude_variants(text: str) -> dict:
    kinds = "\n".join(f"- {k}: {v}" for k, v in KINDS.items())
    out = llm.ask_json(
        system=(
            "You write controlled wording variants of marketing copy for a survey-methods experiment. "
            "Every variant must keep exactly the same offer, facts, numbers, conditions and audience. "
            "Only the wording may change. Keep each variant about the same length as the original."
        ),
        prompt=f"Original:\n{text}\n\nWrite one variant of each kind:\n{kinds}",
        schema=_VARIANT_SCHEMA,
    )
    variants = {k: out[k].strip() for k in KINDS}
    listing = "\n".join(f"[{k}] {v}" for k, v in variants.items())
    chk = llm.ask_json(
        system="You are a strict copy editor checking that rewrites did not change the offer.",
        prompt=(
            f"Original:\n{text}\n\nRewrites:\n{listing}\n\n"
            "For each rewrite, is the offer the same (same facts, numbers, conditions, and promise)? "
            "Changes in tone, order, framing or word choice are allowed. Added or dropped facts are not."
        ),
        schema=_CHECK_SCHEMA,
    )
    checks = {c["kind"]: {"same_meaning": c["same_meaning"], "reason": c["reason"]} for c in chk["checks"]}
    for k in KINDS:
        checks.setdefault(k, {"same_meaning": True, "reason": "not returned by checker"})
    return {"variants": variants, "checks": checks, "source": "claude"}


# ---------------------------------------------------------------- offline rules
_PLAIN = [
    (r"\bvariable APR\b", "interest rate that can change"),
    (r"\bAPR\b", "yearly interest rate"),
    (r"\bAPY\b", "interest per year"),
    (r"\bFDIC-insured\b", "protected by the U.S. government"),
    (r"\bFDIC\b", "U.S. government deposit insurance"),
    (r"\b12-month CD\b", "12-month savings certificate"),
    (r"\bCD\b", "savings certificate"),
    (r"\bcompounded daily\b", "with interest added every day"),
    (r"\bHigh-yield savings\b", "A savings account paying"),
]
_POSITIVE = [
    (r"\bno monthly fees and no minimum balance\b", "$0 monthly fees and a $0 minimum balance"),
    (r"\bno (foreign transaction|annual|monthly|hidden) fees?\b", r"$0 \1 fees"),
    (r"\bzero fees\b", "$0 in fees"),
    (r"\bthere's \$0 annual fees\b", "the annual fee is $0"),
    (r"\bnever charges you\b", "doesn't charge you"),
    (r"\bDon't let inflation eat your savings\b", "Keep your savings ahead of inflation"),
    (r",? ever\.", " for life."),
]
_LOSS_TO_GAIN = [
    (r"^Stop losing money to ([^.]+)\.", r"Keep more of your money: say goodbye to \1."),
    (r"^Don't let inflation eat your savings\.", "Grow your savings faster than inflation."),
    (r"\bbefore rates drop\b", "while rates are high"),
]


def _apply(rules, text: str) -> str:
    for pat, rep in rules:
        text = re.sub(pat, rep, text)
    return text


def _sentence_case(s: str) -> str:
    s = s.strip()
    return s[:1].upper() + s[1:] if s else s


def _lower_first(s: str) -> str:
    return s if s[:2].isupper() else s[:1].lower() + s[1:]


def rule_variants(text: str) -> dict[str, str]:
    plain = _apply(_PLAIN, text)
    if plain == text:
        plain = re.sub(r"^Earn\b", "Get", text)
    alt = _apply(_POSITIVE, text)
    if alt == text:
        swaps = [(r"^Earn\b", "Collect"), (r"^Open\b", "Start"), (r"^See\b", "View"), (r"^Free\b", "Complimentary"),
                 (r"^A\b", "Here's a"), (r"^Put\b", "Set"), (r"^Get (?=\d)", "Enjoy "), (r"^Get paid\b", "Receive your pay")]
        alt = _apply(swaps, text)
    flipped = _apply(_LOSS_TO_GAIN, text)
    if flipped == text:
        flipped = f"Stop missing out: {_lower_first(text)}"
    sentences = [x for x in re.split(r"(?<=[.])\s+", text.strip()) if x]
    if len(sentences) > 1:
        reordered = " ".join(sentences[::-1])
    elif ": " in text:
        head, tail = text.rstrip(".").split(": ", 1)
        reordered = _sentence_case(tail) + f". {head}."
    elif ", so " in text:
        head, tail = text.rstrip(".").split(", so ", 1)
        reordered = f"{_sentence_case(tail)}: {_lower_first(head)}."
    elif " with " in text:
        head, tail = text.rstrip(".").rsplit(" with ", 1)
        reordered = f"With {tail}, {_lower_first(head).rstrip(",")}."
    else:
        parts = text.rstrip(".").split(", ")
        if len(parts) == 2 and len(parts[1].split()) < 3:
            parts = [text]
        reordered = (_sentence_case(", ".join([parts[-1].removeprefix("and ")] + parts[:-1][::-1]).replace(", " + parts[0], ", and " + _lower_first(parts[0]))) + ".") if len(parts) > 1 else text
    return {"plain": plain, "alt": alt, "frame_flip": flipped, "reordered": reordered}
