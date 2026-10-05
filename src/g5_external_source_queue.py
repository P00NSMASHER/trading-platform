from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = "1"

LANES = {
    "classification": {
        "fields": ("sector", "index_bucket"),
        "preferred_routes": (
            "SEC_SIC_OR_AUTHORIZED_HISTORICAL_CLASSIFICATION",
            "AUTHORIZED_HISTORICAL_INDEX_MEMBERSHIP",
        ),
        "cost_profile": "MIXED_PUBLIC_AND_AUTHORIZED",
    },
    "ownership": {
        "fields": ("institutional_ownership",),
        "preferred_routes": (
            "SEC_13F_OR_AUTHORIZED_13F_REFERENCE",
        ),
        "cost_profile": "PUBLIC_OR_AUTHORIZED",
    },
    "analyst": {
        "fields": ("analyst_coverage",),
        "preferred_routes": (
            "IBES_OR_AUTHORIZED_POINT_IN_TIME_ANALYST_SOURCE",
        ),
        "cost_profile": "AUTHORIZED_LIKELY",
    },
    "borrow": {
        "fields": ("borrow_cost",),
        "preferred_routes": (
            "MARKIT_OR_AUTHORIZED_SECURITIES_LENDING_SOURCE",
        ),
        "cost_profile": "AUTHORIZED_LIKELY",
    },
}


@dataclass(frozen=True)
class ExternalSourceRequest:
    request_id: str
    lane: str
    event_date: str
    candidate_symbol: str
    latest_acceptable_effective_ts_utc: str
    required_fields: str
    preferred_routes: str
    cost_profile: str
    status: str = "SOURCE_REQUIRED"
    eligible_g5_evidence: int = 0
    research_use_only: int = 1


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
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    return fields, rows


def _request_id(lane: str, event_date: str, symbol: str) -> str:
    raw = f"{lane}|{event_date}|{symbol}".encode("utf-8")
    return "G5EXT-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def build(*, candidate_path: Path, output_dir: Path) -> dict:
    fields, rows = _read_csv(candidate_path)
    required = {
        "event_date",
        "candidate_symbol",
        "latest_acceptable_effective_ts_utc",
    }
    missing = required.difference(fields)
    if missing:
        raise ValueError(f"candidate file missing columns: {sorted(missing)}")
    if not rows:
        raise ValueError("candidate file is empty")

    requests: list[ExternalSourceRequest] = []
    seen_candidates: set[tuple[str, str]] = set()
    for row_no, row in enumerate(rows, 2):
        event_date = row["event_date"][:10]
        symbol = row["candidate_symbol"].upper()
        cutoff = row["latest_acceptable_effective_ts_utc"]
        if not event_date or not symbol or not cutoff:
            raise ValueError(
                f"candidate row {row_no}: event_date, candidate_symbol, and cutoff are required"
            )
        key = (event_date, symbol)
        if key in seen_candidates:
            raise ValueError(f"duplicate candidate symbol-date: {event_date}|{symbol}")
        seen_candidates.add(key)

        for lane, spec in LANES.items():
            requests.append(
                ExternalSourceRequest(
                    request_id=_request_id(lane, event_date, symbol),
                    lane=lane,
                    event_date=event_date,
                    candidate_symbol=symbol,
                    latest_acceptable_effective_ts_utc=cutoff,
                    required_fields=";".join(spec["fields"]),
                    preferred_routes=";".join(spec["preferred_routes"]),
                    cost_profile=spec["cost_profile"],
                )
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    all_path = output_dir / "g5_external_source_requests.csv"
    fields_out = list(ExternalSourceRequest.__dataclass_fields__)
    with all_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields_out)
        writer.writeheader()
        for row in requests:
            writer.writerow(asdict(row))

    lane_counts = {}
    lane_paths = {}
    for lane in LANES:
        lane_rows = [row for row in requests if row.lane == lane]
        lane_path = output_dir / f"g5_external_{lane}_requests.csv"
        with lane_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields_out)
            writer.writeheader()
            for row in lane_rows:
                writer.writerow(asdict(row))
        lane_counts[lane] = len(lane_rows)
        lane_paths[lane] = str(lane_path)

    unique_dates = {row.event_date for row in requests}
    candidate_count = len(seen_candidates)
    field_requirement_count = candidate_count * sum(
        len(spec["fields"]) for spec in LANES.values()
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Deterministic source-acquisition queue for the external point-in-time "
            "fields required by the G5 primary control candidates."
        ),
        "research_use_only": True,
        "candidate_symbol_date_count": candidate_count,
        "event_date_count": len(unique_dates),
        "lane_request_count": len(requests),
        "external_field_requirement_count": field_requirement_count,
        "lane_counts": lane_counts,
        "lane_definitions": LANES,
        "inputs": {
            "candidate_path": str(candidate_path),
            "candidate_sha256": _sha256(candidate_path),
        },
        "outputs": {
            "all_requests": str(all_path),
            "lane_requests": lane_paths,
        },
        "policy": {
            "request_rows_are_g5_evidence": False,
            "authorization_and_source_hash_required_before_intake": True,
            "effective_timestamp_must_not_exceed_candidate_cutoff": True,
            "retrospective_or_post_event_fields_may_not_close_g5": True,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_external_source_request_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build source-specific G5 external metadata request queues."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        candidate_path=args.candidates,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
