"""Panel adapters. Every adapter exposes the same call:

    score(text, segment, n, run_label) -> PanelResult

so switching between the mock panel and the real Flashpoint panel is one flag.
Every result is cached in outputs/runs/<adapter>/ so a panel run is never paid twice.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass

from .. import config, QUESTION_VERSION


@dataclass
class PanelResult:
    text: str
    run_label: str
    mean: float
    n: int
    sd: float | None = None
    responses: list[int] | None = None  # per-persona answers, when the panel returns them
    source: str = "synthetic"
    adapter: str = "mock"


def summarize(text, run_label, responses, adapter, source="synthetic") -> PanelResult:
    return PanelResult(
        text=text,
        run_label=run_label,
        mean=statistics.fmean(responses),
        n=len(responses),
        sd=statistics.stdev(responses) if len(responses) > 1 else None,
        responses=list(responses),
        source=source,
        adapter=adapter,
    )


def get_adapter(name: str):
    if name == "mock":
        from . import mock as m
    elif name == "flashpoint":
        from . import flashpoint as m
    elif name == "claude-mcp":
        from . import claude_mcp as m
    elif name == "import":
        from . import imported as m
    else:
        raise ValueError(f"unknown panel adapter {name!r}")
    return m


def score(adapter: str, text: str, segment: str, n: int, run_label: str) -> PanelResult:
    key_src = json.dumps([adapter, text, segment, n, run_label, config.QUESTION, QUESTION_VERSION])
    key = hashlib.sha256(key_src.encode()).hexdigest()[:24]
    d = config.RUNS_DIR / adapter
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{key}.json"
    if path.exists():
        return PanelResult(**json.loads(path.read_text()))
    res = get_adapter(adapter).score(text=text, segment=segment, n=n, run_label=run_label)
    path.write_text(json.dumps(asdict(res), indent=2))
    return res
