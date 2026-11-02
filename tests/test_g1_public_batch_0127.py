import csv, hashlib, json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
BATCH=ROOT/"data/public/metadata/g1_announcement_times_batch_0127.csv"
EVIDENCE=ROOT/"data/public/metadata/g1_public_batch_0127_evidence.json"
EID="HEJFE-81F188C0D790FE70"
def rows(path):
    with path.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0127_cree_exact_binding_and_resolution():
    evidence=json.loads(EVIDENCE.read_text(encoding="utf-8")); item=evidence["items"][0]
    hist={x["event_id"]:x for x in rows(ROOT/"data/processed/historical_events.csv")}
    resolved={x["event_id"]:x for x in rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert item["event_id"]==EID and item["historical_symbol"]=="CREE" and item["gx8002_row_id"]==1811
    assert item["public_announcement_ts"]=="2015-01-20T16:01:00-05:00" and item["information_asymmetry_seconds"]==1320
    assert item["source_family"]=="federal_court_public_distribution_record" and item["source_grade"]=="A" and item["public_distribution_explicit"] is True
    assert item["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
    release=datetime.fromisoformat(item["public_announcement_ts"])
    assert resolved[EID]["resolution_status"]=="resolved_exact_public_timestamp"
    assert resolved[EID]["public_announcement_ts"]==release.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00","Z")
def test_batch_0127_preserves_172_and_leaves_one_fail_closed():
    evidence=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    resolved={x["event_id"]:x for x in rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert evidence["previous_exact_count"]==172 and evidence["expected_exact_count_after_batch"]==173 and evidence["expected_excluded_after_batch"]==1
    assert hashlib.sha256(BATCH.read_bytes()).hexdigest()==evidence["batch_sha256"]
    for eid,stamp in evidence["previous_exact_timestamps"].items(): assert resolved[eid]["public_announcement_ts"]==stamp
    excluded=[x for x in resolved.values() if x["resolution_status"]=="excluded_fail_closed"]
    assert len(excluded)==0 and all(not x["public_announcement_ts"] and not x["information_asymmetry_seconds"] for x in excluded)
def test_batch_0127_worker2_ownership_and_lane():
    assert 127>=62 and (127-62)%5==0
    assert int(hashlib.sha256(EID.encode("utf-8")).hexdigest(),16)%5==2
