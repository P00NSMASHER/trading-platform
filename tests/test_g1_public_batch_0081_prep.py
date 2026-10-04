import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_batch_0081_worker1_ownership_counts_and_exact_main():
    prep = json.loads(
        (ROOT / "data/public/metadata/g1_public_batch_0081_prep_evidence.json").read_text()
    )
    readiness = json.loads(
        (ROOT / "data/processed/authorized_input_real/metadata_readiness_summary.json").read_text()
    )

    assert prep["prep_only"] is True
    assert prep["base_main_sha"] == "3752e553ae10ae62f1d68720abe453db8cded079"
    assert prep["reserved_batch"] == "0081"
    assert prep["worker_slot"] == 1
    assert prep["previous_exact_count"] == 114
    assert prep["expected_exact_count_after_batch"] == 117
    assert prep["expected_excluded_after_batch"] == 57
    assert readiness["announcement_exact_resolved"] == 114
    assert readiness["announcement_events_excluded"] == 60

    items = {item["event_id"]: item for item in prep["items"]}
    assert set(items) == {
        "HEJFE-AF5106891E058D23",
        "HEJFE-334BAA0D940A418A",
        "HEJFE-12CC8075D3F634CD",
    }
    assert all(int(hashlib.sha256(event_id.encode()).hexdigest(), 16) % 5 == 1 for event_id in items)
    assert all(item["public_announcement_ts"] for item in items.values())
    assert all(item["corroboration_reference"].startswith("https://www.sec.gov/") for item in items.values())
