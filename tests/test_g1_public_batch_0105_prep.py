from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/g1_batch_0105_validate_prep.py"


def _load():
    spec = importlib.util.spec_from_file_location("g1_batch_0105_validate_prep", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_batch_0105_prep_is_fail_closed_and_consistent():
    receipt = _load().validate()
    assert receipt["batch_id"] == "0105"
    assert receipt["event_count"] == 8
    assert receipt["publish_authorized"] is False
    assert len(receipt["event_ids"]) == len(set(receipt["event_ids"])) == 8
    assert len(receipt["csv_sha256"]) == 64
    assert len(receipt["evidence_sha256"]) == 64
