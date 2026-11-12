"""Run startup/repair/shutdown in a fresh interpreter to catch Qt lifetime failures."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_application_smoke_exits_cleanly(tmp_path):
    report = tmp_path / "report.json"
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    process = subprocess.run(
        [sys.executable, "-m", "pm7fixer.app", "--smoke-test", str(report)],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["repair"] == "passed"
    assert result["non_preview_sha256"] == "passed"
    assert result["update_button"] == "Update Preview"
    assert result["formats"] == {
        extension: "passed" for extension in (".pm7", ".pwsz", ".pm7m", ".pm4u", ".pp1", ".pp1m")
    }
