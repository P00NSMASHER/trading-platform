#!/usr/bin/env python3
"""Fail-closed validator for Worker-4 G1 batch 0119 PNRA-2013 prep."""
from __future__ import annotations
import csv, hashlib, json
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CSV_PATH=ROOT/"data/public/metadata/g1_announcement_times_batch_0119.csv"
EVIDENCE_PATH=ROOT/"data/public/metadata/g1_public_batch_0119_evidence.json"
HISTORICAL=ROOT/"data/processed/historical_events.csv"
RESOLUTIONS=ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv"
EXCLUSIONS=ROOT/"data/processed/authorized_input_real/g1_final_timing_exclusions.json"
EXPECTED_BASE="55eb6e4c600d2e21bb4a26b616feb6a3ec9e6d00"
EVENT_ID="HEJFE-CCC7747CFBDE893E"
COURT_URL="https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf"
SEC_URL="https://www.sec.gov/Archives/edgar/data/724606/000072460613000016/a20130326ex991pressrelease.htm"
def _rows(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def _sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def validate():
    ev=json.loads(EVIDENCE_PATH.read_text(encoding="utf-8")); rows=_rows(CSV_PATH)
    assert ev["batch_id"]=="0119" and ev["lane"]=="worker-4" and ev["state"]=="PREPARED" and ev["publish_authorized"] is False
    assert ev["base_main_sha"]==EXPECTED_BASE
    assert ev["refresh_note"]=="Refreshed from exact post-BIO main; event remains fail-closed, owned, and unclaimed while the controller marker is stale."
    assert ev["expected_baseline"]=={"exact":165,"fail_closed":9,"total":174}
    assert ev["expected_after_gated_integration"]=={"exact":166,"fail_closed":8,"total":174}
    assert len(rows)==len(ev["items"])==1
    row=rows[0]; item=ev["items"][0]
    assert row["event_id"]==item["event_id"]==EVENT_ID
    assert int(hashlib.sha256(EVENT_ID.encode()).hexdigest(),16)%5==4
    assert row["historical_symbol"]==item["historical_symbol"]=="PNRA"
    assert row["event_date"]==item["event_date"]=="2013-04-23"
    assert row["public_announcement_ts"]==item["public_announcement_ts"]=="2013-04-23T16:00:00-04:00"
    assert row["timestamp_kind"]==item["timestamp_kind"]=="first_public_release"
    assert row["source_grade"]==item["source_grade"]=="A" and row["source_reference"]==COURT_URL
    assert item["gx8002_row"]==1657 and item["wire_code"]=="MW"
    assert item["press_release_submission_ts"]=="2013-04-23T13:05:00-04:00"
    assert item["court_earliest_order_ts"]=="2013-04-23T15:00:00-04:00"
    assert item["release_member"]=="2013/QTR2/76695_20130423_1.txt"
    assert item["corroboration_reference"]==SEC_URL
    assert item["release_title"]=="Panera Bread Company Reports Q1 2013 diluted EPS of $1.64, up 17%"
    assert "exact equality with GX 8002 Earliest Order Time" in item["mapping_exception_reason"]
    trade=datetime.fromisoformat(item["first_documented_illicit_trade_ts"]); release=datetime.fromisoformat(item["public_announcement_ts"])
    assert trade<release and int((release-trade).total_seconds())==5700
    historical={r["event_id"]:r for r in _rows(HISTORICAL)}
    assert historical[EVENT_ID]["historical_symbol"]=="PNRA"
    assert historical[EVENT_ID]["first_documented_illicit_trade_ts"]=="2013-04-23 14:25:00"
    resolutions={r["event_id"]:r for r in _rows(RESOLUTIONS)}
    assert resolutions[EVENT_ID]["resolution_status"]=="excluded_fail_closed" and not resolutions[EVENT_ID]["public_announcement_ts"]
    ex=json.loads(EXCLUSIONS.read_text(encoding="utf-8"))["exclusions"]
    assert len(ex)==9 and sum(r["event_id"]==EVENT_ID for r in ex)==1
    assert ev["identity_corroboration"]["url"]==SEC_URL and ev["identity_corroboration"]["exhibit_type"]=="EX-99.1"
    return {"batch_id":"0119","event_ids":[EVENT_ID],"event_count":1,"base_main_sha":EXPECTED_BASE,"csv_sha256":_sha(CSV_PATH),"evidence_sha256":_sha(EVIDENCE_PATH),"publish_authorized":False}
if __name__=="__main__": print(json.dumps(validate(),indent=2,sort_keys=True))
