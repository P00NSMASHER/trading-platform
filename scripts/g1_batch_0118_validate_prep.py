#!/usr/bin/env python3
"""Fail-closed validator for Worker-3 G1 batch 0118 BIO preparation."""
from __future__ import annotations
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/public/metadata/g1_announcement_times_batch_0118.csv"
EVIDENCE_PATH = ROOT / "data/public/metadata/g1_public_batch_0118_evidence.json"
HISTORICAL_PATH = ROOT / "data/processed/historical_events.csv"
RESOLUTIONS_PATH = ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv"
EXCLUSIONS_PATH = ROOT / "data/processed/authorized_input_real/g1_final_timing_exclusions.json"
EXPECTED_BASE = "f5d983f6c5d7dbd84ccbf15271a874366cd42888"
EVENT_ID = "HEJFE-2FD552B9358078C6"
COURT_URL = "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf"
SEC_URL = "https://www.sec.gov/Archives/edgar/data/12208/000001220813000012/bio-8k572013xex991.htm"

def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate() -> dict[str, object]:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    batch_rows = _rows(CSV_PATH)
    assert evidence["schema_version"] == "g1-public-batch-evidence-v1"
    assert evidence["batch_id"] == "0118" and evidence["lane"] == "worker-3"
    assert evidence["state"] == "PREPARED"
    assert evidence["base_main_sha"] == EXPECTED_BASE
    assert evidence["expected_baseline"] == {"exact": 150, "fail_closed": 24, "total": 174}
    assert evidence["expected_after_gated_integration"] == {"exact": 151, "fail_closed": 23, "total": 174}
    assert len(batch_rows) == len(evidence["items"]) == 1
    row = batch_rows[0]
    item = evidence["items"][0]
    assert row["event_id"] == item["event_id"] == EVENT_ID
    assert int(hashlib.sha256(EVENT_ID.encode()).hexdigest(), 16) % 5 == 3
    assert row["historical_symbol"] == item["historical_symbol"] == "BIO"
    assert row["event_date"] == item["event_date"] == "2013-05-07"
    assert row["public_announcement_ts"] == item["public_announcement_ts"] == "2013-05-07T16:15:00-04:00"
    assert row["timestamp_kind"] == item["timestamp_kind"] == "first_public_release"
    assert row["source_grade"] == item["source_grade"] == "A"
    assert row["source_reference"] == COURT_URL
    assert item["source_family"] == "federal_court_public_distribution_record"
    assert item["first_documented_illicit_trade_ts"] == "2013-05-07T15:55:00-04:00"
    assert item["gx8002_row"] == 1702 and item["wire_code"] == "MW"
    assert item["gap_seconds"] == 1200
    assert item["release_title"].rstrip(".") == "Bio-Rad Reports First-Quarter 2013 Financial Results"
    assert item["release_member"] == "2013/QTR2/61516_20130507_0.txt"
    assert item["corroboration_reference"] == SEC_URL
    assert item["explicit_clock_timezone"] == "America/New_York (EDT, UTC-04:00)"
    assert "SEC Exhibit 99.1" in item["corroboration_basis"]
    trade = datetime.fromisoformat(item["first_documented_illicit_trade_ts"])
    release = datetime.fromisoformat(item["public_announcement_ts"])
    assert trade < release and int((release - trade).total_seconds()) == 1200

    historical = {r["event_id"]: r for r in _rows(HISTORICAL_PATH)}
    assert historical[EVENT_ID]["historical_symbol"] == "BIO"
    assert historical[EVENT_ID]["first_documented_illicit_trade_ts"] == "2013-05-07 15:55:00"
    resolutions = {r["event_id"]: r for r in _rows(RESOLUTIONS_PATH)}
    assert resolutions[EVENT_ID]["resolution_status"] == "excluded_fail_closed"
    assert not resolutions[EVENT_ID]["public_announcement_ts"]
    exclusions = json.loads(EXCLUSIONS_PATH.read_text(encoding="utf-8"))["exclusions"]
    unresolved = [r for r in exclusions if r["event_id"] == EVENT_ID]
    assert len(unresolved) == 1
    assert unresolved[0]["resolution_status"] == "FAIL_CLOSED_NO_ADMISSIBLE_EXACT_PUBLIC_RELEASE_CLOCK_TIME"
    assert evidence["identity_corroboration"]["url"] == SEC_URL
    assert evidence["identity_corroboration"]["exhibit_type"] == "EX-99.1"
    assert "acceptance time is not used" in evidence["identity_corroboration"]["purpose"]
    return {
        "batch_id": "0118",
        "event_ids": [EVENT_ID],
        "event_count": 1,
        "base_main_sha": EXPECTED_BASE,
        "csv_sha256": _sha(CSV_PATH),
        "evidence_sha256": _sha(EVIDENCE_PATH),
        "publish_authorized": False,
    }

if __name__ == "__main__":
    print(json.dumps(validate(), indent=2, sort_keys=True))
