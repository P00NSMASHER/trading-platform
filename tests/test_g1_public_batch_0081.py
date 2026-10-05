import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0081():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0081_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={
      "HEJFE-AF5106891E058D23":("TNGO","2015-02-12T21:05:00Z",3300),
      "HEJFE-334BAA0D940A418A":("TER","2015-01-28T22:32:00Z",6180),
      "HEJFE-12CC8075D3F634CD":("ECOL","2013-04-25T10:00:00Z",53580),
    }
    assert len(d["items"])==3
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="federal_court_public_distribution_record" and x["source_grade"]=="A"
        assert x["timestamp_evidence_kind"]=="explicit_release_clock"
        assert x["public_distribution_explicit"] is True
        assert x["source_reference"].startswith("https://storage.courtlistener.com/recap/")
        assert x["court_docket_reference"].startswith("https://www.courtlistener.com/docket/")
        assert x["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
def test_batch_0081_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0081_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==51
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
def test_batch_0081_worker1_shard_ownership():
    event_ids={"HEJFE-AF5106891E058D23","HEJFE-334BAA0D940A418A","HEJFE-12CC8075D3F634CD"}
    assert 81 >= 60 and (81-60) % 5 == 1
    assert all(int(hashlib.sha256(eid.encode("utf-8")).hexdigest(),16) % 5 == 1 for eid in event_ids)
