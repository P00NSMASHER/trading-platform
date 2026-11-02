from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from g5_external_source_queue import LANES


SCHEMA_VERSION = "1"


class G5TreatedExternalCompressionError(ValueError):
    pass


@dataclass(frozen=True)
class CompressedTreatedExternalRequest:
    request_id: str
    lane: str
    treated_symbol: str
    required_event_count: int
    first_event_date: str
    last_event_date: str
    request_points: str
    required_fields: str
    preferred_routes: str
    cost_profile: str
    status: str = "SOURCE_REQUIRED"
    eligible_g5_evidence: int = 0
    research_use_only: int = 1


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


def _compressed_request_id(
    lane: str,
    symbol: str,
    points: list[tuple[str, str, str]],
) -> str:
    packed = ";".join(
        f"{event_id}@{event_date}@{cutoff}"
        for event_id, event_date, cutoff in points
    )
    raw = f"{lane}|{symbol}|{packed}".encode("utf-8")
    return "G5TRTC-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def build(
    *,
    treated_external_request_path: Path,
    output_dir: Path,
) -> dict:
    fields, rows = _read_csv(treated_external_request_path)
    required = {
        "request_id",
        "event_id",
        "lane",
        "event_date",
        "treated_symbol",
        "latest_acceptable_effective_ts_utc",
        "required_fields",
        "status",
        "eligible_g5_evidence",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5TreatedExternalCompressionError(
            f"treated external request file missing columns: {sorted(missing)}"
        )
    if not rows:
        raise G5TreatedExternalCompressionError(
            "treated external request file is empty"
        )

    grouped: dict[tuple[str, str], dict[str, object]] = {}
    seen_request_ids: set[str] = set()
    seen_event_lanes: set[tuple[str, str]] = set()

    for row_no, row in enumerate(rows, 2):
        request_id = row["request_id"]
        event_id = row["event_id"]
        lane = row["lane"]
        event_date = row["event_date"][:10]
        symbol = row["treated_symbol"].upper()
        cutoff = row["latest_acceptable_effective_ts_utc"]

        if not request_id or request_id in seen_request_ids:
            raise G5TreatedExternalCompressionError(
                f"treated external row {row_no}: request_id must be unique and nonblank"
            )
        seen_request_ids.add(request_id)
        if not event_id or not lane or not event_date or not symbol or not cutoff:
            raise G5TreatedExternalCompressionError(
                f"treated external row {row_no}: event/lane/date/symbol/cutoff required"
            )
        if lane not in LANES:
            raise G5TreatedExternalCompressionError(
                f"treated external row {row_no}: unknown lane {lane!r}"
            )
        expected_fields = ";".join(LANES[lane]["fields"])
        if row["required_fields"] != expected_fields:
            raise G5TreatedExternalCompressionError(
                f"treated external row {row_no}: required_fields disagree with lane contract"
            )
        if row["status"] != "SOURCE_REQUIRED":
            raise G5TreatedExternalCompressionError(
                f"treated external row {row_no}: status must equal SOURCE_REQUIRED"
            )
        if row["eligible_g5_evidence"] != "0":
            raise G5TreatedExternalCompressionError(
                f"treated external row {row_no}: eligible_g5_evidence must equal 0"
            )
        if row["research_use_only"] != "1":
            raise G5TreatedExternalCompressionError(
                f"treated external row {row_no}: research_use_only must equal 1"
            )

        event_lane = (event_id, lane)
        if event_lane in seen_event_lanes:
            raise G5TreatedExternalCompressionError(
                f"duplicate treated event/lane request: {event_id}|{lane}"
            )
        seen_event_lanes.add(event_lane)

        key = (lane, symbol)
        bucket = grouped.setdefault(
            key,
            {
                "points": [],
                "required_fields": expected_fields,
                "preferred_routes": ";".join(LANES[lane]["preferred_routes"]),
                "cost_profile": str(LANES[lane]["cost_profile"]),
            },
        )
        bucket["points"].append((event_id, event_date, cutoff))

    compressed: list[CompressedTreatedExternalRequest] = []
    flattened: list[tuple[str, str, str, str, str]] = []

    for (lane, symbol), bucket in sorted(grouped.items()):
        raw_points = list(bucket["points"])
        points = sorted(set(raw_points))
        if len(points) != len(raw_points):
            raise G5TreatedExternalCompressionError(
                f"duplicate treated request point for {lane}|{symbol}"
            )
        dates = [event_date for _event_id, event_date, _cutoff in points]
        packed = ";".join(
            f"{event_id}@{event_date}@{cutoff}"
            for event_id, event_date, cutoff in points
        )
        compressed.append(
            CompressedTreatedExternalRequest(
                request_id=_compressed_request_id(lane, symbol, points),
                lane=lane,
                treated_symbol=symbol,
                required_event_count=len(points),
                first_event_date=min(dates),
                last_event_date=max(dates),
                request_points=packed,
                required_fields=str(bucket["required_fields"]),
                preferred_routes=str(bucket["preferred_routes"]),
                cost_profile=str(bucket["cost_profile"]),
            )
        )
        flattened.extend(
            (event_id, lane, event_date, symbol, cutoff)
            for event_id, event_date, cutoff in points
        )

    expected_points = {
        (
            row["event_id"],
            row["lane"],
            row["event_date"][:10],
            row["treated_symbol"].upper(),
            row["latest_acceptable_effective_ts_utc"],
        )
        for row in rows
    }
    if set(flattened) != expected_points:
        raise G5TreatedExternalCompressionError(
            "compressed treated requests do not preserve exact event/date/cutoff scope"
        )
    if len(flattened) != len(rows):
        raise G5TreatedExternalCompressionError(
            "compressed treated requests lost or duplicated source rows"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    all_path = output_dir / "g5_treated_external_compressed_requests.csv"
    fieldnames = list(CompressedTreatedExternalRequest.__dataclass_fields__)
    with all_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in compressed:
            writer.writerow(asdict(row))

    lane_input_counts: dict[str, int] = {}
    lane_compressed_counts: dict[str, int] = {}
    lane_paths: dict[str, str] = {}
    for lane in LANES:
        lane_rows = [row for row in compressed if row.lane == lane]
        lane_path = (
            output_dir / f"g5_treated_external_{lane}_compressed_requests.csv"
        )
        with lane_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in lane_rows:
                writer.writerow(asdict(row))
        lane_input_counts[lane] = sum(1 for row in rows if row["lane"] == lane)
        lane_compressed_counts[lane] = len(lane_rows)
        lane_paths[lane] = str(lane_path)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Compress treated-event external metadata acquisition into one request "
            "per lane and historical symbol while preserving every original event_id, "
            "event date, and point-in-time cutoff. Compression changes request packaging "
            "only and never assumes cross-event metadata continuity."
        ),
        "research_use_only": True,
        "date_level_request_count": len(rows),
        "compressed_lane_symbol_request_count": len(compressed),
        "request_reduction_count": len(rows) - len(compressed),
        "compression_ratio": round(len(compressed) / len(rows), 8),
        "lane_input_counts": lane_input_counts,
        "lane_compressed_counts": lane_compressed_counts,
        "exact_request_point_count_reconciled": len(flattened),
        "unique_treated_symbol_count": len(
            {row.treated_symbol for row in compressed}
        ),
        "inputs": {
            "treated_external_request_path": str(treated_external_request_path),
            "treated_external_request_sha256": _sha256(
                treated_external_request_path
            ),
        },
        "outputs": {
            "all_compressed_requests": str(all_path),
            "lane_compressed_requests": lane_paths,
        },
        "policy": {
            "one_request_per_lane_and_symbol": True,
            "exact_event_id_date_and_cutoff_preserved": True,
            "cross_event_metadata_continuity_assumed": False,
            "compressed_rows_are_g5_evidence": False,
            "authorization_and_source_hash_still_required": True,
            "point_in_time_cutoff_still_required_for_every_event": True,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_treated_external_compression_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compress treated G5 external metadata requests by lane and symbol "
            "without losing event-specific point-in-time cutoffs."
        )
    )
    parser.add_argument("--treated-external-requests", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        treated_external_request_path=args.treated_external_requests,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
