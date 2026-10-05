import csv,json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
EID="HEJFE-BD3F577ADD90D512"
BATCH=ROOT/"data/public/metadata/g1_announcement_times_batch_0128.csv"
EVIDENCE=ROOT/"data/public/metadata/g1_public_batch_0128_evidence.json"

def rows(path):
    with path.open(newline="",encoding="utf-8") as h:
        return list(csv.DictReader(h))

def test_batch_0128_gntx_exact_official_newswire_binding():
    ev=json.loads(EVIDENCE.read_text())
    item=ev["items"][0]
    resolved={r["event_id"]:r for r in rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert item["event_id"]==EID and item["historical_symbol"]=="GNTX"
    assert item["public_announcement_ts"]=="2013-10-22T08:03:00-04:00"
    assert item["information_asymmetry_seconds"]==60120
    assert item["source_family"]=="official_newswire_archive" and item["source_grade"]=="A"
    assert item["source_reference"].startswith("https://www.globenewswire.com/news-release/2013/10/22/930758/")
    assert item["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/355811/")
    release=datetime.fromisoformat(item["public_announcement_ts"])
    assert resolved[EID]["resolution_status"]=="resolved_exact_public_timestamp"
    assert resolved[EID]["public_announcement_ts"]==release.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00","Z")

def test_batch_0128_completes_all_174_and_step9():
    ev=json.loads(EVIDENCE.read_text())
    resolved=rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")
    assert ev["previous_exact_count"]==173
    assert ev["expected_exact_count_after_batch"]==174
    assert ev["expected_excluded_after_batch"]==0
    assert len(resolved)==174
    assert sum(r["resolution_status"]=="resolved_exact_public_timestamp" for r in resolved)==174
    exclusions=json.loads((ROOT/"data/processed/authorized_input_real/g1_final_timing_exclusions.json").read_text())
    assert exclusions["exclusions"]==[]
    ready=json.loads((ROOT/"data/processed/authorized_input_real/metadata_readiness_summary.json").read_text())
    assert ready["announcement_exact_resolved"]==174 and ready["announcement_events_excluded"]==0
    assert ready["ready_g1_exact_timing_analysis"] is True
    status=json.loads((ROOT/"data/processed/real_data_release_sprint/step_status.json").read_text())
    step9=next(r for r in status["steps"] if r["step"]==9)
    assert step9["status"]=="PASS"
    assert "174/174" in step9["evidence"]
