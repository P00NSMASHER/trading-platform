#!/usr/bin/env python3
"""Fail-closed validator for Worker-0 G1 batch 0105 preparation.

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
CSV_PATH = ROOT / "data/public/metadata/g1_announcement_times_batch_0105.csv"
EVIDENCE_PATH = ROOT / "data/public/metadata/g1_public_batch_0105_evidence.json"
EXPECTED_BASE = "8014585b043217da5d5774382eb79e6a8b0972cc"
EXPECTED_IDS = {
    "HEJFE-7F8218B15679F14D",
    "HEJFE-45559DD90D876D39",
    "HEJFE-D6AE4ACB99958A73",
    "HEJFE-5408AADD0CBD54E8",
    "HEJFE-93A7D27EF425EDF0",
    "HEJFE-20EC97300E6205B9",
    "HEJFE-B04F1AF8B6E30A43",
    "HEJFE-5D222F0F8E0C77D0",
}
COURT_URL = "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf"


def validate() -> dict[str, object]:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8", newline="")))
    assert evidence["state"] == "PREPARED"
    assert evidence["base_main_sha"] == EXPECTED_BASE
    assert evidence["expected_baseline"] == {"exact": 123, "fail_closed": 51, "total": 174}
    assert evidence["expected_after_gated_integration"] == {"exact": 131, "fail_closed": 43, "total": 174}
    assert len(rows) == len(EXPECTED_IDS) == 8
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
