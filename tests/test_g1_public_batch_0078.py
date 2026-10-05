import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0078():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0078_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-830337A8564B826E":("ALGN","2013-10-17T20:00:00Z",8220)}
    assert len(d["items"])==1
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="sec_litigation_public_distribution_record" and x["source_grade"]=="A"
        assert x["timestamp_evidence_kind"]=="explicit_release_clock"
        assert x["public_distribution_explicit"] is True
        assert x["source_reference"].startswith("https://www.sec.gov/files/litigation/complaints/")
        assert x["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
def test_batch_0078_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0078_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==10
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
