from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import g5_external_source_queue as control_external
import g5_treated_metadata_requirements as treated_external


SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class ExternalMasterRequest:
    request_id: str
    target_kind: str
    target_id: str
    lane: str
    event_date: str
    symbol: str
    latest_acceptable_effective_ts_utc: str
    required_fields: str
    preferred_routes: str
    cost_profile: str
    status: str = "SOURCE_REQUIRED"
    eligible_g5_evidence: int = 0
    research_use_only: int = 1


class G5ExternalMasterAcquisitionError(ValueError):
    pass


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    return fields, rows


def _target_id(event_date: str, symbol: str) -> str:
    raw = f"{event_date}|{symbol}".encode("utf-8")
    return "G5CTRL-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def _validate_lane_contract() -> None:
    control_lanes = control_external.LANES
    treated_lanes = treated_external.EXTERNAL_LANES
    if set(control_lanes) != set(treated_lanes):
        raise G5ExternalMasterAcquisitionError(
            "control and treated external lane names do not match"
        )
    for lane in sorted(control_lanes):
        control_fields = tuple(control_lanes[lane]["fields"])
        treated_fields = tuple(treated_lanes[lane])
        if control_fields != treated_fields:
            raise G5ExternalMasterAcquisitionError(
                f"control/treated external field contract differs for lane {lane}"
            )


def _normalize_control(rows: list[dict[str, str]]) -> list[ExternalMasterRequest]:
    out: list[ExternalMasterRequest] = []
    for row_no, row in enumerate(rows, 2):
        lane = row["lane"]
        spec = control_external.LANES.get(lane)
        if spec is None:
            raise G5ExternalMasterAcquisitionError(
                f"control external row {row_no}: unknown lane {lane!r}"
            )
        event_date = row["event_date"][:10]
        symbol = row["candidate_symbol"].upper()
        cutoff = row["latest_acceptable_effective_ts_utc"]
        if not event_date or not symbol or not cutoff:
            raise G5ExternalMasterAcquisitionError(
                f"control external row {row_no}: date/symbol/cutoff required"
            )
        if row["research_use_only"] != "1":
            raise G5ExternalMasterAcquisitionError(
                f"control external row {row_no}: research_use_only must equal 1"
            )
        expected_fields = ";".join(spec["fields"])
        expected_routes = ";".join(spec["preferred_routes"])
        if row["required_fields"] != expected_fields:
            raise G5ExternalMasterAcquisitionError(
                f"control external row {row_no}: required_fields drift"
            )
        if row["preferred_routes"] != expected_routes:
            raise G5ExternalMasterAcquisitionError(
                f"control external row {row_no}: preferred_routes drift"
            )
        if row["cost_profile"] != spec["cost_profile"]:
            raise G5ExternalMasterAcquisitionError(
                f"control external row {row_no}: cost_profile drift"
            )
        out.append(
            ExternalMasterRequest(
                request_id=row["request_id"],
                target_kind="control",
                target_id=_target_id(event_date, symbol),
                lane=lane,
                event_date=event_date,
                symbol=symbol,
                latest_acceptable_effective_ts_utc=cutoff,
                required_fields=expected_fields,
                preferred_routes=expected_routes,
                cost_profile=spec["cost_profile"],
            )
        )
    return out


def _normalize_treated(rows: list[dict[str, str]]) -> list[ExternalMasterRequest]:
    out: list[ExternalMasterRequest] = []
    for row_no, row in enumerate(rows, 2):
        lane = row["lane"]
        spec = control_external.LANES.get(lane)
        if spec is None:
            raise G5ExternalMasterAcquisitionError(
                f"treated external row {row_no}: unknown lane {lane!r}"
            )
        event_id = row["event_id"]
        event_date = row["event_date"][:10]
        symbol = row["treated_symbol"].upper()
        cutoff = row["latest_acceptable_effective_ts_utc"]
        if not event_id or not event_date or not symbol or not cutoff:
            raise G5ExternalMasterAcquisitionError(
                f"treated external row {row_no}: event/date/symbol/cutoff required"
            )
        if row["research_use_only"] != "1":
            raise G5ExternalMasterAcquisitionError(
                f"treated external row {row_no}: research_use_only must equal 1"
            )
        expected_fields = ";".join(spec["fields"])
        if row["required_fields"] != expected_fields:
            raise G5ExternalMasterAcquisitionError(
                f"treated external row {row_no}: required_fields drift"
            )
        out.append(
            ExternalMasterRequest(
                request_id=row["request_id"],
                target_kind="treated",
                target_id=event_id,
                lane=lane,
                event_date=event_date,
                symbol=symbol,
                latest_acceptable_effective_ts_utc=cutoff,
                required_fields=expected_fields,
                preferred_routes=";".join(spec["preferred_routes"]),
                cost_profile=spec["cost_profile"],
            )
        )
    return out


def build(
    *,
    control_candidates_path: Path,
    events_path: Path,
    output_dir: Path,
) -> dict:
    _validate_lane_contract()
    output_dir.mkdir(parents=True, exist_ok=True)

    control_dir = output_dir / "control_requests"
    treated_dir = output_dir / "treated_requests"

    control_summary = control_external.build(
        candidate_path=control_candidates_path,
        output_dir=control_dir,
    )
    treated_summary = treated_external.build(
        events_path=events_path,
        output_dir=treated_dir,
    )

    control_fields, control_rows = _read_csv(
        control_dir / "g5_external_source_requests.csv"
    )
    treated_fields, treated_rows = _read_csv(
        treated_dir / "g5_treated_external_lane_requests.csv"
    )

    required_control = {
        "request_id",
        "lane",
        "event_date",
        "candidate_symbol",
        "latest_acceptable_effective_ts_utc",
        "required_fields",
        "preferred_routes",
        "cost_profile",
        "research_use_only",
    }
    missing_control = required_control.difference(control_fields)
    if missing_control:
        raise G5ExternalMasterAcquisitionError(
            f"control request file missing columns: {sorted(missing_control)}"
        )

    required_treated = {
        "request_id",
        "event_id",
        "lane",
        "event_date",
        "treated_symbol",
        "latest_acceptable_effective_ts_utc",
        "required_fields",
        "research_use_only",
    }
    missing_treated = required_treated.difference(treated_fields)
    if missing_treated:
        raise G5ExternalMasterAcquisitionError(
            f"treated request file missing columns: {sorted(missing_treated)}"
        )

    requests = [
        *_normalize_control(control_rows),
        *_normalize_treated(treated_rows),
    ]
    request_ids = [row.request_id for row in requests]
    if len(request_ids) != len(set(request_ids)):
        raise G5ExternalMasterAcquisitionError(
            "control and treated external request IDs are not globally unique"
        )

    requests.sort(
        key=lambda row: (
            row.lane,
            row.event_date,
            row.symbol,
            row.target_kind,
            row.target_id,
        )
    )

    all_path = output_dir / "g5_external_master_requests.csv"
    fields_out = list(ExternalMasterRequest.__dataclass_fields__)
    with all_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields_out)
        writer.writeheader()
        for row in requests:
            writer.writerow(asdict(row))

    lane_counts: dict[str, int] = {}
    lane_field_counts: dict[str, int] = {}
    lane_paths: dict[str, str] = {}
    for lane in sorted(control_external.LANES):
        lane_rows = [row for row in requests if row.lane == lane]
        path = output_dir / f"g5_external_master_{lane}_requests.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields_out)
            writer.writeheader()
            for row in lane_rows:
                writer.writerow(asdict(row))
        lane_counts[lane] = len(lane_rows)
        lane_field_counts[lane] = sum(
            len([field for field in row.required_fields.split(";") if field])
            for row in lane_rows
        )
        lane_paths[lane] = str(path)

    target_keys = {
        (row.target_kind, row.target_id)
        for row in requests
    }
    control_target_keys = {
        row.target_id for row in requests if row.target_kind == "control"
    }
    treated_target_keys = {
        row.target_id for row in requests if row.target_kind == "treated"
    }
    field_requirement_count = sum(lane_field_counts.values())

    if len(control_rows) != int(control_summary["lane_request_count"]):
        raise G5ExternalMasterAcquisitionError(
            "control lane request count does not reconcile"
        )
    if len(treated_rows) != int(treated_summary["treated_external_lane_request_count"]):
        raise G5ExternalMasterAcquisitionError(
            "treated lane request count does not reconcile"
        )
    if field_requirement_count != (
        int(control_summary["external_field_requirement_count"])
        + int(treated_summary["treated_external_field_requirement_count"])
    ):
        raise G5ExternalMasterAcquisitionError(
            "combined external field requirement count does not reconcile"
        )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "One deterministic acquisition queue for all external point-in-time "
            "matching metadata required by both G5 controls and treated events. "
            "This unifies acquisition planning only and never promotes evidence."
        ),
        "research_use_only": True,
        "control_target_count": len(control_target_keys),
        "treated_target_count": len(treated_target_keys),
        "total_matching_target_count": len(target_keys),
        "control_lane_request_count": len(control_rows),
        "treated_lane_request_count": len(treated_rows),
        "total_lane_request_count": len(requests),
        "external_field_requirement_count": field_requirement_count,
        "lane_counts": lane_counts,
        "lane_field_requirement_counts": lane_field_counts,
        "lane_definitions": control_external.LANES,
        "inputs": {
            "control_candidates_path": str(control_candidates_path),
            "events_path": str(events_path),
        },
        "component_summaries": {
            "control": control_summary,
            "treated": treated_summary,
        },
        "outputs": {
            "all_requests": str(all_path),
            "lane_requests": lane_paths,
        },
        "policy": {
            "request_rows_are_g5_evidence": False,
            "source_hash_required_before_intake": True,
            "authorization_reference_required_before_intake": True,
            "effective_timestamp_must_not_exceed_target_cutoff": True,
            "retrospective_or_post_event_values_may_not_close_g5": True,
            "public_route_names_do_not_imply_data_availability": True,
            "purchase_authorized": False,
            "data_fetch_performed": False,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_external_master_acquisition_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build one external point-in-time metadata acquisition queue for "
            "G5 control and treated matching targets."
        )
    )
    parser.add_argument("--control-candidates", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        control_candidates_path=args.control_candidates,
        events_path=args.events,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
