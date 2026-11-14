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


def _path(adapter, text, segment, n, run_label):
    key_src = json.dumps([adapter, text, segment, n, run_label, config.QUESTION, QUESTION_VERSION])
    key = hashlib.sha256(key_src.encode()).hexdigest()[:24]
    d = config.RUNS_DIR / adapter
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def cached(adapter, text, segment, n, run_label) -> PanelResult | None:
    path = _path(adapter, text, segment, n, run_label)
    return PanelResult(**json.loads(path.read_text())) if path.exists() else None


def save(adapter, segment, n, res: PanelResult) -> None:
    _path(adapter, res.text, segment, n, res.run_label).write_text(json.dumps(asdict(res), indent=2))


def score(adapter: str, text: str, segment: str, n: int, run_label: str) -> PanelResult:
    hit = cached(adapter, text, segment, n, run_label)
    if hit:
        return hit
    res = get_adapter(adapter).score(text=text, segment=segment, n=n, run_label=run_label)
    save(adapter, segment, n, res)
    return res


def prefetch(adapter: str, items: list[tuple[str, str, str]], n: int, log=print) -> None:
    """Score many (text, segment, run_label) items at once if the adapter supports batching.

    Slow panels (Flashpoint runs take minutes) bundle every wording with the same
    run_label into one survey, so ~6 panel runs replace ~100.
    """
    mod = get_adapter(adapter)
    if not hasattr(mod, "score_batch"):
        return
    todo = sorted({it for it in items if not cached(adapter, it[0], it[1], n, it[2])})
    if not todo:
        return
    for res, (text, segment, label) in mod.score_batch(todo, n=n, log=log):
        save(adapter, segment, n, res)
