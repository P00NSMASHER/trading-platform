import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parents[1]
def read_rows(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))
def test_nvr_primary_release_clock_and_event_match():
    evidence = json.loads((ROOT / "data/public/metadata/g1_public_batch_0033_evidence.json").read_text())
    item = evidence["items"][0]
    event = next(r for r in read_rows(ROOT / "data/processed/historical_events.csv") if r["event_id"] == item["event_id"])
    assert event["historical_symbol"] == "NVR"
    trade = datetime.fromisoformat(event["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
    release = datetime.fromisoformat(item["public_announcement_ts"])
    assert trade < release <= trade + timedelta(days=7)
    assert int((release-trade).total_seconds()) == 60840
    resolved = next(r for r in read_rows(ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv") if r["event_id"] == item["event_id"])
    assert resolved["public_announcement_ts"] == "2012-01-26T13:50:00Z"
    assert resolved["resolution_status"] == "resolved_exact_public_timestamp"
    assert resolved["source_reference"] == item["source_reference"]
    assert item["publisher_timestamp_text"] == "Jan 26, 2012, 08:50 ET"
    assert item["corroboration_reference"]
def test_previous_exact_evidence_preserved_and_exclusions_stay_blank():
    evidence = json.loads((ROOT / "data/public/metadata/g1_public_batch_0033_evidence.json").read_text())
    assert hashlib.sha256((ROOT / evidence["batch_path"]).read_bytes()).hexdigest() == evidence["batch_sha256"]
    by_id = {r["event_id"]:r for r in read_rows(ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert len(by_id) == 174
    for eid, timestamp in evidence["previous_exact_timestamps"].items():
        assert by_id[eid]["public_announcement_ts"] == timestamp
        assert by_id[eid]["resolution_status"] == "resolved_exact_public_timestamp"
    for row in by_id.values():
        if row["resolution_status"] == "excluded_fail_closed":
            assert not row["public_announcement_ts"] and not row["information_asymmetry_seconds"]
