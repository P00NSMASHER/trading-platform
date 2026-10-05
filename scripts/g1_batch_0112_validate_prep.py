#!/usr/bin/env python3
"""Fail-closed validator for Worker-2 G1 batch 0112 preparation.

This script does not publish canonical outputs. It validates the preserved
court evidence package before a controller-authorized exact-main regeneration.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/public/metadata/g1_announcement_times_batch_0112.csv"
EVIDENCE_PATH = ROOT / "data/public/metadata/g1_public_batch_0112_evidence.json"
EXPECTED_BASE = "8014585b043217da5d5774382eb79e6a8b0972cc"
EXPECTED_IDS = {
    "HEJFE-198DE6D99E934F32",
    "HEJFE-54A5D1D8A5B593C8",
    "HEJFE-4E643D38FFB3016E",
    "HEJFE-FBA59D82CEE8FD00",
    "HEJFE-B5A8A297D14CD19D",
    "HEJFE-A3C5C43F6AC75C44",
}
COURT_URL = "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf"


def validate() -> dict[str, object]:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8", newline="")))
    assert evidence["state"] == "PREPARED"
    assert evidence["base_main_sha"] == EXPECTED_BASE
    assert evidence["expected_baseline"] == {"exact": 123, "fail_closed": 51, "total": 174}
    assert evidence["expected_after_gated_integration"] == {"exact": 129, "fail_closed": 45, "total": 174}
    assert len(rows) == len(EXPECTED_IDS) == 6
    assert {row["event_id"] for row in rows} == EXPECTED_IDS
    assert len({row["event_id"] for row in rows}) == len(rows)
    evidence_items = {item["event_id"]: item for item in evidence["items"]}
    assert set(evidence_items) == EXPECTED_IDS
    for row in rows:
        assert row["timestamp_kind"] == "first_public_release"
        assert row["source_grade"] == "A"
        assert row["source_reference"] == COURT_URL
        stamp = datetime.fromisoformat(row["public_announcement_ts"])
        assert stamp.tzinfo is not None
        assert row["event_date"] <= stamp.date().isoformat()
        item = evidence_items[row["event_id"]]
        for key in ("historical_symbol", "event_date", "public_announcement_ts"):
            assert row[key] == item[key]
        assert item["release_member"].endswith(".txt")
    return {
        "batch_id": evidence["batch_id"],
        "event_count": len(rows),
        "event_ids": sorted(EXPECTED_IDS),
        "csv_sha256": hashlib.sha256(CSV_PATH.read_bytes()).hexdigest(),
        "evidence_sha256": hashlib.sha256(EVIDENCE_PATH.read_bytes()).hexdigest(),
        "publish_authorized": False,
    }


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2, sort_keys=True))
