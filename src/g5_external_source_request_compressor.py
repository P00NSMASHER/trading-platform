from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


SCHEMA_VERSION = "1"


class G5ExternalSourceCompressionError(ValueError):
    pass


@dataclass(frozen=True)
class CompressedExternalSourceRequest:
    request_id: str
    lane: str
    candidate_symbol: str
    required_date_count: int
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
    request_points: list[tuple[str, str]],
) -> str:
    packed = ";".join(
        f"{event_date}@{cutoff}" for event_date, cutoff in request_points
    )
    raw = f"{lane}|{symbol}|{packed}".encode("utf-8")
    return "G5EXTC-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def build(
    *,
    external_request_path: Path,
    output_dir: Path,
) -> dict:
    fields, rows = _read_csv(external_request_path)
    required = {
        "request_id",
        "lane",
        "event_date",
        "candidate_symbol",
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
        raise G5ExternalSourceCompressionError(
            f"external source request file missing columns: {sorted(missing)}"
        )
    if not rows:
        raise G5ExternalSourceCompressionError(
            "external source request file is empty"
        )

    grouped: dict[tuple[str, str], dict[str, object]] = {}
    seen_request_ids: set[str] = set()
    seen_points: set[tuple[str, str, str]] = set()

    for row_no, row in enumerate(rows, 2):
        request_id = row["request_id"]
        lane = row["lane"]
        event_date = row["event_date"][:10]
        symbol = row["candidate_symbol"].upper()
        cutoff = row["latest_acceptable_effective_ts_utc"]

        if not request_id or request_id in seen_request_ids:
            raise G5ExternalSourceCompressionError(
                f"external source row {row_no}: request_id must be unique and nonblank"
            )
        seen_request_ids.add(request_id)
        if not lane or not event_date or not symbol or not cutoff:
            raise G5ExternalSourceCompressionError(
                f"external source row {row_no}: lane/date/symbol/cutoff required"
            )
        if row["eligible_g5_evidence"] != "0":
            raise G5ExternalSourceCompressionError(
                f"external source row {row_no}: eligible_g5_evidence must equal 0"
            )
        if row["research_use_only"] != "1":
            raise G5ExternalSourceCompressionError(
                f"external source row {row_no}: research_use_only must equal 1"
            )

        point = (lane, event_date, symbol)
        if point in seen_points:
            raise G5ExternalSourceCompressionError(
                f"duplicate external lane/date/symbol request: {lane}|{event_date}|{symbol}"
            )
        seen_points.add(point)

        key = (lane, symbol)
        bucket = grouped.setdefault(
            key,
            {
                "points": [],
                "required_fields": row["required_fields"],
                "preferred_routes": row["preferred_routes"],
                "cost_profile": row["cost_profile"],
                "status": row["status"],
            },
        )
        for field in (
            "required_fields",
            "preferred_routes",
            "cost_profile",
            "status",
        ):
            if bucket[field] != row[field]:
                raise G5ExternalSourceCompressionError(
                    f"inconsistent {field} for {lane}|{symbol}"
                )
        bucket["points"].append((event_date, cutoff))

    requests: list[CompressedExternalSourceRequest] = []
    flattened: list[tuple[str, str, str, str]] = []

    for (lane, symbol), bucket in sorted(grouped.items()):
        raw_points = list(bucket["points"])
        points = sorted(set(raw_points))
        if len(points) != len(raw_points):
            raise G5ExternalSourceCompressionError(
                f"duplicate date/cutoff point for {lane}|{symbol}"
            )
        dates = [event_date for event_date, _cutoff in points]
        packed = ";".join(
            f"{event_date}@{cutoff}" for event_date, cutoff in points
        )
        requests.append(
            CompressedExternalSourceRequest(
                request_id=_compressed_request_id(lane, symbol, points),
                lane=lane,
                candidate_symbol=symbol,
                required_date_count=len(points),
                first_event_date=min(dates),
                last_event_date=max(dates),
                request_points=packed,
                required_fields=str(bucket["required_fields"]),
                preferred_routes=str(bucket["preferred_routes"]),
                cost_profile=str(bucket["cost_profile"]),
                status=str(bucket["status"]),
            )
        )
        flattened.extend(
            (lane, event_date, symbol, cutoff)
            for event_date, cutoff in points
        )

    expected_points = {
        (
            row["lane"],
            row["event_date"][:10],
            row["candidate_symbol"].upper(),
            row["latest_acceptable_effective_ts_utc"],
        )
        for row in rows
    }
    if set(flattened) != expected_points:
        raise G5ExternalSourceCompressionError(
            "compressed requests do not preserve the exact external date/cutoff scope"
        )
    if len(flattened) != len(rows):
        raise G5ExternalSourceCompressionError(
            "compressed requests lost or duplicated external source rows"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    all_path = output_dir / "g5_external_source_compressed_requests.csv"
    fields_out = list(CompressedExternalSourceRequest.__dataclass_fields__)
    with all_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields_out)
        writer.writeheader()
        for row in requests:
            writer.writerow(asdict(row))

    lane_counts: dict[str, int] = {}
    lane_input_counts: dict[str, int] = {}
    lane_paths: dict[str, str] = {}
    for lane in sorted({row.lane for row in requests}):
        lane_rows = [row for row in requests if row.lane == lane]
        lane_input = sum(1 for row in rows if row["lane"] == lane)
        path = output_dir / f"g5_external_{lane}_compressed_requests.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields_out)
            writer.writeheader()
            for row in lane_rows:
                writer.writerow(asdict(row))
        lane_counts[lane] = len(lane_rows)
        lane_input_counts[lane] = lane_input
        lane_paths[lane] = str(path)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Compress date-level G5 external metadata acquisition work into one "
            "request per lane and historical symbol while preserving every exact "
            "event date and point-in-time cutoff. Compression changes acquisition "
            "packaging only; no cross-date metadata continuity is assumed."
        ),
        "research_use_only": True,
        "date_level_request_count": len(rows),
        "compressed_lane_symbol_request_count": len(requests),
        "request_reduction_count": len(rows) - len(requests),
        "compression_ratio": round(len(requests) / len(rows), 8),
        "lane_input_counts": lane_input_counts,
        "lane_compressed_counts": lane_counts,
        "exact_request_point_count_reconciled": len(flattened),
        "unique_historical_symbol_count": len(
            {row.candidate_symbol for row in requests}
        ),
        "inputs": {
            "external_request_path": str(external_request_path),
            "external_request_sha256": _sha256(external_request_path),
        },
        "outputs": {
            "all_compressed_requests": str(all_path),
            "lane_compressed_requests": lane_paths,
        },
        "policy": {
            "one_request_per_lane_and_symbol": True,
            "exact_event_dates_and_cutoffs_preserved": True,
            "cross_date_metadata_continuity_assumed": False,
            "compressed_rows_are_g5_evidence": False,
            "authorization_and_source_hash_still_required": True,
            "point_in_time_cutoff_still_required_for_every_date": True,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_external_source_compression_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compress G5 external source requests by lane and symbol while "
            "preserving exact date/cutoff scope."
        )
    )
    parser.add_argument("--external-requests", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        external_request_path=args.external_requests,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
