#!/usr/bin/env python3
"""Fail-closed validator for Worker-3 G1 batch 0113 preparation."""
from __future__ import annotations
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/public/metadata/g1_announcement_times_batch_0113.csv"
EVIDENCE_PATH = ROOT / "data/public/metadata/g1_public_batch_0113_evidence.json"
EXPECTED_BASE = "41e07137b5aeb3b4765b5d8d350fb4f66aa4ce28"
EXPECTED_IDS = {
    "HEJFE-263620F13A6443DD",
    "HEJFE-2FD552B9358078C6",
    "HEJFE-E575622C8FDAB71F",
    "HEJFE-749FFC4028DF7B1C",
    "HEJFE-350B3481A9CBBF0E",
}
RESOLVED_ON_BASE = {"HEJFE-EFFA194386ABDD28"}
COURT_URL = "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf"

def validate() -> dict[str, object]:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8", newline="")))
    assert evidence["state"] == "PREPARED"
    assert evidence["base_main_sha"] == EXPECTED_BASE
    assert evidence["expected_baseline"] == {"exact": 137, "fail_closed": 37, "total": 174}
    assert evidence["expected_after_gated_integration"] == {"exact": 142, "fail_closed": 32, "total": 174}
    assert len(rows) == len(EXPECTED_IDS) == 5
    assert {row["event_id"] for row in rows} == EXPECTED_IDS
    assert not ({row["event_id"] for row in rows} & RESOLVED_ON_BASE)
    assert evidence["removed_as_resolved_on_base"] == sorted(RESOLVED_ON_BASE)
    assert all(int(hashlib.sha256(eid.encode()).hexdigest(), 16) % 5 == 3 for eid in EXPECTED_IDS)
    evidence_items = {item["event_id"]: item for item in evidence["items"]}
    assert set(evidence_items) == EXPECTED_IDS
    for row in rows:
        assert row["timestamp_kind"] == "first_public_release"
        assert row["source_grade"] == "A"
        assert row["source_reference"] == COURT_URL
        stamp = datetime.fromisoformat(row["public_announcement_ts"])
        assert stamp.utcoffset().total_seconds() == -4 * 3600
        item = evidence_items[row["event_id"]]
        for key in ("historical_symbol", "event_date", "public_announcement_ts"):
            assert row[key] == item[key]
        trade = datetime.fromisoformat(item["first_documented_illicit_trade_ts"])
        assert int((stamp - trade).total_seconds()) == item["gap_seconds"] > 0
        assert item["gx8002_row"] > 0 and item["wire_code"] in {"BW", "MW"}
        assert item["source_family"] == "federal_court_public_distribution_record"
        assert item["release_title"] and item["corroboration_reference"].startswith("https://")
    return {"batch_id": evidence["batch_id"],"event_count": len(rows),"event_ids": sorted(EXPECTED_IDS),"csv_sha256": hashlib.sha256(CSV_PATH.read_bytes()).hexdigest(),"evidence_sha256": hashlib.sha256(EVIDENCE_PATH.read_bytes()).hexdigest(),"publish_authorized": False}

if __name__ == "__main__":
    print(json.dumps(validate(), indent=2, sort_keys=True))
