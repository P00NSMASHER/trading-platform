from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g1_source_research as g1r


RESEARCH_PATH = ROOT / "data/public/metadata/g1_source_research_20260928.json"
EXCLUSIONS_PATH = ROOT / "data/processed/authorized_input_real/g1_final_timing_exclusions.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _eligible_probe(exclusions: dict) -> dict:
    row = exclusions["exclusions"][0]
    trade = datetime.fromisoformat(row["first_documented_illicit_trade_ts"])
    trade = trade.replace(tzinfo=ZoneInfo("America/New_York"))
    release = trade + timedelta(hours=1)
    return {
        "probe_id": "TEST-ELIGIBLE-PROBE",
        "event_id": row["event_id"],
        "historical_symbol": row["historical_symbol"],
        "historical_event_match": True,
        "exact_clock_observed": True,
        "exact_public_release_ts": release.isoformat(),
        "timestamp_kind": "first_public_release",
        "timestamp_evidence_kind": "publisher_timestamp",
        "source_family": "official_newswire_archive",
        "source_reference": "https://example.test/release",
        "evidence_eligible": True,
    }


def test_research_map_builds_fail_closed_priority_queue():
    report = g1r.build_priority_queue(_load(RESEARCH_PATH), _load(EXCLUSIONS_PATH))

    assert report["status"] == "RESEARCH_PRIORITIES_READY"
    assert report["research_use_only"] is True
    assert report["required_event_count"] == 174
    assert report["exact_resolved_event_records"] == 31
    assert report["reviewed_excluded_event_records"] == 143
    assert report["priority_event_count"] == 6
    assert [row["historical_symbol"] for row in report["queue"]] == [
        "QLIK", "TNGO", "CAKE", "NKE", "NATI", "NATI"
    ]
    assert all(
        row["current_resolution_status"]
        == "FAIL_CLOSED_NO_ADMISSIBLE_EXACT_PUBLIC_RELEASE_CLOCK_TIME"
        for row in report["queue"]
    )


def test_2026_and_date_only_probes_are_never_promoted():
    research = _load(RESEARCH_PATH)
    probes = {row["probe_id"]: row for row in research["validation_probes"]}

    assert probes["CAKE-2026-Q4FY25"]["evidence_eligible"] is False
    assert probes["CAKE-2026-Q1"]["evidence_eligible"] is False
    assert probes["CAKE-2026-Q2"]["evidence_eligible"] is False
    assert probes["TNGO-2026-H1"]["evidence_eligible"] is False
    assert all(
        not row.get("evidence_eligible", False)
        for row in research["validation_probes"]
    )


def test_false_positive_promotion_fails_closed():
    research = _load(RESEARCH_PATH)
    exclusions = _load(EXCLUSIONS_PATH)
    probe = _eligible_probe(exclusions)
    probe["historical_event_match"] = False
    research["validation_probes"].append(probe)

    with pytest.raises(g1r.G1SourceResearchError, match="historical_event_match"):
        g1r.validate_research_map(research, exclusions)


def test_valid_eligible_probe_passes_independent_checks():
    research = _load(RESEARCH_PATH)
    exclusions = _load(EXCLUSIONS_PATH)
    research["validation_probes"].append(_eligible_probe(exclusions))

    result = g1r.validate_research_map(research, exclusions)
    assert result["validation_probe_count"] == len(research["validation_probes"])


def test_eligible_probe_requires_timezone_aware_timestamp():
    research = _load(RESEARCH_PATH)
    exclusions = _load(EXCLUSIONS_PATH)
    probe = _eligible_probe(exclusions)
    parsed = datetime.fromisoformat(probe["exact_public_release_ts"])
    probe["exact_public_release_ts"] = parsed.replace(tzinfo=None).isoformat()
    research["validation_probes"].append(probe)

    with pytest.raises(g1r.G1SourceResearchError, match="timezone-aware"):
        g1r.validate_research_map(research, exclusions)


def test_eligible_probe_rejects_symbol_mismatch():
    research = _load(RESEARCH_PATH)
    exclusions = _load(EXCLUSIONS_PATH)
    probe = _eligible_probe(exclusions)
    probe["historical_symbol"] = "WRONG"
    research["validation_probes"].append(probe)

    with pytest.raises(g1r.G1SourceResearchError, match="historical_symbol"):
        g1r.validate_research_map(research, exclusions)


def test_eligible_probe_rejects_non_release_timestamp_semantics():
    research = _load(RESEARCH_PATH)
    exclusions = _load(EXCLUSIONS_PATH)
    probe = _eligible_probe(exclusions)
    probe["timestamp_evidence_kind"] = "archive_capture_time"
    research["validation_probes"].append(probe)

    with pytest.raises(g1r.G1SourceResearchError, match="timestamp_evidence_kind"):
        g1r.validate_research_map(research, exclusions)


def test_eligible_probe_must_be_after_first_documented_trade():
    research = _load(RESEARCH_PATH)
    exclusions = _load(EXCLUSIONS_PATH)
    probe = _eligible_probe(exclusions)
    row = exclusions["exclusions"][0]
    trade = datetime.fromisoformat(row["first_documented_illicit_trade_ts"])
    trade = trade.replace(tzinfo=ZoneInfo("America/New_York"))
    probe["exact_public_release_ts"] = trade.isoformat()
    research["validation_probes"].append(probe)

    with pytest.raises(g1r.G1SourceResearchError, match="strictly after"):
        g1r.validate_research_map(research, exclusions)


def test_eligible_probe_must_be_within_seven_calendar_days():
    research = _load(RESEARCH_PATH)
    exclusions = _load(EXCLUSIONS_PATH)
    probe = _eligible_probe(exclusions)
    row = exclusions["exclusions"][0]
    trade = datetime.fromisoformat(row["first_documented_illicit_trade_ts"])
    trade = trade.replace(tzinfo=ZoneInfo("America/New_York"))
    probe["exact_public_release_ts"] = (trade + timedelta(days=8)).isoformat()
    research["validation_probes"].append(probe)

    with pytest.raises(g1r.G1SourceResearchError, match="seven calendar days"):
        g1r.validate_research_map(research, exclusions)


def test_preserved_wire_mirror_requires_corroboration():
    research = _load(RESEARCH_PATH)
    exclusions = _load(EXCLUSIONS_PATH)
    probe = _eligible_probe(exclusions)
    probe["source_family"] = "preserved_wire_mirror"
    research["validation_probes"].append(probe)

    with pytest.raises(g1r.G1SourceResearchError, match="corroboration_reference"):
        g1r.validate_research_map(research, exclusions)

    probe["corroboration_reference"] = "https://example.test/corroboration"
    g1r.validate_research_map(research, exclusions)


def test_batch_count_and_event_count_are_explicitly_distinct():
    research = _load(RESEARCH_PATH)
    state = research["current_g1_state"]

    assert state["public_exact_batch_count"] == 29
    assert state["exact_resolved_event_records"] == 31
    assert "some public batches resolve more than one historical event" in state["note"]


def test_no_public_one_stop_dataset_claim_is_preserved():
    report = g1r.build_priority_queue(_load(RESEARCH_PATH), _load(EXCLUSIONS_PATH))

    assert report["public_one_stop_exact_timestamp_dataset_found"] is False
    assert report["licensed_complete_candidate"]["provider_family"] == "LSEG I/B/E/S Historical Estimates / Actuals"
    assert report["licensed_complete_candidate"]["lawful_access_only"] is True
