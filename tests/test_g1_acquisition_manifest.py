from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g1_acquisition_manifest as g1a


MANIFEST_PATH = ROOT / "data/public/metadata/g1_acquisition_manifest.json"
RESOLUTIONS_PATH = ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv"
EXCLUSIONS_PATH = ROOT / "data/processed/authorized_input_real/g1_final_timing_exclusions.json"
RESEARCH_PATH = ROOT / "data/public/metadata/g1_source_research_20260928.json"


def _current():
    rows = g1a._read_csv(RESOLUTIONS_PATH)
    exclusions = g1a._read_json(EXCLUSIONS_PATH)
    research = g1a._read_json(RESEARCH_PATH)
    return rows, exclusions, research


def test_committed_manifest_reproduces_byte_for_byte():
    rendered = g1a.render_manifest(g1a.build_manifest())
    assert rendered == MANIFEST_PATH.read_text(encoding="utf-8")


def test_full_universe_and_queue_reconcile():
    manifest = g1a.build_manifest()
    assert manifest["state"]["event_count"] == 174
    assert manifest["state"]["accounted_for"] == 174
    assert manifest["state"]["exact_resolved"] == 72
    assert manifest["state"]["acquisition_needed"] == 102
    assert len(manifest["items"]) == 174
    assert len(manifest["work_queue"]) == 102
    assert len({row["event_id"] for row in manifest["items"]}) == 174
    assert len({row["dedupe_key"] for row in manifest["work_queue"]}) == 102


def test_resolved_rows_never_reenter_acquisition_queue():
    manifest = g1a.build_manifest()
    queue_ids = {row["event_id"] for row in manifest["work_queue"]}
    resolved = [
        row for row in manifest["items"]
        if row["acquisition_status"] == "RESOLVED_NO_ACTION"
    ]
    assert len(resolved) == 72
    assert all(row["event_id"] not in queue_ids for row in resolved)
    assert all(row["routes"] == [] for row in resolved)


def test_unresolved_rows_have_public_and_lawful_licensed_routes():
    manifest = g1a.build_manifest()
    unresolved = [
        row for row in manifest["items"]
        if row["acquisition_status"] == "NEEDS_EXACT_PUBLIC_RELEASE_CLOCK"
    ]
    assert len(unresolved) == 102
    for row in unresolved:
        assert row["routes"]["licensed_ibes"]["entitlement_required"] is True
        assert row["routes"]["licensed_ibes"]["lawful_access_only"] is True
        assert "ANNDATS_ACT" in row["routes"]["licensed_ibes"]["required_fields"]
        assert "ANNTIMS_ACT" in row["routes"]["licensed_ibes"]["required_fields"]
        assert row["routes"]["public_archive"]["exact_first_public_clock_required"] is True
        assert "archive_capture_time" in row["routes"]["public_archive"]["prohibited_timestamp_substitutes"]


def test_routing_prioritizes_clock_recovery_vs_release_discovery():
    manifest = g1a.build_manifest()
    by_id = {row["event_id"]: row for row in manifest["items"]}
    present = next(
        row for row in manifest["work_queue"]
        if "PUBLIC_RELEASE_FILE_PRESENT" in row["public_release_file_status"]
    )
    missing = next(
        row for row in manifest["work_queue"]
        if row["public_release_file_status"] == "NO_PUBLIC_REPLICATION_CANDIDATE_FILE"
    )
    assert by_id[present["event_id"]]["route_order"][0] == "public_exact_clock_recovery"
    assert by_id[missing["event_id"]]["route_order"][0] == "licensed_ibes_bulk"


def test_explicit_research_priorities_head_the_queue():
    manifest = g1a.build_manifest()
    assert [row["historical_symbol"] for row in manifest["work_queue"][:6]] == [
        "QLIK", "TNGO", "CAKE", "NKE", "NATI", "NATI"
    ]
    assert [row["queue_priority"] for row in manifest["work_queue"][:6]] == [1, 2, 3, 4, 5, 6]


def test_stale_research_counts_do_not_override_authoritative_resolution_state():
    rows, exclusions, research = _current()
    tampered = copy.deepcopy(research)
    tampered["current_g1_state"]["exact_resolved_event_records"] = 0
    tampered["current_g1_state"]["reviewed_excluded_event_records"] = 174

    manifest = g1a.build_manifest_from_data(rows, exclusions, tampered)

    assert manifest["state"]["exact_resolved"] == 72
    assert manifest["state"]["acquisition_needed"] == 102
    assert manifest["state"]["research_hint_state_matches_authoritative"] is False


def test_duplicate_resolution_event_id_fails_closed():
    rows, exclusions, research = _current()
    bad = copy.deepcopy(rows)
    bad[-1]["event_id"] = bad[0]["event_id"]

    with pytest.raises(g1a.G1AcquisitionManifestError, match="duplicate or missing event_id"):
        g1a.build_manifest_from_data(bad, exclusions, research)
