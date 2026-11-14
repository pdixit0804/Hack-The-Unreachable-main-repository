import hashlib
import json
import shutil
import sys
from pathlib import Path

from stress_tester import config

ROOT = Path(__file__).resolve().parent.parent


def test_rewrite_flagged_writes_new_files_and_leaves_results_alone(offline_workspace, monkeypatch):
    out = offline_workspace / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    src = out / "results.json"
    shutil.copy(ROOT / "outputs" / "results.json", src)
    before = hashlib.sha1(src.read_bytes()).hexdigest()

    sys.path.insert(0, str(ROOT / "scripts"))
    import rewrite_flagged

    monkeypatch.setattr(sys, "argv", ["rewrite_flagged.py", "--claude", "off", "--results", str(src)])
    rewrite_flagged.main()

    assert hashlib.sha1(src.read_bytes()).hexdigest() == before
    data = json.loads((config.OUT_DIR / "rewrites_suggested.json").read_text())
    unstable = [c["id"] for c in json.loads(src.read_text())["batch2"]["concepts"] if c["unstable"]]
    assert [r["id"] for r in data["rewrites"]] == unstable
    assert "not been scored" in data["note"]
    rows = (config.OUT_DIR / "rewrite_requests.csv").read_text().splitlines()
    assert rows[0] == "id,text,segment"
    assert len(rows) - 1 == sum(r["status"] == "accepted" for r in data["rewrites"])
