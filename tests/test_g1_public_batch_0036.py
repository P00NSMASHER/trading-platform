from __future__ import annotations
import csv
import hashlib
import json
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def read_rows(path):
    with path.open(newline="",encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
def test_batch_0036_exact_clocks_and_event_match():
    dossier=json.loads((ROOT/"data/public/metadata/g1_public_batch_0036_evidence.json").read_text())
    events={r["event_id"]:r for r in read_rows(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in read_rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    expected={
        "HEJFE-489E74F74AFB5AFA":("MCRL","2013-04-25T20:01:00Z",5340),
        "HEJFE-E61095F8DC4132DE":("JNPR","2013-07-23T20:05:00Z",3720),
    }
    assert len(dossier["items"])==2
    for item in dossier["items"]:
        symbol,utc,delta=expected[item["event_id"]]
        event=events[item["event_id"]]
        trade=datetime.fromisoformat(event["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
        release=datetime.fromisoformat(item["public_announcement_ts"])
        assert event["historical_symbol"]==symbol
        assert trade < release <= trade+timedelta(days=7)
        assert int((release-trade).total_seconds())==delta
        assert resolved[item["event_id"]]["public_announcement_ts"]==utc
        assert resolved[item["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert resolved[item["event_id"]]["source_grade"]=="B"
        assert item["source_family"]=="preserved_wire_mirror"
        assert item["corroboration_reference"].startswith("https://")
def test_batch_0036_hash_prior_evidence_and_fail_closed_remainder():
    dossier=json.loads((ROOT/"data/public/metadata/g1_public_batch_0036_evidence.json").read_text())
    assert hashlib.sha256((ROOT/dossier["batch_path"]).read_bytes()).hexdigest()==dossier["batch_sha256"]
    by_id={r["event_id"]:r for r in read_rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert len(by_id)==174
    for eid,timestamp in dossier["previous_exact_timestamps"].items():
        assert by_id[eid]["public_announcement_ts"]==timestamp
        assert by_id[eid]["resolution_status"]=="resolved_exact_public_timestamp"
    excluded=[r for r in by_id.values() if r["resolution_status"]=="excluded_fail_closed"]
    assert len(excluded)==108
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
