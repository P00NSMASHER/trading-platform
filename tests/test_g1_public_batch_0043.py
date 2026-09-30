import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0043():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0043_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-99F3FC8CE022DEA1":("VAR","2012-01-25T21:01:00Z",11700),"HEJFE-89844B5980EB5339":("AF","2012-01-25T21:30:00Z",4320),"HEJFE-824BABBAD988A068":("SYMM","2012-01-25T21:18:00Z",5040),"HEJFE-D4E8CD312A2AA576":("ISSI","2012-01-25T21:10:00Z",4740),"HEJFE-8596DDD6A535BD90":("DEST","2012-01-26T11:00:00Z",51960)}
    assert len(d["items"])==5
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="official_newswire_archive" and x["source_grade"]=="A"
        assert x["corroboration_reference"].startswith("https://www.sec.gov/")
def test_batch_0043_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0043_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,ts in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==ts
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==92
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
