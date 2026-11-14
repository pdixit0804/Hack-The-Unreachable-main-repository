"""Panel results typed in by hand (e.g. from runs done in Claude Desktop).

Workflow: run `python run.py --panel import`. It writes every wording it needs
to outputs/panel_requests.csv. Run those through Flashpoint in Claude Desktop,
paste results into data/panel_import.csv (columns: text,run_label,mean,n and
optionally responses as space-separated integers), and run again.
"""
from __future__ import annotations

import csv

from .. import config
from . import PanelResult, summarize

_rows: dict | None = None
_missing: list[tuple[str, str]] = []


def _load() -> dict:
    global _rows
    if _rows is None:
        _rows = {}
        path = config.DATA_DIR / "panel_import.csv"
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    _rows[(r["text"].strip(), r["run_label"].strip())] = r
    return _rows


class MissingPanelData(RuntimeError):
    pass


def score(text: str, segment: str, n: int, run_label: str) -> PanelResult:
    row = _load().get((text, run_label))
    if row is None:
        _missing.append((text, run_label))
        path = config.OUT_DIR / "panel_requests.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["text", "run_label", "segment", "n", "question"])
            w.writerow([text, run_label, segment, n, config.QUESTION])
        raise MissingPanelData(f"no imported panel result for {run_label!r}: {text[:60]}")
    if row.get("responses"):
        resp = [int(x) for x in row["responses"].split()]
        return summarize(text, run_label, resp, adapter="import", source="Flashpoint synthetic panel (imported)")
    return PanelResult(text=text, run_label=run_label, mean=float(row["mean"]), n=int(row.get("n") or n),
                       adapter="import", source="Flashpoint synthetic panel (imported, mean only)")
