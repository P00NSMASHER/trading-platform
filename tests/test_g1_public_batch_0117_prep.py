from __future__ import annotations
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/g1_batch_0117_validate_prep.py"

def _load():
    spec=importlib.util.spec_from_file_location("g1_batch_0117_validate_prep",SCRIPT)
    assert spec and spec.loader
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def test_batch_0117_prep_is_exact_main_fail_closed_and_event_bound():
    r=_load().validate()
    assert r["batch_id"]=="0117"
    assert r["event_count"]==6
    assert len(r["event_ids"])==len(set(r["event_ids"]))==6
    assert r["publish_authorized"] is False
    assert r["expected_after"]=={"exact":172,"fail_closed":2}
    assert len(r["csv_sha256"])==len(r["evidence_sha256"])==64
