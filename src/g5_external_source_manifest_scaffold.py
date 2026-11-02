from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import g5_external_metadata_adapter as external_adapter
import g5_external_source_queue as external_queue


SCHEMA_VERSION = "1"
MANIFEST_SCHEMA_VERSION = "1"
TARGET_KINDS = ("control", "treated")
BASE_SOURCE_FIELDS = ("event_date", "symbol", "effective_ts_utc")


@dataclass(frozen=True)
class ExternalSourceSlot:
    source_id: str
    target_kind: str
    lane: str
    request_count: int
    unique_symbol_count: int
    first_event_date: str
    last_event_date: str
    required_fields: str
    preferred_routes: str
    cost_profile: str
    template_path: str
    template_sha256: str
    status: str = "SOURCE_FILE_AND_AUTHORIZATION_REQUIRED"
    research_use_only: int = 1


class G5ExternalSourceManifestScaffoldError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    return fields, rows


def _source_id(target_kind: str, lane: str) -> str:
    return f"g5-{target_kind}-{lane}"


def _template_name(target_kind: str, lane: str) -> str:
    return f"{target_kind}_{lane}.csv"


def _validate_packet(
    path: Path,
) -> dict[tuple[str, str], list[dict[str, str]]]:
    fields, rows = _read_csv(path)
    required = {
        "packet_request_id",
        "target_type",
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
    }
    missing = required.difference(fields)
    if missing:
        raise G5ExternalSourceManifestScaffoldError(
            f"external acquisition packet missing columns: {sorted(missing)}"
        )
    if not rows:
        raise G5ExternalSourceManifestScaffoldError(
            "external acquisition packet is empty"
        )

    seen_ids: set[str] = set()
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row_no, row in enumerate(rows, 2):
        request_id = row["packet_request_id"]
        target_kind = row["target_type"].lower()
        lane = row["lane"].lower()
        event_date = row["event_date"][:10]
        symbol = row["symbol"].upper()
        cutoff = row["latest_acceptable_effective_ts_utc"]

        if not request_id or request_id in seen_ids:
            raise G5ExternalSourceManifestScaffoldError(
                f"packet row {row_no}: packet_request_id must be unique and nonblank"
            )
        seen_ids.add(request_id)
        if target_kind not in TARGET_KINDS:
            raise G5ExternalSourceManifestScaffoldError(
                f"packet row {row_no}: target_type must be CONTROL or TREATED"
            )
        if lane not in external_queue.LANES:
            raise G5ExternalSourceManifestScaffoldError(
                f"packet row {row_no}: unsupported lane {lane!r}"
            )
        if not event_date or not symbol or not cutoff:
            raise G5ExternalSourceManifestScaffoldError(
                f"packet row {row_no}: event_date, symbol, and cutoff are required"
            )
        if (
            row["research_use_only"] != "1"
            or row["eligible_g5_evidence"] != "0"
            or row["status"] != "SOURCE_REQUIRED"
        ):
            raise G5ExternalSourceManifestScaffoldError(
                f"packet row {row_no}: acquisition rows must remain source-required/non-evidence"
            )

        spec = external_queue.LANES[lane]
        expected_fields = tuple(spec["fields"])
        adapter_fields = tuple(external_adapter.LANE_FIELDS.get(lane, ()))
        if expected_fields != adapter_fields:
            raise G5ExternalSourceManifestScaffoldError(
                f"lane definition drift for {lane}"
            )
        if tuple(x for x in row["required_fields"].split(";") if x) != expected_fields:
            raise G5ExternalSourceManifestScaffoldError(
                f"packet row {row_no}: required_fields disagree with lane {lane}"
            )
        expected_routes = ";".join(spec["preferred_routes"])
        if row["preferred_routes"] != expected_routes:
            raise G5ExternalSourceManifestScaffoldError(
                f"packet row {row_no}: preferred_routes disagree with lane {lane}"
            )
        if row["cost_profile"] != spec["cost_profile"]:
            raise G5ExternalSourceManifestScaffoldError(
                f"packet row {row_no}: cost_profile disagrees with lane {lane}"
            )

        normalized = dict(row)
        normalized["target_type"] = target_kind
        normalized["lane"] = lane
        normalized["event_date"] = event_date
        normalized["symbol"] = symbol
        grouped.setdefault((target_kind, lane), []).append(normalized)

    expected_slots = {
        (target_kind, lane)
        for target_kind in TARGET_KINDS
        for lane in external_queue.LANES
    }
    actual_slots = set(grouped)
    if actual_slots != expected_slots:
        missing_slots = sorted(expected_slots - actual_slots)
        extra_slots = sorted(actual_slots - expected_slots)
        raise G5ExternalSourceManifestScaffoldError(
            f"packet source-slot coverage mismatch: missing={missing_slots}, extra={extra_slots}"
        )
    return grouped


def build(
    *,
    acquisition_requests_path: Path,
    output_dir: Path,
) -> dict:
    grouped = _validate_packet(acquisition_requests_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    sources_dir = output_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    slots: list[ExternalSourceSlot] = []
    manifest_sources: list[dict[str, object]] = []

    for target_kind in TARGET_KINDS:
        for lane in external_queue.LANES:
            rows = grouped[(target_kind, lane)]
            spec = external_queue.LANES[lane]
            lane_fields = tuple(spec["fields"])

            template_path = sources_dir / _template_name(target_kind, lane)
            with template_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow([*BASE_SOURCE_FIELDS, *lane_fields])

            relative_template_path = (
                Path("sources") / template_path.name
            ).as_posix()
            template_sha256 = _sha256(template_path)
            dates = [row["event_date"] for row in rows]
            symbols = {row["symbol"] for row in rows}

            slot = ExternalSourceSlot(
                source_id=_source_id(target_kind, lane),
                target_kind=target_kind,
                lane=lane,
                request_count=len(rows),
                unique_symbol_count=len(symbols),
                first_event_date=min(dates),
                last_event_date=max(dates),
                required_fields=";".join(lane_fields),
                preferred_routes=";".join(spec["preferred_routes"]),
                cost_profile=spec["cost_profile"],
                template_path=relative_template_path,
                template_sha256=template_sha256,
            )
            slots.append(slot)

            manifest_sources.append(
                {
                    "source_id": slot.source_id,
                    "target_kind": target_kind,
                    "lane": lane,
                    "path": relative_template_path,
                    "expected_sha256": "",
                    "authorization_reference": "",
                    "source_name": "",
                    "request_count": slot.request_count,
                    "unique_symbol_count": slot.unique_symbol_count,
                    "required_fields": list(lane_fields),
                    "preferred_routes": list(spec["preferred_routes"]),
                    "cost_profile": spec["cost_profile"],
                    "template_sha256": template_sha256,
                    "status": "FILL_SOURCE_HASH_AUTHORIZATION_AND_NAME",
                    "research_use_only": True,
                }
            )

    manifest_path = output_dir / "g5_external_source_manifest.template.json"
    checklist_path = output_dir / "g5_external_source_manifest_checklist.csv"
    summary_path = output_dir / "g5_external_source_manifest_scaffold_summary.json"

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "purpose": (
            "Fill-in template for the hash-bound G5 external metadata intake manifest. "
            "Blank expected_sha256, authorization_reference, and source_name values are "
            "intentional and keep the template fail-closed until real source files are supplied."
        ),
        "research_use_only": True,
        "intake_ready": False,
        "sources": manifest_sources,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with checklist_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(ExternalSourceSlot.__dataclass_fields__),
        )
        writer.writeheader()
        for slot in slots:
            writer.writerow(asdict(slot))

    lane_slot_counts = {
        lane: sum(slot.lane == lane for slot in slots)
        for lane in external_queue.LANES
    }
    target_slot_counts = {
        target_kind: sum(slot.target_kind == target_kind for slot in slots)
        for target_kind in TARGET_KINDS
    }
    packet_request_count = sum(slot.request_count for slot in slots)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Deterministically bridge the complete G5 external acquisition packet into "
            "the source-manifest shape consumed by g5_external_metadata_intake without "
            "inventing source paths, hashes, authorization references, names, or data."
        ),
        "research_use_only": True,
        "packet_request_count": packet_request_count,
        "source_slot_count": len(slots),
        "target_slot_counts": target_slot_counts,
        "lane_slot_counts": lane_slot_counts,
        "all_packet_requests_reconciled": packet_request_count == sum(
            len(rows) for rows in grouped.values()
        ),
        "manifest_intake_ready": False,
        "required_fill_fields_per_slot": [
            "path_replaced_with_real_source_file_if_needed",
            "expected_sha256",
            "authorization_reference",
            "source_name",
        ],
        "inputs": {
            "acquisition_requests": {
                "path": str(acquisition_requests_path),
                "sha256": _sha256(acquisition_requests_path),
            }
        },
        "outputs": {
            "manifest_template": str(manifest_path),
            "source_checklist": str(checklist_path),
            "source_template_directory": str(sources_dir),
        },
        "policy": {
            "blank_manifest_credentials_are_intentional": True,
            "template_files_are_not_source_evidence": True,
            "template_hashes_are_not_delivery_hashes": True,
            "real_source_sha256_required_before_intake": True,
            "authorization_reference_required_before_intake": True,
            "source_name_required_before_intake": True,
            "data_fetch_performed": False,
            "purchase_performed": False,
            "scaffold_changes_canonical_g5_readiness": False,
        },
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the fail-closed source-manifest scaffold for the complete "
            "G5 external acquisition packet."
        )
    )
    parser.add_argument(
        "--acquisition-requests",
        type=Path,
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        acquisition_requests_path=args.acquisition_requests,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
