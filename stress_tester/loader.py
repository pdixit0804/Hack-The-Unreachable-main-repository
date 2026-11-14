"""Reads concepts.csv."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass
class Concept:
    id: str
    batch: int
    segment: str
    text: str


def load_concepts(path: Path | None = None) -> list[Concept]:
    path = path or config.DATA_DIR / "concepts.csv"
    with open(path, newline="", encoding="utf-8") as f:
        return [
            Concept(id=r["id"].strip(), batch=int(r["batch"]), segment=r["segment"].strip(), text=r["text"].strip())
            for r in csv.DictReader(f)
        ]
