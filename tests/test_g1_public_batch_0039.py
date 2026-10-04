import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0039():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0039_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert len(d["items"])==1
    x=d["items"][0]
    assert x["event_id"]=="HEJFE-36433565499915E2" and x["historical_symbol"]=="PLL"
    e=events[x["event_id"]]
    tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
    rel=datetime.fromisoformat(x["public_announcement_ts"])
    assert tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==57420
    assert resolved[x["event_id"]]["public_announcement_ts"]=="2015-02-24T12:00:00Z"
    assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
    assert "marketscreener.com" in x["source_reference"] and x["corroboration_reference"].startswith("https://www.sec.gov/")
def test_batch_0039_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0039_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,ts in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==ts
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==53
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
