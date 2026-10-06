from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as control_plan
import g5_external_acquisition_packet as packet
import g5_external_metadata_intake as external_intake
import g5_external_source_manifest_scaffold as scaffold
import g5_external_source_queue as control_external
import g5_treated_metadata_requirements as treated_plan


PACKET_FIELDS = [
    "packet_request_id",
    "source_request_id",
    "target_type",
    "event_id",
    "lane",
    "event_date",
    "symbol",
    "latest_acceptable_effective_ts_utc",
    "required_fields",
    "preferred_routes",
    "cost_profile",
    "status",
    "eligible_g5_evidence",
    "research_use_only",
]


def _write_full_packet(path: Path) -> None:
    rows = []
    counter = 0
    for target_kind in ("CONTROL", "TREATED"):
        for lane, spec in control_external.LANES.items():
            counter += 1
            rows.append(
                {
                    "packet_request_id": f"PKT-{counter}",
                    "source_request_id": f"SRC-{counter}",
                    "target_type": target_kind,
                    "event_id": f"E-{counter}" if target_kind == "TREATED" else "",
                    "lane": lane,
                    "event_date": "2015-01-05",
                    "symbol": f"S{counter}",
                    "latest_acceptable_effective_ts_utc": "2015-01-05T15:00:00Z",
                    "required_fields": ";".join(spec["fields"]),
                    "preferred_routes": ";".join(spec["preferred_routes"]),
                    "cost_profile": spec["cost_profile"],
                    "status": "SOURCE_REQUIRED",
                    "eligible_g5_evidence": "0",
                    "research_use_only": "1",
                }
            )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PACKET_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_manifest_scaffold_emits_exact_fail_closed_slots(tmp_path: Path):
    packet_path = tmp_path / "packet.csv"
    _write_full_packet(packet_path)

    out = tmp_path / "out"
    summary = scaffold.build(
        acquisition_requests_path=packet_path,
        output_dir=out,
    )

    assert summary["packet_request_count"] == 8
    assert summary["source_slot_count"] == 8
    assert summary["target_slot_counts"] == {
        "control": 4,
        "treated": 4,
    }
    assert summary["lane_slot_counts"] == {
        "classification": 2,
        "ownership": 2,
        "analyst": 2,
        "borrow": 2,
    }
    assert summary["all_packet_requests_reconciled"] is True
    assert summary["manifest_intake_ready"] is False
    assert summary["canonical_g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False

    manifest_path = out / "g5_external_source_manifest.template.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1"
    assert manifest["intake_ready"] is False
    assert len(manifest["sources"]) == 8
    assert all(source["expected_sha256"] == "" for source in manifest["sources"])
    assert all(
        source["authorization_reference"] == ""
        for source in manifest["sources"]
    )
    assert all(source["source_name"] == "" for source in manifest["sources"])

    for source in manifest["sources"]:
        template = out / source["path"]
        assert template.is_file()
        assert source["template_sha256"] == scaffold._sha256(template)


def test_template_headers_match_canonical_lane_fields(tmp_path: Path):
    packet_path = tmp_path / "packet.csv"
    _write_full_packet(packet_path)
    out = tmp_path / "out"
    scaffold.build(
        acquisition_requests_path=packet_path,
        output_dir=out,
    )

    for target_kind in ("control", "treated"):
        for lane, spec in control_external.LANES.items():
            path = out / "sources" / f"{target_kind}_{lane}.csv"
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader)
                assert list(reader) == []
            assert header == [
                "event_date",
                "symbol",
                "effective_ts_utc",
                *spec["fields"],
            ]


def test_blank_manifest_template_cannot_enter_intake(tmp_path: Path):
    packet_path = tmp_path / "packet.csv"
    _write_full_packet(packet_path)
    out = tmp_path / "out"
    scaffold.build(
        acquisition_requests_path=packet_path,
        output_dir=out,
    )

    with pytest.raises(
        external_intake.G5ExternalMetadataIntakeError,
        match="expected_sha256 must be 64 hex characters",
    ):
        external_intake._load_manifest(
            out / "g5_external_source_manifest.template.json"
        )


def test_missing_target_lane_slot_fails_closed(tmp_path: Path):
    packet_path = tmp_path / "packet.csv"
    _write_full_packet(packet_path)
    fields, rows = scaffold._read_csv(packet_path)
    rows = [
        row
        for row in rows
        if not (
            row["target_type"] == "TREATED"
            and row["lane"] == "borrow"
        )
    ]
    with packet_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(
        scaffold.G5ExternalSourceManifestScaffoldError,
        match="source-slot coverage mismatch",
    ):
        scaffold.build(
            acquisition_requests_path=packet_path,
            output_dir=tmp_path / "out",
        )


def test_real_packet_scaffolds_all_1560_external_requests(tmp_path: Path):
    control_dir = tmp_path / "controls"
    control_external_dir = tmp_path / "control_external"
    treated_dir = tmp_path / "treated"
    packet_dir = tmp_path / "packet"
    scaffold_dir = tmp_path / "scaffold"

    control_plan.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=(
            ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"
        ),
        planning_universe_path=(
            ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv"
        ),
        output_dir=control_dir,
    )
    control_external.build(
        candidate_path=control_dir / "g5_primary_candidate_symbol_dates.csv",
        output_dir=control_external_dir,
    )
    treated_plan.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        output_dir=treated_dir,
    )
    packet_summary = packet.build(
        control_requests_path=(
            control_external_dir / "g5_external_source_requests.csv"
        ),
        treated_requests_path=(
            treated_dir / "g5_treated_external_lane_requests.csv"
        ),
        output_dir=packet_dir,
    )
    summary = scaffold.build(
        acquisition_requests_path=(
            packet_dir / "g5_external_acquisition_requests.csv"
        ),
        output_dir=scaffold_dir,
    )

    assert packet_summary["total_lane_request_count"] == 1560
    assert summary["packet_request_count"] == 1560
    assert summary["source_slot_count"] == 8
    assert summary["target_slot_counts"] == {
        "control": 4,
        "treated": 4,
    }
    assert summary["lane_slot_counts"] == {
        "classification": 2,
        "ownership": 2,
        "analyst": 2,
        "borrow": 2,
    }

    checklist = list(
        csv.DictReader(
            (scaffold_dir / "g5_external_source_manifest_checklist.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(checklist) == 8
    assert sum(
        int(row["request_count"])
        for row in checklist
        if row["target_kind"] == "control"
    ) == 864
    assert sum(
        int(row["request_count"])
        for row in checklist
        if row["target_kind"] == "treated"
    ) == 696
    assert summary["manifest_intake_ready"] is False
    assert summary["policy"]["data_fetch_performed"] is False
    assert summary["policy"]["purchase_performed"] is False
