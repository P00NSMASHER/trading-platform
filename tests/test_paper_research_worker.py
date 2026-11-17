"""Run actual SQLite persistence and synthetic Worker integration in required CI."""
from pathlib import Path
import shutil
import subprocess


def test_sqlite_paper_research_worker():
    node = shutil.which("node")
    assert node, "Node 24 required for the production Worker persistence tests"
    result = subprocess.run(
        [node, "--test", "tests/paper_research_v1.test.mjs"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        timeout=40, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
