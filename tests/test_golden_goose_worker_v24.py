"""Execute the JS worker's synthetic no-D1-read test from the Python CI suite."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_worker_uses_in_memory_spot_without_d1_select():
    node=shutil.which("node")
    if node is None:
        pytest.skip("Node.js not installed; GitHub Actions runner requires Node")
    root=Path(__file__).resolve().parents[1]
    run=subprocess.run([node,"--test","tests/golden_goose_worker_v24.test.mjs"],
                       cwd=root,text=True,capture_output=True,timeout=30,check=False)
    assert run.returncode==0, (
        "Golden Goose Worker v24 synthetic tests failed; inspect Node test on the CI runner."
    )
