import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0105():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0105_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-7F8218B15679F14D":["NATI","2015-04-28T20:02:00Z",7380],"HEJFE-45559DD90D876D39":["ILMN","2015-04-21T20:05:00Z",4620],"HEJFE-D6AE4ACB99958A73":["SGEN","2015-04-30T20:02:00Z",6240],"HEJFE-5408AADD0CBD54E8":["CMP","2015-04-27T20:15:00Z",1740],"HEJFE-93A7D27EF425EDF0":["MIC","2015-02-18T21:36:00Z",2280],"HEJFE-20EC97300E6205B9":["INWK","2015-02-12T21:10:00Z",7740],"HEJFE-B04F1AF8B6E30A43":["CLD","2015-02-17T21:10:00Z",2100],"HEJFE-5D222F0F8E0C77D0":["TW","2015-05-05T10:00:00Z",51180]}
    assert len(d["items"])==8
    for x in d["items"]:
        sym,utc,delta=exp[x["event_id"]];e=events[x["event_id"]]
        tr=datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"));rel=datetime.fromisoformat(x["public_announcement_ts"])
        assert e["historical_symbol"]==sym and tr<rel<=tr+timedelta(days=7) and int((rel-tr).total_seconds())==delta
        assert resolved[x["event_id"]]["public_announcement_ts"]==utc
        assert resolved[x["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert x["source_family"]=="federal_court_public_distribution_record" and x["source_grade"]=="A"
        assert x["timestamp_evidence_kind"]=="explicit_release_clock" and x["public_distribution_explicit"] is True
def test_batch_0105_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0105_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==1
def test_batch_0105_worker0_shard_ownership():
    event_ids=set(["HEJFE-7F8218B15679F14D","HEJFE-45559DD90D876D39","HEJFE-D6AE4ACB99958A73","HEJFE-5408AADD0CBD54E8","HEJFE-93A7D27EF425EDF0","HEJFE-20EC97300E6205B9","HEJFE-B04F1AF8B6E30A43","HEJFE-5D222F0F8E0C77D0"])
    assert 105 >= 60 and (105-60) % 5 == 0
    assert all(int(hashlib.sha256(eid.encode("utf-8")).hexdigest(),16) % 5 == 0 for eid in event_ids)
