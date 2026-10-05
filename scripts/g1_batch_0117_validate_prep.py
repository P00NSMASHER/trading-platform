#!/usr/bin/env python3
"""Fail-closed validator for Worker-2 G1 batch 0117 court prep.

Prep only: no canonical publication or merge authority.
"""
from __future__ import annotations
import csv, hashlib, json
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CSV_PATH=ROOT/"data/public/metadata/g1_announcement_times_batch_0117_prep.csv"
EVIDENCE_PATH=ROOT/"data/public/metadata/g1_public_batch_0117_prep_evidence.json"
EXCLUSIONS=ROOT/"data/processed/authorized_input_real/g1_final_timing_exclusions.json"
EVENTS=ROOT/"data/processed/historical_events.csv"
EXPECTED_BASE="8b2622df3b4641606e5de6a80eda88244a8af49d"
EXPECTED_IDS={
"HEJFE-B5A8A297D14CD19D","HEJFE-FBA59D82CEE8FD00","HEJFE-4E643D38FFB3016E",
"HEJFE-54A5D1D8A5B593C8","HEJFE-198DE6D99E934F32",
"HEJFE-A3C5C43F6AC75C44"}
COURT_URL="https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf"

def _rows(path):
    with path.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))

def validate():
    evidence=json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    batch=_rows(CSV_PATH)
    events={r["event_id"]:r for r in _rows(EVENTS)}
    exclusions=json.loads(EXCLUSIONS.read_text(encoding="utf-8"))["exclusions"]
    unresolved={r["event_id"] for r in exclusions}
    assert evidence["state"]=="PREPARED" and evidence["publish_authorized"] is False
    assert evidence["base_main_sha"]==EXPECTED_BASE
    assert evidence["expected_baseline"]=={"exact":166,"fail_closed":8,"total":174}
    assert evidence["expected_after_gated_integration"]=={"exact":172,"fail_closed":2,"total":174}
    assert len(unresolved)==8 and EXPECTED_IDS <= unresolved
    assert len(batch)==len(EXPECTED_IDS)==6 and {r["event_id"] for r in batch}==EXPECTED_IDS
    items={x["event_id"]:x for x in evidence["items"]}
    assert set(items)==EXPECTED_IDS
    assert evidence["primary_evidence"]["family"]=="federal_court_public_distribution_record"
    for row in batch:
        eid=row["event_id"]; item=items[eid]; ev=events[eid]
        assert int(hashlib.sha256(eid.encode("utf-8")).hexdigest(),16)%5==2
        assert row["historical_symbol"]==item["historical_symbol"]==ev["historical_symbol"]
        assert row["public_announcement_ts"]==item["public_announcement_ts"]
        assert row["timestamp_kind"]=="first_public_release" and row["source_grade"]=="A"
        assert row["source_reference"]==COURT_URL
        assert item["source_code"] in {"BW","MW"}
        assert isinstance(item["gx8002_row_id"],int) and item["gx8002_row_id"]>0
        assert item["release_member"].endswith(".txt")
        assert item["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
        trade=datetime.fromisoformat(item["first_documented_illicit_trade_ts"])
        release=datetime.fromisoformat(item["public_announcement_ts"])
        assert trade.tzinfo is not None and release.tzinfo is not None and trade < release
        assert int((release-trade).total_seconds())==item["information_asymmetry_seconds"]
        assert ev["first_documented_illicit_trade_ts"].replace(" ","T")==item["first_documented_illicit_trade_ts"][:19]
    return {
      "batch_id":"0117","event_count":6,"event_ids":sorted(EXPECTED_IDS),
      "csv_sha256":hashlib.sha256(CSV_PATH.read_bytes()).hexdigest(),
      "evidence_sha256":hashlib.sha256(EVIDENCE_PATH.read_bytes()).hexdigest(),
      "publish_authorized":False,
      "expected_after":{"exact":172,"fail_closed":2},
    }

if __name__=="__main__": print(json.dumps(validate(),indent=2,sort_keys=True))
