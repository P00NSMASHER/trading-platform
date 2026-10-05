from __future__ import annotations
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/g1_batch_0118_validate_prep.py"
def _load():
    spec=importlib.util.spec_from_file_location("g1_batch_0118_validate_prep",SCRIPT)
    assert spec and spec.loader
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def test_batch_0118_bio_prep_is_fail_closed_owned_and_exactly_bound():
    r=_load().validate()
    assert r["batch_id"]=="0118"
    assert r["event_ids"]==["HEJFE-2FD552B9358078C6"]
    assert r["event_count"]==1
    assert r["base_main_sha"]=="60764bc4494820e36c001fe13a5e6cbe0a83740e"
    assert r["publish_authorized"] is False
    assert len(r["csv_sha256"])==len(r["evidence_sha256"])==64
