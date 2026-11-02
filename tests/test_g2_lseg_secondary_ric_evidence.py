import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "data/processed/g2_vendor_requests/lseg_secondary_ric_candidates.csv"
AUDIT = ROOT / "data/processed/g2_vendor_requests/lseg_secondary_ric_evidence_audit.json"


def test_secondary_lseg_ric_evidence_audit_matches_candidate_table():
    with CANDIDATES.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    expected = {
        (row["historical_symbol"], candidate)
        for row in rows
        for candidate in row["candidate_rics"].split(";")
        if candidate
    }
    confirmed = {
        (item["historical_symbol"], item["candidate_ric"])
        for item in audit["confirmations"]
    }

    assert len(rows) == 34
    assert len(expected) == 43
    assert confirmed == expected

    assert audit["summary"] == {
        "historical_symbols": 34,
        "candidate_rics": 43,
        "candidate_rics_confirmed_in_cited_sources": 43,
        "unconfirmed_candidate_rics": 0,
        "historical_date_validation_still_required": True,
        "g2_coverage_change": False,
    }

    assert len(audit["source_files"]) == 6
    assert all(item["blob_sha"] for item in audit["source_files"])
    assert all(item["confirmed_sources"] for item in audit["confirmations"])
    assert all(
        item["validation_status"] == "historical_date_validation_required"
        for item in audit["confirmations"]
    )


def test_secondary_lseg_candidates_remain_fail_closed_for_historical_date():
    with CANDIDATES.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert rows
    assert {
        row["validation_status"] for row in rows
    } == {"historical_date_validation_required"}
