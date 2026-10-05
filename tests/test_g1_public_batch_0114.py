import csv,json,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def rr(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def test_batch_0114():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0114_evidence.json").read_text())
    events={r["event_id"]:r for r in rr(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    exp={"HEJFE-4080E04F012A7290":["QLIK","2015-02-12T21:05:00Z",1560],"HEJFE-7CEFB3FE3D986464":["ROG","2015-02-17T21:01:00Z",1020],"HEJFE-9861757889227DD4":["IDTI","2015-02-02T21:05:00Z",6060],"HEJFE-8EAA8616B1750B40":["CGNX","2015-05-04T20:06:00Z",3420],"HEJFE-8415E931D4314106":["KOPN","2015-03-10T20:05:00Z",4020],"HEJFE-0AA84E6E44ED02D8":["AMSG","2015-02-25T21:00:00Z",180],"HEJFE-947F50EBAFBA54DC":["CRL","2015-02-10T21:30:00Z",2100],"HEJFE-791693865584F9CB":["COL","2015-04-23T11:30:00Z",61260],"HEJFE-22BF36BABB9D19D7":["ALNY","2015-02-12T21:00:00Z",300],"HEJFE-E28050410A1480C6":["DYN","2015-05-06T20:07:00Z",6180],"HEJFE-0704950C71CFAFB4":["TXRH","2015-02-23T21:02:00Z",2280],"HEJFE-C926C41F03E66E82":["PAY","2014-12-15T21:01:00Z",1500],"HEJFE-826F68D9DA88B37C":["ATRC","2015-02-23T21:02:00Z",240],"HEJFE-A5AE76F13A48C40F":["DGI","2013-05-07T20:02:00Z",5580]}
    assert len(d["items"])==14
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
def test_batch_0114_preserves_prior():
    d=json.loads((ROOT/"data/public/metadata/g1_public_batch_0114_evidence.json").read_text())
    assert hashlib.sha256((ROOT/d["batch_path"]).read_bytes()).hexdigest()==d["batch_sha256"]
    by={r["event_id"]:r for r in rr(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    for eid,stamp in d["previous_exact_timestamps"].items():assert by[eid]["public_announcement_ts"]==stamp
    ex=[r for r in by.values() if r["resolution_status"]=="excluded_fail_closed"];assert len(ex)==29
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in ex)
def test_batch_0114_worker4_shard_ownership():
    event_ids=set(["HEJFE-4080E04F012A7290","HEJFE-7CEFB3FE3D986464","HEJFE-9861757889227DD4","HEJFE-8EAA8616B1750B40","HEJFE-8415E931D4314106","HEJFE-0AA84E6E44ED02D8","HEJFE-947F50EBAFBA54DC","HEJFE-791693865584F9CB","HEJFE-22BF36BABB9D19D7","HEJFE-E28050410A1480C6","HEJFE-0704950C71CFAFB4","HEJFE-C926C41F03E66E82","HEJFE-826F68D9DA88B37C","HEJFE-A5AE76F13A48C40F"])
    assert 114 >= 64 and (114-64) % 5 == 0
    assert all(int(hashlib.sha256(eid.encode("utf-8")).hexdigest(),16) % 5 == 4 for eid in event_ids)
