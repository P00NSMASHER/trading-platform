from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PREP = ROOT / "data/public/metadata/g1_public_batch_0077_prep_evidence.json"
EXCLUSIONS = ROOT / "data/processed/authorized_input_real/g1_final_timing_exclusions.json"
READINESS = ROOT / "data/processed/authorized_input_real/metadata_readiness_summary.json"
EVENTS = ROOT / "data/processed/historical_events.csv"

EXPECTED = {
    "HEJFE-D346C6CFDFB6E581": ("WTS", "2015-02-17T16:30:00-05:00", 7860),
    "HEJFE-0273F1BFCD285E7F": ("THC", "2015-02-23T16:11:00-05:00", 840),
    "HEJFE-99F31DB35F001A44": ("DXCM", "2015-02-25T16:01:00-05:00", 1020),
    "HEJFE-BB62E8864F35DCD0": ("WLL", "2015-02-25T16:00:00-05:00", 360),
    "HEJFE-E1B57B6A71B06A7F": ("CR", "2015-04-27T17:38:00-04:00", 7140),
}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_batch_0077_prep_is_strict_and_complete():
    prep = _load(PREP)
    exclusions = _load(EXCLUSIONS)
    readiness = _load(READINESS)
    events = {row["event_id"]: row for row in _rows(EVENTS)}
    excluded = {row["event_id"]: row for row in exclusions["exclusions"]}

    assert prep["schema_version"] == "1"
    assert prep["research_use_only"] is True
    assert prep["prep_only"] is True
    assert prep["base_main_sha"] == "5a2dae64561880c736cb9eeb16b65f67d5894d29"
    assert prep["reserved_batch"] == "0077"
    assert prep["worker_slot"] == 2
    assert prep["previous_exact_count"] == 101
    assert prep["expected_exact_count_after_batch"] == 106
    assert prep["expected_excluded_after_batch"] == 68
    assert prep["source_family"] == "federal_court_public_distribution_record"
    assert prep["source_reference"].startswith("https://storage.courtlistener.com/recap/")
    assert prep["source_reference"].endswith(".pdf")
    assert prep["court_docket_reference"].startswith("https://www.courtlistener.com/docket/")

    assert readiness["announcement_exact_resolved"] == 101
    assert readiness["announcement_events_excluded"] == 73

    items = prep["items"]
    assert len(items) == 5
    assert {item["event_id"] for item in items} == set(EXPECTED)
    assert len({item["event_id"] for item in items}) == 5

    for item in items:
        event_id = item["event_id"]
        symbol, expected_clock, expected_delta = EXPECTED[event_id]
        assert item["historical_symbol"] == symbol
        assert item["public_announcement_ts"] == expected_clock
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


def test_batch_0077_prep_does_not_relax_fail_closed_state():
    prep = _load(PREP)
    readiness = _load(READINESS)
    assert prep["prep_only"] is True
    assert readiness["announcement_exact_resolved"] == prep["previous_exact_count"]
    assert readiness["announcement_events_excluded"] == 73
    assert readiness["ready_g1_exact_timing_analysis"] is False
