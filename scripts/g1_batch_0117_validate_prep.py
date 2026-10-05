#!/usr/bin/env python3
"""Fail-closed validator for Worker-2 G1 batch 0117 court7 preparation."""
from __future__ import annotations
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/public/metadata/g1_announcement_times_batch_0117.csv"
EVIDENCE_PATH = ROOT / "data/public/metadata/g1_public_batch_0117_evidence.json"
HISTORICAL_PATH = ROOT / "data/processed/historical_events.csv"
RESOLUTIONS_PATH = ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv"
EXCLUSIONS_PATH = ROOT / "data/processed/authorized_input_real/g1_final_timing_exclusions.json"
EXPECTED_BASE = "60764bc4494820e36c001fe13a5e6cbe0a83740e"
COURT_URL = "https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf"
OVERRIDE_OUT = {"HEJFE-45E6DA32B37F83D4", "HEJFE-66BA40A20548B7E3", "HEJFE-8415E931D4314106"}
TARGETS = {
    "HEJFE-198DE6D99E934F32": {
        "event_id": "HEJFE-198DE6D99E934F32",
        "historical_symbol": "EW",
        "event_date": "2011-04-20",
        "first_documented_illicit_trade_ts": "2011-04-20T14:29:00-04:00",
        "public_announcement_ts": "2011-04-20T16:01:00-04:00",
        "gx8002_row": 934,
        "wire_code": "MW",
        "gap_seconds": 5520,
        "release_title": "Edwards Lifesciences Reports Strong First Quarter Results Driven by Sales Growth of 18.8 Percent",
        "release_member": "2011/QTR2/87657_20110420_0.txt",
        "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1099800/000110465911021363/a11-10591_1ex99d1.htm",
        "explicit_clock_timezone": "America/New_York (EDT, UTC-04:00)"
    },
    "HEJFE-81F188C0D790FE70": {
        "event_id": "HEJFE-81F188C0D790FE70",
        "historical_symbol": "CREE",
        "event_date": "2015-01-20",
        "first_documented_illicit_trade_ts": "2015-01-20T15:39:00-05:00",
        "public_announcement_ts": "2015-01-20T16:01:00-05:00",
        "gx8002_row": 1811,
        "wire_code": "BW",
        "gap_seconds": 1320,
        "release_title": "Cree Reports Financial Results for the Second Quarter of Fiscal Year 2015",
        "release_member": "2015/QTR1/78875_20150120_0.txt",
        "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/895419/000089541915000004/ex9912qfy2015.htm",
        "explicit_clock_timezone": "America/New_York (EST, UTC-05:00)"
    },
    "HEJFE-54A5D1D8A5B593C8": {
        "event_id": "HEJFE-54A5D1D8A5B593C8",
        "historical_symbol": "NUAN",
        "event_date": "2015-02-05",
        "first_documented_illicit_trade_ts": "2015-02-05T15:33:00-05:00",
        "public_announcement_ts": "2015-02-05T16:03:00-05:00",
        "gx8002_row": 1848,
        "wire_code": "BW",
        "gap_seconds": 1800,
        "release_title": "Nuance Announces First Quarter Fiscal 2015 Results",
        "release_member": "2015/QTR1/82759_20150205_0.txt",
        "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1002517/000100251715000010/ex991pressreleasedecember3.htm",
        "explicit_clock_timezone": "America/New_York (EST, UTC-05:00)"
    },
    "HEJFE-4E643D38FFB3016E": {
        "event_id": "HEJFE-4E643D38FFB3016E",
        "historical_symbol": "PNRA",
        "event_date": "2015-02-11",
        "first_documented_illicit_trade_ts": "2015-02-11T14:58:00-05:00",
        "public_announcement_ts": "2015-02-11T17:28:00-05:00",
        "gx8002_row": 1857,
        "wire_code": "MW",
        "gap_seconds": 9000,
        "release_title": "Panera Bread Company Reports Q4 2014 Diluted EPS of $1.82 and Fiscal Year 2014 Diluted EPS of $6.64",
        "release_member": "2015/QTR1/76695_20150211_0.txt",
        "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/724606/000072460615000002/a20141230exhibit991.htm",
        "explicit_clock_timezone": "America/New_York (EST, UTC-05:00)"
    },
    "HEJFE-FBA59D82CEE8FD00": {
        "event_id": "HEJFE-FBA59D82CEE8FD00",
        "historical_symbol": "CGNX",
        "event_date": "2015-02-12",
        "first_documented_illicit_trade_ts": "2015-02-12T14:04:00-05:00",
        "public_announcement_ts": "2015-02-12T16:06:00-05:00",
        "gx8002_row": 1861,
        "wire_code": "BW",
        "gap_seconds": 7320,
        "release_title": "Cognex Reports Record Results for 2014",
        "release_member": "2015/QTR1/75654_20150212_0.txt",
        "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/851205/000115752315000551/a51039264ex99_1.htm",
        "explicit_clock_timezone": "America/New_York (EST, UTC-05:00)"
    },
    "HEJFE-B5A8A297D14CD19D": {
        "event_id": "HEJFE-B5A8A297D14CD19D",
        "historical_symbol": "TXT",
        "event_date": "2015-04-27",
        "first_documented_illicit_trade_ts": "2015-04-27T15:34:00-04:00",
        "public_announcement_ts": "2015-04-28T06:30:00-04:00",
        "gx8002_row": 1947,
        "wire_code": "BW",
        "gap_seconds": 53760,
        "release_title": "Textron Reports First Quarter 2015 Income from Continuing Operations of $0.46 per Share, up 48.4%",
        "release_member": "2015/QTR2/23579_20150428_0.txt",
        "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/217346/000110465915030725/a15-10040_1ex99d1.htm",
        "explicit_clock_timezone": "America/New_York (EDT, UTC-04:00)"
    },
    "HEJFE-A3C5C43F6AC75C44": {
        "event_id": "HEJFE-A3C5C43F6AC75C44",
        "historical_symbol": "PRU",
        "event_date": "2015-05-06",
        "first_documented_illicit_trade_ts": "2015-05-06T15:47:00-04:00",
        "public_announcement_ts": "2015-05-06T16:07:00-04:00",
        "gx8002_row": 1979,
        "wire_code": "BW",
        "gap_seconds": 1200,
        "release_title": "Prudential Financial, Inc. Announces First Quarter 2015 Results",
        "release_member": "2015/QTR2/89258_20150506_0.txt",
        "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1137774/000119312515174562/d917306dex991.htm",
        "explicit_clock_timezone": "America/New_York (EDT, UTC-04:00)"
    }
}

def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate() -> dict[str, object]:
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    batch = {row["event_id"]: row for row in _rows(CSV_PATH)}
    evidence_items = {item["event_id"]: item for item in evidence["items"]}
    expected_ids = set(TARGETS)

    assert evidence["schema_version"] == "g1-public-batch-evidence-v1"
    assert evidence["batch_id"] == "0117" and evidence["lane"] == "worker-2"
    assert evidence["state"] == "PREPARED" and evidence["base_main_sha"] == EXPECTED_BASE
    assert evidence["supersedes"]["batch_id"] == "0112"
    assert evidence["expected_baseline"] == {"exact": 164, "fail_closed": 10, "total": 174}
    assert evidence["expected_after_gated_integration"] == {"exact": 171, "fail_closed": 3, "total": 174}
    assert set(batch) == set(evidence_items) == expected_ids
    assert len(batch) == len(evidence_items) == 7
    assert expected_ids.isdisjoint(OVERRIDE_OUT)
    for event_id in expected_ids:
        assert int(hashlib.sha256(event_id.encode()).hexdigest(), 16) % 5 == 2

    historical = {row["event_id"]: row for row in _rows(HISTORICAL_PATH)}
    resolutions = {row["event_id"]: row for row in _rows(RESOLUTIONS_PATH)}
    exclusions = json.loads(EXCLUSIONS_PATH.read_text(encoding="utf-8"))["exclusions"]
    unresolved = {row["event_id"]: row for row in exclusions}

    for event_id, expected in TARGETS.items():
        row = batch[event_id]
        item = evidence_items[event_id]
        assert row["historical_symbol"] == item["historical_symbol"] == expected["historical_symbol"]
        assert row["event_date"] == item["event_date"] == expected["event_date"]
        assert row["public_announcement_ts"] == item["public_announcement_ts"] == expected["public_announcement_ts"]
        assert row["timestamp_kind"] == item["timestamp_kind"] == "first_public_release"
        assert row["source_grade"] == item["source_grade"] == "A"
        assert row["source_reference"] == COURT_URL
        assert item["source_family"] == "federal_court_public_distribution_record"
        for key in ("first_documented_illicit_trade_ts", "gx8002_row", "wire_code", "gap_seconds",
                    "release_title", "release_member", "corroboration_reference", "explicit_clock_timezone"):
            assert item[key] == expected[key]
        assert item["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
        assert "sole exact public-distribution clock source" in item["corroboration_basis"]

        trade = datetime.fromisoformat(item["first_documented_illicit_trade_ts"])
        release = datetime.fromisoformat(item["public_announcement_ts"])
        assert trade < release
        assert int((release - trade).total_seconds()) == item["gap_seconds"]

        assert historical[event_id]["historical_symbol"] == expected["historical_symbol"]
        assert historical[event_id]["first_documented_illicit_trade_ts"].replace(" ", "T") == expected["first_documented_illicit_trade_ts"][:19]
        assert resolutions[event_id]["resolution_status"] == "excluded_fail_closed"
        assert not resolutions[event_id]["public_announcement_ts"]
        assert event_id in unresolved
        assert unresolved[event_id]["resolution_status"] == "FAIL_CLOSED_NO_ADMISSIBLE_EXACT_PUBLIC_RELEASE_CLOCK_TIME"

    return {
        "batch_id": "0117",
        "event_ids": sorted(expected_ids),
        "event_count": len(expected_ids),
        "base_main_sha": EXPECTED_BASE,
        "expected_baseline": evidence["expected_baseline"],
        "expected_after_gated_integration": evidence["expected_after_gated_integration"],
        "csv_sha256": _sha(CSV_PATH),
        "evidence_sha256": _sha(EVIDENCE_PATH),
        "publish_authorized": False,
    }

if __name__ == "__main__":
    print(json.dumps(validate(), indent=2, sort_keys=True))
