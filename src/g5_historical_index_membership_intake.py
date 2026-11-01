from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "1"
ALLOWED_BUCKETS = {"SP500", "SP400", "SP600", "NONE"}


class G5IndexMembershipError(ValueError):
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


def _parse_date(value: str, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError as exc:
        raise G5IndexMembershipError(f"{label} must be YYYY-MM-DD") from exc


def _parse_ts(value: str, *, label: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise G5IndexMembershipError(f"{label} invalid timestamp") from exc
    if dt.tzinfo is None:
        raise G5IndexMembershipError(f"{label} must include timezone")
    return dt.astimezone(timezone.utc)


def build(
    *,
    targets_path: Path,
    membership_intervals_path: Path,
    output_path: Path,
) -> dict:
    target_fields, targets = _read_csv(targets_path)
    symbol_field = (
        "candidate_symbol"
        if "candidate_symbol" in target_fields
        else "historical_symbol"
        if "historical_symbol" in target_fields
        else "symbol"
        if "symbol" in target_fields
        else ""
    )
    if not symbol_field or "event_date" not in target_fields:
        raise G5IndexMembershipError("target file lacks symbol/event_date")
    cutoff_field = "latest_acceptable_effective_ts_utc"
    if cutoff_field not in target_fields:
        raise G5IndexMembershipError("target file lacks cutoff timestamp")

    fields, intervals = _read_csv(membership_intervals_path)
    required = {
        "historical_symbol", "index_bucket", "valid_from", "valid_through",
        "evidence_effective_at", "source_reference", "authorization_reference",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5IndexMembershipError(
            f"membership source missing columns: {sorted(missing)}"
        )

    by_symbol: dict[str, list[dict[str, object]]] = {}
    for row_no, row in enumerate(intervals, 2):
        symbol = row["historical_symbol"].upper()
        bucket = row["index_bucket"].upper()
        if bucket not in ALLOWED_BUCKETS:
            raise G5IndexMembershipError(
                f"membership row {row_no}: unsupported bucket {bucket}"
            )
        if row["research_use_only"] != "1":
            raise G5IndexMembershipError(
                f"membership row {row_no}: research_use_only must equal 1"
            )
        valid_from = _parse_date(
            row["valid_from"], label=f"membership row {row_no} valid_from"
        )
        valid_through = _parse_date(
            row["valid_through"], label=f"membership row {row_no} valid_through"
        )
        if valid_through < valid_from:
            raise G5IndexMembershipError(
                f"membership row {row_no}: invalid interval"
            )
        effective = _parse_ts(
            row["evidence_effective_at"],
            label=f"membership row {row_no} evidence_effective_at",
        )
        if not row["source_reference"] or not row["authorization_reference"]:
            raise G5IndexMembershipError(
                f"membership row {row_no}: source/authorization required"
            )
        by_symbol.setdefault(symbol, []).append(
            {
                "bucket": bucket,
                "valid_from": valid_from,
                "valid_through": valid_through,
                "effective": effective,
                "source_reference": row["source_reference"],
                "authorization_reference": row["authorization_reference"],
            }
        )

    output = []
    gaps = []
    for row_no, row in enumerate(targets, 2):
        symbol = row[symbol_field].upper()
        event_date = _parse_date(
            row["event_date"], label=f"target row {row_no} event_date"
        )
        cutoff = _parse_ts(
            row[cutoff_field], label=f"target row {row_no} cutoff"
        )
        matches = [
            item
            for item in by_symbol.get(symbol, [])
            if item["valid_from"] <= event_date <= item["valid_through"]
            and item["effective"] <= cutoff
        ]
        buckets = {str(item["bucket"]) for item in matches}
        if len(buckets) > 1:
            raise G5IndexMembershipError(
                f"conflicting index buckets for {symbol}|{event_date}: {sorted(buckets)}"
            )
        if not matches:
            gaps.append((event_date.isoformat(), symbol))
            continue
        chosen = max(matches, key=lambda item: item["effective"])
        output.append(
            {
                "event_date": event_date.isoformat(),
                "symbol": symbol,
                "effective_ts_utc": chosen["effective"].isoformat(
                    timespec="seconds"
                ).replace("+00:00", "Z"),
                "index_bucket": chosen["bucket"],
                "source_reference": chosen["source_reference"],
                "authorization_reference": chosen["authorization_reference"],
                "research_use_only": "1",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "event_date", "symbol", "effective_ts_utc", "index_bucket",
                "source_reference", "authorization_reference",
                "research_use_only",
            ],
        )
        writer.writeheader()
        writer.writerows(output)

    return {
        "schema_version": SCHEMA_VERSION,
        "target_count": len(targets),
        "resolved_index_bucket_count": len(output),
        "gap_count": len(gaps),
        "output_path": str(output_path),
        "output_sha256": _sha256(output_path),
        "policy": {
            "point_in_time_interval_required": True,
            "evidence_must_be_available_before_cutoff": True,
            "conflicting_memberships_fail_closed": True,
            "third_party_reconstruction_is_primary_evidence": False,
            "output_changes_canonical_g5_readiness": False,
        },
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize point-in-time historical index membership for G5."
    )
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--membership-intervals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        targets_path=args.targets,
        membership_intervals_path=args.membership_intervals,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
