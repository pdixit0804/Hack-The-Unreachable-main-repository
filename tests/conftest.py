import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from stress_tester import config, llm  # noqa: E402


@pytest.fixture
def offline_workspace(tmp_path, monkeypatch):
    """Run the pipeline against a scratch copy of outputs/ and memory/ so tests never touch tracked files."""
    llm.set_mode("off")
    for name, val in {"OUT_DIR": tmp_path / "outputs", "RUNS_DIR": tmp_path / "outputs" / "runs",
                      "CACHE_DIR": tmp_path / "outputs" / "cache", "MEMORY_DIR": tmp_path / "memory",
                      "RULES_PATH": tmp_path / "memory" / "rules.json", "OBS_PATH": tmp_path / "memory" / "obs.json"}.items():
        monkeypatch.setattr(config, name, val)
    yield tmp_path
    llm.set_mode("auto")


@pytest.fixture(autouse=True)
def _offline_claude():
    """Tests never call the real Claude API, even when .env holds a working key.

    Tests that need Claude replace llm.available / llm.ask_json with a fake themselves.
    """
    llm.set_mode("off")
    yield
    llm.set_mode("auto")
