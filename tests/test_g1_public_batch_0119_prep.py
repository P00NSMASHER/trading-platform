from __future__ import annotations
import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/g1_batch_0119_validate_prep.py"
def _load():
    spec=importlib.util.spec_from_file_location("g1_batch_0119_validate_prep",SCRIPT)
    assert spec and spec.loader
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def test_batch_0119_pnra2013_prep_is_fail_closed_owned_and_exactly_bound():
    r=_load().validate()
    assert r["batch_id"]=="0119"
    assert r["event_ids"]==["HEJFE-CCC7747CFBDE893E"]
    assert r["event_count"]==1
    assert r["base_main_sha"]=="55eb6e4c600d2e21bb4a26b616feb6a3ec9e6d00"
    assert r["publish_authorized"] is False
    assert len(r["csv_sha256"])==len(r["evidence_sha256"])==64
