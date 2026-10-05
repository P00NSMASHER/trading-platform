from pathlib import Path
import importlib.util
ROOT=Path(__file__).resolve().parents[1]
def test_final_gntx_prep_is_exact_bound_and_fail_closed():
    p=ROOT/"scripts/g1_batch_0128_validate_prep.py"
    s=importlib.util.spec_from_file_location("g1_0128",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
    r=m.validate()
    assert r["event_id"]=="HEJFE-BD3F577ADD90D512"
    assert r["expected_after"]=={"exact":174,"fail_closed":0}
    assert r["publish_authorized"] is False
