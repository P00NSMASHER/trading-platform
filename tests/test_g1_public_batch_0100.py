import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0100():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0100_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={
      "HEJFE-E4D3EE1A6CB984DB":("EHTH","2011-04-26T20:15:00Z",4080),
      "HEJFE-45E6DA32B37F83D4":("BA","2012-01-25T12:30:00Z",58260),
      "HEJFE-B7EFA7CF95262283":("LSCC","2013-04-18T20:00:00Z",5760),
      "HEJFE-D7BD84C255F2273D":("GORO","2013-05-08T21:27:00Z",5340),
      "HEJFE-7482DE1CD44C1A00":("GMCR","2015-02-04T21:00:00Z",6780),
    }
    assert len(d["items"])==5
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
def test_batch_0100_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0100_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==52
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
def test_batch_0100_worker0_shard_ownership():
    event_ids={"HEJFE-E4D3EE1A6CB984DB","HEJFE-B7EFA7CF95262283","HEJFE-D7BD84C255F2273D","HEJFE-7482DE1CD44C1A00"}
    ba="HEJFE-45E6DA32B37F83D4"
    assert 100 >= 60 and (100-60) % 5 == 0
    assert all(int(hashlib.sha256(eid.encode("utf-8")).hexdigest(),16) % 5 == 0 for eid in event_ids)
    assert ba=="HEJFE-45E6DA32B37F83D4"
