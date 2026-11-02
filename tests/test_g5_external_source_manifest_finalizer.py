from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_external_metadata_intake as external_intake
import g5_external_source_manifest_finalizer as finalizer
import g5_external_source_manifest_scaffold as scaffold
import g5_external_source_queue as external_queue


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


def _write_packet(path: Path) -> None:
    rows = []
    counter = 0
    for target_kind in ("CONTROL", "TREATED"):
        for lane, spec in external_queue.LANES.items():
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


def _value_for(field: str) -> str:
    return {
        "sector": "10",
        "index_bucket": "SP500",
        "institutional_ownership": "0.25",
        "analyst_coverage": "12",
        "borrow_cost": "0.03",
    }[field]


def _build_scaffold_and_bindings(
    tmp_path: Path,
    *,
    missing_source_id: str | None = None,
    reuse_template_source_id: str | None = None,
    prohibited_source_id: str | None = None,
) -> tuple[Path, Path, dict]:
    packet_path = tmp_path / "packet.csv"
    _write_packet(packet_path)

    scaffold_dir = tmp_path / "scaffold"
    scaffold.build(
        acquisition_requests_path=packet_path,
        output_dir=scaffold_dir,
    )
    template_path = scaffold_dir / "g5_external_source_manifest.template.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))

    deliveries_dir = tmp_path / "deliveries"
    deliveries_dir.mkdir()
    bindings = []

    for index, source in enumerate(template["sources"], 1):
        source_id = source["source_id"]
        if source_id == missing_source_id:
            continue

        if source_id == reuse_template_source_id:
            source_path = scaffold_dir / source["path"]
        else:
            source_path = deliveries_dir / f"{source_id}.csv"
            lane_fields = list(external_queue.LANES[source["lane"]]["fields"])
            header = [
                "event_date",
                "symbol",
                "effective_ts_utc",
                *lane_fields,
            ]
            if source_id == prohibited_source_id:
                header.append("hacked")
            row = [
                "2015-01-05",
                f"S{index}",
                "2015-01-05T14:00:00Z",
                *[_value_for(field) for field in lane_fields],
            ]
            if source_id == prohibited_source_id:
                row.append("1")
            with source_path.open(
                "w", encoding="utf-8", newline=""
            ) as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(header)
                writer.writerow(row)

        try:
            binding_path = source_path.relative_to(tmp_path).as_posix()
        except ValueError:
            binding_path = str(source_path)
        bindings.append(
            {
                "source_id": source_id,
                "path": binding_path,
                "authorization_reference": f"AUTHORIZED-{source_id}",
                "source_name": f"source-{source_id}",
            }
        )

    bindings_path = tmp_path / "bindings.json"
    bindings_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "bindings": bindings,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return template_path, bindings_path, template


def test_finalizer_hashes_all_eight_source_slots_and_emits_intake_manifest(
    tmp_path: Path,
):
    template_path, bindings_path, _template = _build_scaffold_and_bindings(
        tmp_path
    )

    out = tmp_path / "finalized"
    summary = finalizer.build(
        template_manifest_path=template_path,
        bindings_path=bindings_path,
        output_dir=out,
    )

    assert summary["template_source_count"] == 8
    assert summary["binding_count"] == 8
    assert summary["finalized_source_count"] == 8
    assert summary["all_source_ids_reconciled"] is True
    assert summary["intake_manifest_ready"] is True
    assert summary["canonical_g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
    assert summary["policy"]["source_files_are_not_copied"] is True
    assert summary["policy"]["source_files_are_not_fetched"] is True
    assert summary["policy"]["finalized_manifest_is_g5_evidence"] is False

    manifest_path = out / "g5_external_source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["intake_ready"] is True
    assert len(manifest["sources"]) == 8
    assert all(len(source["expected_sha256"]) == 64 for source in manifest["sources"])
    assert all(source["authorization_reference"] for source in manifest["sources"])
    assert all(source["source_name"] for source in manifest["sources"])
    assert all(source["status"] == "READY_FOR_INTAKE" for source in manifest["sources"])

    specs = external_intake._load_manifest(manifest_path)
    assert len(specs) == 8
    for source in manifest["sources"]:
        path = Path(source["path"])
        assert path.is_absolute()
        assert path.is_file()
        assert finalizer._sha256(path) == source["expected_sha256"]


def test_missing_binding_fails_closed(tmp_path: Path):
    template_path, bindings_path, template = _build_scaffold_and_bindings(
        tmp_path,
        missing_source_id="g5-treated-borrow",
    )
    assert len(template["sources"]) == 8

    with pytest.raises(
        finalizer.G5ExternalSourceManifestFinalizerError,
        match="coverage mismatch",
    ):
        finalizer.build(
            template_manifest_path=template_path,
            bindings_path=bindings_path,
            output_dir=tmp_path / "finalized",
        )


def test_empty_scaffold_template_cannot_be_bound_as_real_source(tmp_path: Path):
    template_path, bindings_path, _template = _build_scaffold_and_bindings(
        tmp_path,
        reuse_template_source_id="g5-control-classification",
    )

    with pytest.raises(
        finalizer.G5ExternalSourceManifestFinalizerError,
        match="empty scaffold template may not be used",
    ):
        finalizer.build(
            template_manifest_path=template_path,
            bindings_path=bindings_path,
            output_dir=tmp_path / "finalized",
        )


def test_prohibited_retrospective_source_column_fails_closed(tmp_path: Path):
    template_path, bindings_path, _template = _build_scaffold_and_bindings(
        tmp_path,
        prohibited_source_id="g5-treated-ownership",
    )

    with pytest.raises(
        finalizer.G5ExternalSourceManifestFinalizerError,
        match="prohibited retrospective/post-event columns",
    ):
        finalizer.build(
            template_manifest_path=template_path,
            bindings_path=bindings_path,
            output_dir=tmp_path / "finalized",
        )


def test_binding_source_requires_at_least_one_data_row(tmp_path: Path):
    template_path, bindings_path, template = _build_scaffold_and_bindings(
        tmp_path
    )
    target_id = "g5-control-analyst"
    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    binding = next(
        item for item in bindings["bindings"]
        if item["source_id"] == target_id
    )
    path = tmp_path / binding["path"]
    source = next(
        item for item in template["sources"]
        if item["source_id"] == target_id
    )
    lane_fields = list(external_queue.LANES[source["lane"]]["fields"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ["event_date", "symbol", "effective_ts_utc", *lane_fields]
        )

    with pytest.raises(
        finalizer.G5ExternalSourceManifestFinalizerError,
        match="contains no data rows",
    ):
        finalizer.build(
            template_manifest_path=template_path,
            bindings_path=bindings_path,
            output_dir=tmp_path / "finalized",
        )
