from __future__ import annotations
import csv,hashlib,json
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0036_exact_clocks():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0036_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    expected={
      "HEJFE-489E74F74AFB5AFA":("MCRL","2013-04-25T20:01:00Z",5340),
      "HEJFE-E61095F8DC4132DE":("JNPR","2013-07-23T20:05:00Z",3720),
      "HEJFE-8F17F6BEDF631C8B":("MCRI","2013-04-25T20:05:00Z",3420)}
    assert len(d["items"])==3
    for item in d["items"]:
        sym,utc,delta=expected[item["event_id"]]
        e=events[item["event_id"]]
        trade=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
        release=datetime.fromisoformat(item["public_announcement_ts"])
        assert e["historical_symbol"]==sym and trade < release <= trade+timedelta(days=7)
        assert int((release-trade).total_seconds())==delta
        assert resolved[item["event_id"]]["public_announcement_ts"]==utc
        assert resolved[item["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert item["corroboration_reference"].startswith("https://www.sec.gov/")
def test_batch_0036_preserves_prior_and_fail_closed_remainder():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0036_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,ts in d["previous_exact_timestamps"].items():
        assert by[eid]["public_announcement_ts"]==ts and by[eid]["resolution_status"]=="resolved_exact_public_timestamp"
    excluded=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"]
    assert len(excluded)==129
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
