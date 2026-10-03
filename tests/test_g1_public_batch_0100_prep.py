from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PREP = ROOT / "data/public/metadata/g1_public_batch_0100_prep_evidence.json"
EXCLUSIONS = ROOT / "data/processed/authorized_input_real/g1_final_timing_exclusions.json"
READINESS = ROOT / "data/processed/authorized_input_real/metadata_readiness_summary.json"
EVENTS = ROOT / "data/processed/historical_events.csv"

BA_OVERRIDE = "HEJFE-45E6DA32B37F83D4"
EXPECTED = {
    "HEJFE-E4D3EE1A6CB984DB": ("EHTH", "2011-04-26T16:15:00-04:00", 4080, 939, "MW"),
    "HEJFE-45E6DA32B37F83D4": ("BA", "2012-01-25T07:30:00-05:00", 58260, 1223, "PR"),
    "HEJFE-B7EFA7CF95262283": ("LSCC", "2013-04-18T16:00:00-04:00", 5760, 1651, "MW"),
    "HEJFE-D7BD84C255F2273D": ("GORO", "2013-05-08T17:27:00-04:00", 5340, 1706, "MW"),
    "HEJFE-7482DE1CD44C1A00": ("GMCR", "2015-02-04T16:00:00-05:00", 6780, 1846, "BW"),
}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _worker(event_id: str) -> int:
    return int(hashlib.sha256(event_id.encode("utf-8")).hexdigest(), 16) % 5


def test_batch_0100_prep_is_strict_complete_and_worker0_owned():
    prep = _load(PREP)
    exclusions = _load(EXCLUSIONS)
    readiness = _load(READINESS)
    events = {row["event_id"]: row for row in _rows(EVENTS)}
    excluded = {row["event_id"]: row for row in exclusions["exclusions"]}

    assert prep["schema_version"] == "1"
    assert prep["research_use_only"] is True
    assert prep["prep_only"] is True
    assert prep["base_main_sha"] == "3cfa3c7c402b9205b7fd2b305f371bcee0f49ccd"
    assert prep["reserved_batch"] == "0100"
    assert prep["worker_slot"] == 0
    assert prep["previous_exact_count"] == 106
    assert prep["expected_exact_count_after_batch"] == 111
    assert prep["expected_excluded_after_batch"] == 63
    assert prep["source_family"] == "federal_court_public_distribution_record"
    assert prep["source_reference"].startswith("https://storage.courtlistener.com/recap/")
    assert prep["source_reference"].endswith(".pdf")
    assert prep["court_docket_reference"].startswith("https://www.courtlistener.com/docket/")
    assert prep["timestamp_evidence_kind"] == "explicit_release_clock"
    assert prep["public_distribution_explicit"] is True

    assert readiness["announcement_exact_resolved"] == 106
    assert readiness["announcement_events_excluded"] == 68

    items = prep["items"]
    assert len(items) == 5
    assert {item["event_id"] for item in items} == set(EXPECTED)

    for item in items:
        event_id = item["event_id"]
        symbol, expected_clock, expected_delta, court_event, source = EXPECTED[event_id]
        assert event_id == BA_OVERRIDE or _worker(event_id) == 0
        assert item["historical_symbol"] == symbol
        assert item["public_announcement_ts"] == expected_clock
        assert item["court_event_number"] == court_event
        assert item["court_distribution_source"] == source
        assert item["corroboration_reference"].startswith(
            "https://www.sec.gov/Archives/edgar/data/"
        )
        assert event_id in excluded
        assert excluded[event_id]["resolution_status"] == (
            "FAIL_CLOSED_NO_ADMISSIBLE_EXACT_PUBLIC_RELEASE_CLOCK_TIME"
        )

        event = events[event_id]
        assert event["historical_symbol"] == symbol
        trade = datetime.fromisoformat(
            event["first_documented_illicit_trade_ts"]
        ).replace(tzinfo=ZoneInfo("America/New_York"))
        release = datetime.fromisoformat(expected_clock)
        assert trade < release <= trade + timedelta(days=7)
        assert int((release - trade).total_seconds()) == expected_delta


def test_batch_0100_prep_preserves_fail_closed_main_state():
    prep = _load(PREP)
    readiness = _load(READINESS)
    assert prep["prep_only"] is True
    assert readiness["announcement_exact_resolved"] == prep["previous_exact_count"]
    assert readiness["announcement_events_excluded"] == 68
    assert readiness["ready_g1_exact_timing_analysis"] is False
