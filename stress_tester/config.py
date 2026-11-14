"""Shared settings for the Wording Stress-Tester."""
from __future__ import annotations

import os
from pathlib import Path

try:  # .env is optional; mock mode needs no keys
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "outputs"
RUNS_DIR = OUT_DIR / "runs"
CACHE_DIR = OUT_DIR / "cache"
MEMORY_DIR = ROOT / "memory"
RULES_PATH = MEMORY_DIR / "rules.json"
OBS_PATH = MEMORY_DIR / "observations.json"

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

# The one fixed question every variant is scored on.
QUESTION = (
    "How appealing is this offer to you personally? "
    "Answer with a single whole number from 1 (not at all appealing) to 10 (extremely appealing)."
)

# Wording features the learner looks for. Keys are stable ids; values are the
# definitions handed to Claude when it tags text.
FEATURES: dict[str, str] = {
    "jargon": "uses financial jargon or acronyms (APY, APR, FDIC, CD, compounding, variable rate, yield)",
    "negation": "sells by saying what is NOT there (no fees, never, zero, without, don't)",
    "loss_frame": "frames the offer as avoiding a loss (stop losing, don't let X eat, miss out, before it's gone)",
    "many_numbers": "contains three or more separate numbers or percentages",
    "long": "longer than about 22 words",
    "urgency": "pressures the reader on time (today, now, limited time, act now, before rates drop)",
}

# Stability thresholds (see README "How the numbers work").
UNSTABLE_WSS = 1.5      # spread at least 1.5x what pure noise would produce...
UNSTABLE_P = 0.05       # ...and a permutation test says it's unlikely to be noise...
MIN_SPREAD = 1.0        # ...and the swing is big enough to matter (1 point on the 1-10 scale)
MIN_RULE_EFFECT = 0.3   # points on the 1-10 scale before a feature becomes a rule

MARKET_EXPERIMENT_COST = 4500  # USD, 2025 podcast figure, may be out of date
