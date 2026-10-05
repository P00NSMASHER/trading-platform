import csv, hashlib, json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
BATCH=ROOT/"data/public/metadata/g1_announcement_times_batch_0130.csv"
EVIDENCE=ROOT/"data/public/metadata/g1_public_batch_0130_evidence.json"
EID="HEJFE-BD3F577ADD90D512"

def rows(path):
    with path.open(newline="",encoding="utf-8") as h:
        return list(csv.DictReader(h))

def test_batch_0130_gntx_exact_publisher_binding_and_resolution():
    evidence=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    item=evidence["items"][0]
    hist={x["event_id"]:x for x in rows(ROOT/"data/processed/historical_events.csv")}
    resolved={x["event_id"]:x for x in rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert item["event_id"]==EID
    assert item["historical_symbol"]=="GNTX"==hist[EID]["historical_symbol"]
    assert item["globenewswire_release_id"]==930758
    assert item["public_announcement_ts"]=="2013-10-22T08:03:00-04:00"
    assert item["publisher_metadata_utc"]=="2013-10-22T12:03:00Z"
    assert item["information_asymmetry_seconds"]==60120
    assert item["source_family"]=="official_newswire_archive"
    assert item["timestamp_evidence_kind"]=="publisher_timestamp"
    assert item["source_grade"]=="A"
    assert item["source_reference"].startswith("https://www.globenewswire.com/news-release/2013/10/22/930758/")
    assert item["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
    trade=datetime.fromisoformat(item["first_documented_illicit_trade_ts"])
    release=datetime.fromisoformat(item["public_announcement_ts"])
    assert trade < release
    assert int((release-trade).total_seconds())==60120
    assert resolved[EID]["resolution_status"]=="resolved_exact_public_timestamp"
    assert resolved[EID]["public_announcement_ts"]==release.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00","Z")

def test_batch_0130_completes_all_174_exact():
    evidence=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    resolved={x["event_id"]:x for x in rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert evidence["previous_exact_count"]==173
    assert evidence["expected_exact_count_after_batch"]==174
    assert evidence["expected_excluded_after_batch"]==0
    assert hashlib.sha256(BATCH.read_bytes()).hexdigest()==evidence["batch_sha256"]
    assert len(resolved)==174
    assert all(x["resolution_status"]=="resolved_exact_public_timestamp" for x in resolved.values())
    assert all(x["public_announcement_ts"] for x in resolved.values())

def test_batch_0130_worker0_natural_shard_and_lane():
    assert 130>=60 and (130-60)%5==0
    assert int(hashlib.sha256(EID.encode("utf-8")).hexdigest(),16)%5==0
