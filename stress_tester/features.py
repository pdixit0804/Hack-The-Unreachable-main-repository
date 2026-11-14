"""Tags wording features on a piece of text.

Claude does the tagging when a key is available (it handles paraphrases the
regexes miss); the regex tagger is the offline fallback and a sanity check.
"""
from __future__ import annotations

import re

from . import config, llm

_JARGON = re.compile(r"\b(APY|APR|FDIC|CDs?|compound(?:ed|ing)?|basis points?|variable|yield|amortiz\w*)\b", re.I)
_NEG = re.compile(r"\b(no|not|never|zero|without|don't|doesn't|won't|can't|ever)\b", re.I)
_LOSS = re.compile(
    r"\b(los(?:e|es|ing|t)|miss(?:ing)? out|stop paying|eat(?:s|ing)?|waste|drain|cost(?:s|ing)? you|before (?:rates|it)|don't let)\b",
    re.I,
)
_URGENT = re.compile(r"\b(today|now|limited|hurry|act now|ends soon|deadline|before rates)\b", re.I)
_NUM = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?x?")


def regex_tags(text: str) -> dict[str, int]:
    words = len(text.split())
    return {
        "jargon": int(bool(_JARGON.search(text))),
        "negation": int(bool(_NEG.search(text))),
        "loss_frame": int(bool(_LOSS.search(text))),
        "many_numbers": int(len(_NUM.findall(text)) >= 3),
        "long": int(words > 22),
        "urgency": int(bool(_URGENT.search(text))),
    }


_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    **{k: {"type": "boolean"} for k in config.FEATURES},
                },
                "required": ["index", *config.FEATURES.keys()],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


# In mock mode the simulated panel reacts to the regex-detected features, so the
# learner must see the same features to be a fair test of the method.
USE_REGEX = False


def tag_many(texts: list[str]) -> list[dict[str, int]]:
    """Tag a batch of texts. One Claude call for the whole batch."""
    if not texts:
        return []
    if USE_REGEX or not llm.available():
        return [regex_tags(t) for t in texts]
    defs = "\n".join(f"- {k}: {v}" for k, v in config.FEATURES.items())
    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(texts))
    out = llm.ask_json(
        system="You label marketing copy for a survey-methods study. Be literal and consistent.",
        prompt=(
            f"For each numbered text, mark which wording features are present.\n\nFeatures:\n{defs}\n\n"
            f"Texts:\n{listing}\n\nReturn one item per text, using its number as index."
        ),
        schema=_SCHEMA,
    )
    by_idx = {it["index"]: it for it in out["items"]}
    tags = []
    for i, t in enumerate(texts):
        it = by_idx.get(i)
        tags.append({k: int(bool(it[k])) for k in config.FEATURES} if it else regex_tags(t))
    return tags
