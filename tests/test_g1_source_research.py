from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g1_source_research as g1r


RESEARCH_PATH = ROOT / "data/public/metadata/g1_source_research_20260928.json"
EXCLUSIONS_PATH = ROOT / "data/processed/authorized_input_real/g1_final_timing_exclusions.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_research_map_builds_fail_closed_priority_queue():
    report = g1r.build_priority_queue(_load(RESEARCH_PATH), _load(EXCLUSIONS_PATH))

    assert report["status"] == "RESEARCH_PRIORITIES_READY"
    assert report["research_use_only"] is True
    assert report["required_event_count"] == 174
    assert report["exact_resolved_event_records"] == 29
    assert report["reviewed_excluded_event_records"] == 145
    assert report["priority_event_count"] == 7
    assert [row["historical_symbol"] for row in report["queue"]] == [
        "QLIK", "TNGO", "CAKE", "NKE", "BCR", "NATI", "NATI"
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
    tampered = copy.deepcopy(research)
    probe = tampered["validation_probes"][0]
    probe["evidence_eligible"] = True
    probe["historical_event_match"] = False
    probe["exact_clock_observed"] = True
    probe["exact_public_release_ts"] = "2026-02-18T16:00:00-05:00"

    with pytest.raises(g1r.G1SourceResearchError, match="historical_event_match"):
        g1r.validate_research_map(tampered, exclusions)


def test_batch_count_and_event_count_are_explicitly_distinct():
    research = _load(RESEARCH_PATH)
    state = research["current_g1_state"]

    assert state["public_exact_batch_count"] == 27
    assert state["exact_resolved_event_records"] == 29
    assert "some public batches resolve more than one historical event" in state["note"]


def test_no_public_one_stop_dataset_claim_is_preserved():
    report = g1r.build_priority_queue(_load(RESEARCH_PATH), _load(EXCLUSIONS_PATH))

    assert report["public_one_stop_exact_timestamp_dataset_found"] is False
    assert report["licensed_complete_candidate"]["provider_family"] == "LSEG I/B/E/S Historical Estimates / Actuals"
    assert report["licensed_complete_candidate"]["lawful_access_only"] is True
