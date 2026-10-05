from __future__ import annotations
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/g1_batch_0118_validate_prep.py"

def _load():
    spec = importlib.util.spec_from_file_location("g1_batch_0118_validate_prep", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_batch_0118_bio_prep_is_fail_closed_owned_and_exactly_bound():
    receipt = _load().validate()
    assert receipt["batch_id"] == "0118"
    assert receipt["event_ids"] == ["HEJFE-2FD552B9358078C6"]
    assert receipt["event_count"] == 1
    assert receipt["base_main_sha"] == "f5d983f6c5d7dbd84ccbf15271a874366cd42888"
    assert receipt["publish_authorized"] is False
    assert len(receipt["csv_sha256"]) == 64
    assert len(receipt["evidence_sha256"]) == 64
