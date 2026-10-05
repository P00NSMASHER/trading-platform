from __future__ import annotations
import csv,json
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EID="HEJFE-BD3F577ADD90D512"
def validate():
    ev=json.loads((ROOT/"data/public/metadata/g1_public_batch_0128_prep_evidence.json").read_text())
    ex=json.loads((ROOT/"data/processed/authorized_input_real/g1_final_timing_exclusions.json").read_text())["exclusions"]
    rows=list(csv.DictReader((ROOT/"data/public/metadata/g1_announcement_times_batch_0128_prep.csv").open()))
    hist={r["event_id"]:r for r in csv.DictReader((ROOT/"data/processed/historical_events.csv").open())}
    assert ev["state"]=="PREPARED" and ev["publish_authorized"] is False
    assert ev["base_main_sha"]=="268c842b26a696a111f89b1c88b3e92eb227672b"
    assert ev["expected_baseline"]=={"exact":173,"fail_closed":1,"total":174}
    assert ev["expected_after_gated_integration"]=={"exact":174,"fail_closed":0,"total":174}
    assert len(ex)==1 and ex[0]["event_id"]==EID
    assert len(rows)==1 and rows[0]["event_id"]==EID and rows[0]["historical_symbol"]=="GNTX"
    item=ev["items"][0]
    assert hist[EID]["historical_symbol"]=="GNTX"
    assert hist[EID]["first_documented_illicit_trade_ts"]=="2013-10-21 15:21:00"
    assert item["public_announcement_ts"]=="2013-10-22T08:03:00-04:00"
    assert item["source_family"]=="official_newswire_archive" and item["source_grade"]=="A"
    assert item["source_reference"].startswith("https://www.globenewswire.com/news-release/2013/10/22/930758/")
    assert item["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/355811/")
    trade=datetime.fromisoformat(item["first_documented_illicit_trade_ts"])
    release=datetime.fromisoformat(item["public_announcement_ts"])
    assert trade<release and int((release-trade).total_seconds())==60120
    assert ev["primary_evidence"]["embedded_article_published_time"]=="2013-10-22T12:03:00Z"
    assert "sec_edgar_acceptance_time" in ev["prohibited_substitutes"] and "conference_call_time" in ev["prohibited_substitutes"]
    return {"batch_id":"0128","event_id":EID,"expected_after":{"exact":174,"fail_closed":0},"publish_authorized":False}
if __name__=="__main__": print(json.dumps(validate(),sort_keys=True))
