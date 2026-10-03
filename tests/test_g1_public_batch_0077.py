import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0077():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0077_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={
      "HEJFE-D346C6CFDFB6E581":("WTS","2015-02-17T21:30:00Z",7860),
      "HEJFE-0273F1BFCD285E7F":("THC","2015-02-23T21:11:00Z",840),
      "HEJFE-99F31DB35F001A44":("DXCM","2015-02-25T21:01:00Z",1020),
      "HEJFE-BB62E8864F35DCD0":("WLL","2015-02-25T21:00:00Z",360),
      "HEJFE-E1B57B6A71B06A7F":("CR","2015-04-27T21:38:00Z",7140),
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
def test_batch_0077_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0077_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==62
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)

def test_batch_0077_worker2_shard_ownership():
    event_ids={
      "HEJFE-D346C6CFDFB6E581",
      "HEJFE-0273F1BFCD285E7F",
      "HEJFE-99F31DB35F001A44",
      "HEJFE-BB62E8864F35DCD0",
      "HEJFE-E1B57B6A71B06A7F",
    }
    override_out={
      "HEJFE-45E6DA32B37F83D4",
      "HEJFE-66BA40A20548B7E3",
      "HEJFE-81F188C0D790FE70",
      "HEJFE-8415E931D4314106",
    }
    assert 77 >= 62 and (77-62) % 5 == 0
    assert event_ids.isdisjoint(override_out)
    assert all(int(hashlib.sha256(eid.encode("utf-8")).hexdigest(),16) % 5 == 2 for eid in event_ids)
