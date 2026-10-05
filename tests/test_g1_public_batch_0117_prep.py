from __future__ import annotations
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/g1_batch_0117_validate_prep.py"

def _load():
    spec = importlib.util.spec_from_file_location("g1_batch_0117_validate_prep", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_batch_0117_worker2_court7_prep_is_fail_closed_owned_and_exactly_bound():
    receipt = _load().validate()
    assert receipt["batch_id"] == "0117"
    assert receipt["event_count"] == 7
    assert receipt["base_main_sha"] == "60764bc4494820e36c001fe13a5e6cbe0a83740e"
    assert receipt["expected_baseline"] == {"exact": 164, "fail_closed": 10, "total": 174}
    assert receipt["expected_after_gated_integration"] == {"exact": 171, "fail_closed": 3, "total": 174}
    assert receipt["event_ids"] == sorted({
        "HEJFE-198DE6D99E934F32", "HEJFE-81F188C0D790FE70",
        "HEJFE-54A5D1D8A5B593C8", "HEJFE-4E643D38FFB3016E",
        "HEJFE-FBA59D82CEE8FD00", "HEJFE-B5A8A297D14CD19D",
        "HEJFE-A3C5C43F6AC75C44",
    })
    assert receipt["publish_authorized"] is False
    assert len(receipt["csv_sha256"]) == len(receipt["evidence_sha256"]) == 64
