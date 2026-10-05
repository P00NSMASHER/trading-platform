import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0113():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0113_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={
          "HEJFE-263620F13A6443DD": [
            "MAT",
            "2015-04-16T20:05:00Z",
            5160
          ],
          "HEJFE-EFFA194386ABDD28": [
            "IDTI",
            "2015-05-04T20:05:00Z",
            1500
          ],
          "HEJFE-E575622C8FDAB71F": [
            "ISIL",
            "2013-04-24T20:05:00Z",
            4080
          ],
          "HEJFE-749FFC4028DF7B1C": [
            "VMW",
            "2011-04-19T20:01:00Z",
            3900
          ],
          "HEJFE-350B3481A9CBBF0E": [
            "VMW",
            "2013-10-21T20:01:00Z",
            720
          ]
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
        assert x["corroboration_reference"].startswith(("https://github.com/","https://www.sec.gov/"))
def test_batch_0113_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0113_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==9
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
def test_batch_0113_worker3_shard_ownership():
    event_ids=set([
          "HEJFE-263620F13A6443DD",
          "HEJFE-EFFA194386ABDD28",
          "HEJFE-E575622C8FDAB71F",
          "HEJFE-749FFC4028DF7B1C",
          "HEJFE-350B3481A9CBBF0E"
        ])
    assert 113 >= 63 and (113-63) % 5 == 0
    assert all(int(hashlib.sha256(eid.encode("utf-8")).hexdigest(),16) % 5 == 3 for eid in event_ids)
