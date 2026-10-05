from __future__ import annotations
import csv, hashlib, json
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EID="HEJFE-81F188C0D790FE70"
def validate():
    ev=json.loads((ROOT/"data/public/metadata/g1_public_batch_0127_prep_evidence.json").read_text())
    ex=json.loads((ROOT/"data/processed/authorized_input_real/g1_final_timing_exclusions.json").read_text())["exclusions"]
    policy=json.loads((ROOT/"data/public/metadata/g1_swarm_controller_policy.json").read_text())
    rows=list(csv.DictReader((ROOT/"data/public/metadata/g1_announcement_times_batch_0127_prep.csv").open()))
    assert ev["state"]=="PREPARED" and ev["publish_authorized"] is False and ev["base_main_sha"]=="a3fe4734237bbdc7ad79e75c34a6b3c513b2e1bf"
    assert ev["expected_baseline"]=={"exact":172,"fail_closed":2,"total":174}
    assert ev["expected_after_gated_integration"]=={"exact":173,"fail_closed":1,"total":174}
    assert len(ex)==2 and sum(x["event_id"]==EID for x in ex)==1 and len(rows)==1 and rows[0]["event_id"]==EID
    assert policy["event_owner_overrides"][EID]==2 and int(hashlib.sha256(EID.encode()).hexdigest(),16)%5==2
    item=ev["items"][0]; trade=datetime.fromisoformat(item["first_documented_illicit_trade_ts"]); release=datetime.fromisoformat(item["public_announcement_ts"])
    assert item["gx8002_row_id"]==1811 and item["historical_symbol"]=="CREE" and item["source_code"]=="BW"
    assert item["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
    assert trade<release and int((release-trade).total_seconds())==1320
    return {"batch_id":"0127","event_count":1,"expected_after":{"exact":173,"fail_closed":1},"publish_authorized":False}
if __name__=="__main__": print(json.dumps(validate(),sort_keys=True))
