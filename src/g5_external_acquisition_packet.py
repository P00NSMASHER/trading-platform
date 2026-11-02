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
class ExternalAcquisitionRequest:
    packet_request_id: str
    source_request_id: str
    target_type: str
    event_id: str
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


@dataclass(frozen=True)
class ExternalAcquisitionBatch:
    batch_id: str
    lane: str
    symbol: str
    target_request_count: int
    first_event_date: str
    last_event_date: str
    request_scope: str
    required_fields: str
    preferred_routes: str
    cost_profile: str
    status: str = "SOURCE_REQUIRED"
    research_use_only: int = 1


class G5ExternalAcquisitionPacketError(ValueError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    return fields, rows


def _id(prefix: str, *parts: str) -> str:
    raw = "|".join(parts).encode("utf-8")
    return prefix + hashlib.sha256(raw).hexdigest()[:16].upper()


def _lane_spec(lane: str) -> dict:
    spec = control_external.LANES.get(lane)
    if spec is None:
        raise G5ExternalAcquisitionPacketError(f"unsupported external lane: {lane}")
    return spec


def _validate_fields(raw: str, lane: str, *, label: str) -> str:
    values = tuple(value for value in raw.split(";") if value)
    expected = tuple(_lane_spec(lane)["fields"])
    if values != expected:
        raise G5ExternalAcquisitionPacketError(
            f"{label}: required_fields {values} do not match lane {lane} fields {expected}"
        )
    return ";".join(values)


def _control_rows(path: Path) -> list[ExternalAcquisitionRequest]:
    fields, rows = _read_csv(path)
    required = {
        "request_id",
        "lane",
        "event_date",
        "candidate_symbol",
        "latest_acceptable_effective_ts_utc",
        "required_fields",
        "preferred_routes",
        "cost_profile",
        "eligible_g5_evidence",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5ExternalAcquisitionPacketError(
            f"control external queue missing columns: {sorted(missing)}"
        )
    if not rows:
        raise G5ExternalAcquisitionPacketError("control external queue is empty")

    out: list[ExternalAcquisitionRequest] = []
    seen_ids: set[str] = set()
    seen_scope: set[tuple[str, str, str]] = set()
    for row_no, row in enumerate(rows, 2):
        source_id = row["request_id"]
        lane = row["lane"]
        event_date = row["event_date"][:10]
        symbol = row["candidate_symbol"].upper()
        cutoff = row["latest_acceptable_effective_ts_utc"]
        if not source_id or source_id in seen_ids:
            raise G5ExternalAcquisitionPacketError(
                f"control row {row_no}: request_id must be unique and nonblank"
            )
        seen_ids.add(source_id)
        if not event_date or not symbol or not cutoff:
            raise G5ExternalAcquisitionPacketError(
                f"control row {row_no}: event_date, symbol, and cutoff are required"
            )
        if row["research_use_only"] != "1" or row["eligible_g5_evidence"] != "0":
            raise G5ExternalAcquisitionPacketError(
                f"control row {row_no}: planning rows must remain research-only/non-evidence"
            )
        scope = (lane, event_date, symbol)
        if scope in seen_scope:
            raise G5ExternalAcquisitionPacketError(
                f"duplicate control external scope: {lane}|{event_date}|{symbol}"
            )
        seen_scope.add(scope)

        spec = _lane_spec(lane)
        required_fields = _validate_fields(
            row["required_fields"], lane, label=f"control row {row_no}"
        )
        preferred_routes = ";".join(spec["preferred_routes"])
        if row["preferred_routes"] != preferred_routes:
            raise G5ExternalAcquisitionPacketError(
                f"control row {row_no}: preferred_routes disagree with canonical lane definition"
            )
        if row["cost_profile"] != spec["cost_profile"]:
            raise G5ExternalAcquisitionPacketError(
                f"control row {row_no}: cost_profile disagrees with canonical lane definition"
            )

        out.append(
            ExternalAcquisitionRequest(
                packet_request_id=_id(
                    "G5EXTPKT-", "CONTROL", source_id, lane, event_date, symbol
                ),
                source_request_id=source_id,
                target_type="CONTROL",
                event_id="",
                lane=lane,
                event_date=event_date,
                symbol=symbol,
                latest_acceptable_effective_ts_utc=cutoff,
                required_fields=required_fields,
                preferred_routes=preferred_routes,
                cost_profile=spec["cost_profile"],
            )
        )
    return out


def _treated_rows(path: Path) -> list[ExternalAcquisitionRequest]:
    fields, rows = _read_csv(path)
    required = {
        "request_id",
        "event_id",
        "lane",
        "event_date",
        "treated_symbol",
        "latest_acceptable_effective_ts_utc",
        "required_fields",
        "eligible_g5_evidence",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5ExternalAcquisitionPacketError(
            f"treated external queue missing columns: {sorted(missing)}"
        )
    if not rows:
        raise G5ExternalAcquisitionPacketError("treated external queue is empty")

    out: list[ExternalAcquisitionRequest] = []
    seen_ids: set[str] = set()
    seen_scope: set[tuple[str, str]] = set()
    for row_no, row in enumerate(rows, 2):
        source_id = row["request_id"]
        event_id = row["event_id"]
        lane = row["lane"]
        event_date = row["event_date"][:10]
        symbol = row["treated_symbol"].upper()
        cutoff = row["latest_acceptable_effective_ts_utc"]
        if not source_id or source_id in seen_ids:
            raise G5ExternalAcquisitionPacketError(
                f"treated row {row_no}: request_id must be unique and nonblank"
            )
        seen_ids.add(source_id)
        if not event_id or not event_date or not symbol or not cutoff:
            raise G5ExternalAcquisitionPacketError(
                f"treated row {row_no}: event_id, event_date, symbol, and cutoff are required"
            )
        if row["research_use_only"] != "1" or row["eligible_g5_evidence"] != "0":
            raise G5ExternalAcquisitionPacketError(
                f"treated row {row_no}: planning rows must remain research-only/non-evidence"
            )
        scope = (event_id, lane)
        if scope in seen_scope:
            raise G5ExternalAcquisitionPacketError(
                f"duplicate treated external scope: {event_id}|{lane}"
            )
        seen_scope.add(scope)

        spec = _lane_spec(lane)
        expected_treated = tuple(treated_external.EXTERNAL_LANES.get(lane, ()))
        if expected_treated != tuple(spec["fields"]):
            raise G5ExternalAcquisitionPacketError(
                f"lane definition drift between control and treated planners for {lane}"
            )
        required_fields = _validate_fields(
            row["required_fields"], lane, label=f"treated row {row_no}"
        )
        out.append(
            ExternalAcquisitionRequest(
                packet_request_id=_id(
                    "G5EXTPKT-", "TREATED", source_id, event_id, lane
                ),
                source_request_id=source_id,
                target_type="TREATED",
                event_id=event_id,
                lane=lane,
                event_date=event_date,
                symbol=symbol,
                latest_acceptable_effective_ts_utc=cutoff,
                required_fields=required_fields,
                preferred_routes=";".join(spec["preferred_routes"]),
                cost_profile=spec["cost_profile"],
            )
        )
    return out


def build(
    *,
    control_requests_path: Path,
    treated_requests_path: Path,
    output_dir: Path,
) -> dict:
    requests = _control_rows(control_requests_path) + _treated_rows(treated_requests_path)
    packet_ids = {row.packet_request_id for row in requests}
    if len(packet_ids) != len(requests):
        raise G5ExternalAcquisitionPacketError("packet request IDs are not unique")

    lane_counts = {lane: 0 for lane in control_external.LANES}
    control_targets: set[tuple[str, str]] = set()
    treated_targets: set[str] = set()
    field_requirements = 0
    for row in requests:
        lane_counts[row.lane] += 1
        field_requirements += len(row.required_fields.split(";"))
        if row.target_type == "CONTROL":
            control_targets.add((row.event_date, row.symbol))
        else:
            treated_targets.add(row.event_id)

    grouped: dict[tuple[str, str], list[ExternalAcquisitionRequest]] = {}
    for row in requests:
        grouped.setdefault((row.lane, row.symbol), []).append(row)

    batches: list[ExternalAcquisitionBatch] = []
    for (lane, symbol), rows in sorted(grouped.items()):
        rows = sorted(
            rows,
            key=lambda row: (
                row.event_date,
                row.latest_acceptable_effective_ts_utc,
                row.target_type,
                row.event_id,
                row.source_request_id,
            ),
        )
        spec = _lane_spec(lane)
        scope = ";".join(
            f"{row.target_type}:{row.event_id or '-'}:{row.event_date}:"
            f"{row.latest_acceptable_effective_ts_utc}"
            for row in rows
        )
        dates = [row.event_date for row in rows]
        batches.append(
            ExternalAcquisitionBatch(
                batch_id=_id("G5EXTBATCH-", lane, symbol, scope),
                lane=lane,
                symbol=symbol,
                target_request_count=len(rows),
                first_event_date=min(dates),
                last_event_date=max(dates),
                request_scope=scope,
                required_fields=";".join(spec["fields"]),
                preferred_routes=";".join(spec["preferred_routes"]),
                cost_profile=spec["cost_profile"],
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    request_path = output_dir / "g5_external_acquisition_requests.csv"
    batch_path = output_dir / "g5_external_acquisition_batches.csv"

    with request_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(ExternalAcquisitionRequest.__dataclass_fields__)
        )
        writer.writeheader()
        for row in sorted(
            requests,
            key=lambda item: (
                item.lane,
                item.symbol,
                item.event_date,
                item.target_type,
                item.event_id,
            ),
        ):
            writer.writerow(asdict(row))

    with batch_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(ExternalAcquisitionBatch.__dataclass_fields__)
        )
        writer.writeheader()
        for row in batches:
            writer.writerow(asdict(row))

    lane_paths: dict[str, str] = {}
    for lane in control_external.LANES:
        path = output_dir / f"g5_external_acquisition_{lane}.csv"
        lane_rows = [row for row in requests if row.lane == lane]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(ExternalAcquisitionRequest.__dataclass_fields__)
            )
            writer.writeheader()
            for row in sorted(
                lane_rows,
                key=lambda item: (
                    item.symbol,
                    item.event_date,
                    item.target_type,
                    item.event_id,
                ),
            ):
                writer.writerow(asdict(row))
        lane_paths[lane] = str(path)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Unify control and treated G5 external point-in-time metadata requests into "
            "one exact acquisition packet and lane-specific batches without fetching, "
            "inventing, or promoting any metadata values."
        ),
        "research_use_only": True,
        "control_target_count": len(control_targets),
        "treated_target_count": len(treated_targets),
        "total_target_count": len(control_targets) + len(treated_targets),
        "control_lane_request_count": sum(
            row.target_type == "CONTROL" for row in requests
        ),
        "treated_lane_request_count": sum(
            row.target_type == "TREATED" for row in requests
        ),
        "total_lane_request_count": len(requests),
        "external_field_requirement_count": field_requirements,
        "lane_counts": lane_counts,
        "grouped_lane_symbol_batch_count": len(batches),
        "inputs": {
            "control_requests": {
                "path": str(control_requests_path),
                "sha256": _sha256(control_requests_path),
            },
            "treated_requests": {
                "path": str(treated_requests_path),
                "sha256": _sha256(treated_requests_path),
            },
        },
        "outputs": {
            "all_requests": str(request_path),
            "grouped_batches": str(batch_path),
            "lane_requests": lane_paths,
        },
        "policy": {
            "request_rows_are_g5_evidence": False,
            "batching_does_not_assume_cross_date_value_continuity": True,
            "every_target_cutoff_is_preserved": True,
            "authorized_or_public_point_in_time_source_still_required": True,
            "post_cutoff_values_may_not_close_g5": True,
            "data_fetch_performed": False,
            "purchase_performed": False,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_external_acquisition_packet_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the complete G5 external metadata acquisition packet."
    )
    parser.add_argument("--control-requests", type=Path, required=True)
    parser.add_argument("--treated-requests", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        control_requests_path=args.control_requests,
        treated_requests_path=args.treated_requests,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
