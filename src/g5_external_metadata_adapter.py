from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1"

LANE_FIELDS = {
    "classification": ("sector", "index_bucket"),
    "ownership": ("institutional_ownership",),
    "analyst": ("analyst_coverage",),
    "borrow": ("borrow_cost",),
}

FIELD_ALIASES = {
    "sector": ("sector", "gsector"),
    "index_bucket": ("index_bucket", "index_membership", "indexmembership"),
    "institutional_ownership": ("institutional_ownership", "io"),
    "analyst_coverage": ("analyst_coverage", "numest"),
    "borrow_cost": ("borrow_cost", "dcbs"),
}

PROHIBITED_SOURCE_COLUMNS = {
    "hacked",
    "actual",
    "soft",
    "earnings_surprise",
    "post_event_return",
    "announcement_reaction",
    "enforcement",
    "prosecution",
    "expected_return",
    "target_price",
    "position_size",
    "order",
}

OUTPUT_FIELDS = (
    "event_date",
    "symbol",
    "effective_ts_utc",
    "sector",
    "index_bucket",
    "institutional_ownership",
    "analyst_coverage",
    "borrow_cost",
    "source_name",
    "authorization_reference",
    "research_use_only",
)


class G5ExternalMetadataError(ValueError):
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
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    return fields, rows


def _first(row: dict[str, str], names: tuple[str, ...]) -> str:
    lower = {str(k).lower(): str(v or "").strip() for k, v in row.items()}
    for name in names:
        value = lower.get(name.lower(), "")
        if value:
            return value
    return ""


def _parse_aware(value: str, *, label: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise G5ExternalMetadataError(f"{label} is blank")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G5ExternalMetadataError(f"{label} is not a valid ISO timestamp") from exc
    if dt.tzinfo is None:
        raise G5ExternalMetadataError(f"{label} must include a timezone")
    return dt.astimezone(timezone.utc)


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_numeric(field: str, raw: str, *, row_no: int) -> str:
    try:
        value = float(raw)
    except ValueError as exc:
        raise G5ExternalMetadataError(
            f"source row {row_no}: {field} must be numeric"
        ) from exc
    if not math.isfinite(value):
        raise G5ExternalMetadataError(
            f"source row {row_no}: {field} must be finite"
        )
    if value < 0:
        raise G5ExternalMetadataError(
            f"source row {row_no}: {field} must be non-negative"
        )
    return format(value, ".15g")


def load_candidates(path: Path) -> dict[tuple[str, str], datetime]:
    fields, rows = _read_csv(path)
    required = {"event_date", "candidate_symbol", "latest_acceptable_effective_ts_utc"}
    missing = required.difference(fields)
    if missing:
        raise G5ExternalMetadataError(
            f"candidate file missing columns: {sorted(missing)}"
        )

    out: dict[tuple[str, str], datetime] = {}
    for row_no, row in enumerate(rows, 2):
        event_date = row["event_date"].strip()
        symbol = row["candidate_symbol"].strip().upper()
        if not event_date or not symbol:
            raise G5ExternalMetadataError(
                f"candidate row {row_no}: event_date and candidate_symbol are required"
            )
        cutoff = _parse_aware(
            row["latest_acceptable_effective_ts_utc"],
            label=f"candidate row {row_no} cutoff",
        )
        key = (event_date, symbol)
        if key in out:
            raise G5ExternalMetadataError(
                f"duplicate candidate symbol-date: {event_date}|{symbol}"
            )
        out[key] = cutoff
    return out


def normalize(
    *,
    lane: str,
    candidate_path: Path,
    source_path: Path,
    expected_source_sha256: str,
    authorization_reference: str,
    source_name: str,
) -> tuple[list[dict[str, str]], dict]:
    lane = lane.strip().lower()
    if lane not in LANE_FIELDS:
        raise G5ExternalMetadataError(
            f"lane must be one of {sorted(LANE_FIELDS)}"
        )
    authorization_reference = authorization_reference.strip()
    source_name = source_name.strip()
    if not authorization_reference:
        raise G5ExternalMetadataError("authorization_reference must be nonblank")
    if not source_name:
        raise G5ExternalMetadataError("source_name must be nonblank")

    expected = expected_source_sha256.strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise G5ExternalMetadataError(
            "expected_source_sha256 must be a 64-character SHA-256"
        )
    actual = _sha256(source_path)
    if actual != expected:
        raise G5ExternalMetadataError("source SHA-256 mismatch")

    candidate_cutoffs = load_candidates(candidate_path)
    source_fields, source_rows = _read_csv(source_path)
    lower_fields = {field.lower() for field in source_fields}
    prohibited = sorted(PROHIBITED_SOURCE_COLUMNS.intersection(lower_fields))
    if prohibited:
        raise G5ExternalMetadataError(
            f"source contains prohibited retrospective/post-event columns: {prohibited}"
        )

    required_fields = LANE_FIELDS[lane]
    normalized: list[dict[str, str]] = []
    seen_values: dict[tuple[str, str, str, str], str] = {}
    accepted_field_counts: dict[str, int] = defaultdict(int)

    for row_no, row in enumerate(source_rows, 2):
        event_date = _first(row, ("event_date", "trade_date", "date"))
        symbol = _first(row, ("symbol", "historical_symbol", "ticker")).upper()
        raw_ts = _first(row, ("effective_ts_utc", "available_at", "effective_timestamp"))
        if not event_date or not symbol or not raw_ts:
            raise G5ExternalMetadataError(
                f"source row {row_no}: event_date, symbol, and effective timestamp are required"
            )
        event_date = event_date[:10]
        key = (event_date, symbol)
        cutoff = candidate_cutoffs.get(key)
        if cutoff is None:
            raise G5ExternalMetadataError(
                f"source row {row_no}: symbol-date is not in the primary candidate queue: {event_date}|{symbol}"
            )
        effective = _parse_aware(raw_ts, label=f"source row {row_no} effective_ts_utc")
        if effective > cutoff:
            raise G5ExternalMetadataError(
                f"source row {row_no}: effective timestamp is after the event cutoff"
            )

        out = {field: "" for field in OUTPUT_FIELDS}
        out["event_date"] = event_date
        out["symbol"] = symbol
        out["effective_ts_utc"] = _fmt_utc(effective)
        out["source_name"] = source_name
        out["authorization_reference"] = authorization_reference
        out["research_use_only"] = "1"

        populated = 0
        for field in required_fields:
            raw = _first(row, FIELD_ALIASES[field])
            if not raw:
                continue
            if field in {"institutional_ownership", "analyst_coverage", "borrow_cost"}:
                value = _validate_numeric(field, raw, row_no=row_no)
            else:
                value = raw.strip()
            conflict_key = (
                event_date,
                symbol,
                out["effective_ts_utc"],
                field,
            )
            previous = seen_values.get(conflict_key)
            if previous is not None and previous != value:
                raise G5ExternalMetadataError(
                    f"source row {row_no}: conflicting {field} at identical effective timestamp"
                )
            seen_values[conflict_key] = value
            out[field] = value
            accepted_field_counts[field] += 1
            populated += 1

        if populated == 0:
            raise G5ExternalMetadataError(
                f"source row {row_no}: no usable fields for lane {lane}"
            )
        normalized.append(out)

    normalized.sort(
        key=lambda row: (
            row["event_date"],
            row["symbol"],
            row["effective_ts_utc"],
        )
    )
    covered_candidates = {
        (row["event_date"], row["symbol"])
        for row in normalized
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Normalize explicitly authorized, pre-cutoff external G5 metadata into "
            "control-universe rows that can be fused by the resolver. Normalization "
            "does not itself make any row genuine G5 evidence."
        ),
        "research_use_only": True,
        "lane": lane,
        "source_name": source_name,
        "authorization_reference_present": True,
        "source_path": str(source_path),
        "source_sha256": actual,
        "candidate_path": str(candidate_path),
        "candidate_sha256": _sha256(candidate_path),
        "input_row_count": len(source_rows),
        "normalized_row_count": len(normalized),
        "covered_candidate_symbol_dates": len(covered_candidates),
        "primary_candidate_symbol_date_count": len(candidate_cutoffs),
        "accepted_field_counts": dict(sorted(accepted_field_counts.items())),
        "point_in_time_cutoff_enforced": True,
        "unknown_candidate_rows_allowed": False,
        "retrospective_or_post_event_columns_allowed": False,
        "g5_dates_resolved_change": 0,
        "eligible_g5_evidence": False,
        "release_claimed": False,
    }
    return normalized, summary


def write_outputs(
    rows: list[dict[str, str]],
    summary: dict,
    *,
    output_path: Path,
    summary_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(OUTPUT_FIELDS))
        writer.writeheader()
        writer.writerows(rows)
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize authorized point-in-time external metadata for G5 controls."
    )
    parser.add_argument("--lane", choices=sorted(LANE_FIELDS), required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    rows, summary = normalize(
        lane=args.lane,
        candidate_path=args.candidates,
        source_path=args.source,
        expected_source_sha256=args.expected_source_sha256,
        authorization_reference=args.authorization_reference,
        source_name=args.source_name,
    )
    write_outputs(
        rows,
        summary,
        output_path=args.output,
        summary_path=args.summary,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
