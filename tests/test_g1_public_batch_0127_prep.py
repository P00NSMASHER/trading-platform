from pathlib import Path
import importlib.util
ROOT=Path(__file__).resolve().parents[1]
def test_batch_0127_prep():
    p=ROOT/"scripts/g1_batch_0127_validate_prep.py"; s=importlib.util.spec_from_file_location("v",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); r=m.validate()
    assert r["event_count"]==1 and r["expected_after"]=={"exact":173,"fail_closed":1} and r["publish_authorized"] is False
