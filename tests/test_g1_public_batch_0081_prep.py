import hashlib, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def test_batch_0081_worker1_ownership_and_counts():
    p=json.loads((ROOT/"data/public/metadata/g1_public_batch_0081_prep_evidence.json").read_text())
    r=json.loads((ROOT/"data/processed/authorized_input_real/metadata_readiness_summary.json").read_text())
    assert p["prep_only"] is True
    assert p["reserved_batch"]=="0081" and p["worker_slot"]==1
    assert p["previous_exact_count"]==114 and p["expected_exact_count_after_batch"]==117
    assert p["expected_excluded_after_batch"]==57
    assert r["announcement_exact_resolved"]==114 and r["announcement_events_excluded"]==60
    ids={x["event_id"] for x in p["items"]}
    assert ids=={"HEJFE-AF5106891E058D23","HEJFE-334BAA0D940A418A","HEJFE-12CC8075D3F634CD"}
    assert all(int(hashlib.sha256(x.encode()).hexdigest(),16)%5==1 for x in ids)
