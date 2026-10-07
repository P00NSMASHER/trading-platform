from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class CusipRequest:
    request_id: str
    target_kind: str
    historical_symbol: str
    required_event_dates: str
    event_count: int
    earliest_event_date: str
    latest_event_date: str
    required_evidence: str = (
        "HISTORICAL_SYMBOL;CUSIP9;VALID_FROM;VALID_THROUGH;"
        "SOURCE_REFERENCE;EVIDENCE_EFFECTIVE_AT"
    )
    preferred_routes: str = (
        "SEC_ARCHIVAL_13F_OR_FILING_EXHIBIT;"
        "AUTHORIZED_HISTORICAL_SECURITY_MASTER"
    )
    status: str = "HISTORICAL_CUSIP_EVIDENCE_REQUIRED"
    research_use_only: int = 1


class G5HistoricalCusipError(ValueError):
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


def _normalize_cusip(value: str) -> str:
    raw = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if len(raw) != 9:
        raise G5HistoricalCusipError(
            f"CUSIP must normalize to exactly 9 alphanumeric characters: {value!r}"
        )
    return raw


def _request_id(target_kind: str, symbol: str, dates: list[str]) -> str:
    raw = f"{target_kind}|{symbol}|{';'.join(dates)}".encode("utf-8")
    return "G5CUSIP-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def build(
    *,
    control_targets_path: Path,
    treated_targets_path: Path,
    output_dir: Path,
) -> dict:
    grouped: dict[tuple[str, str], set[str]] = {}

    for target_kind, path in (
        ("control", control_targets_path),
        ("treated", treated_targets_path),
    ):
        fields, rows = _read_csv(path)
        symbol_field = (
            "candidate_symbol"
            if "candidate_symbol" in fields
            else "historical_symbol"
            if "historical_symbol" in fields
            else "symbol"
            if "symbol" in fields
            else ""
        )
        date_field = (
            "event_date"
            if "event_date" in fields
            else "trade_date"
            if "trade_date" in fields
            else ""
        )
        if not symbol_field or not date_field:
            raise G5HistoricalCusipError(
                f"{target_kind} target file lacks symbol/date columns"
            )
        for row_no, row in enumerate(rows, 2):
            symbol = row[symbol_field].upper()
            event_date = row[date_field][:10]
            if not symbol or not event_date:
                raise G5HistoricalCusipError(
                    f"{target_kind} row {row_no}: symbol/date required"
                )
            grouped.setdefault((target_kind, symbol), set()).add(event_date)

    requests = []
    for (target_kind, symbol), date_set in sorted(grouped.items()):
        dates = sorted(date_set)
        requests.append(
            CusipRequest(
                request_id=_request_id(target_kind, symbol, dates),
                target_kind=target_kind,
                historical_symbol=symbol,
                required_event_dates=";".join(dates),
                event_count=len(dates),
                earliest_event_date=dates[0],
                latest_event_date=dates[-1],
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    queue_path = output_dir / "g5_historical_cusip_acquisition_queue.csv"
    with queue_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(CusipRequest.__dataclass_fields__)
        )
        writer.writeheader()
        for row in requests:
            writer.writerow(asdict(row))

    by_kind = {
        kind: sum(row.target_kind == kind for row in requests)
        for kind in ("control", "treated")
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "research_use_only": True,
        "request_count": len(requests),
        "request_count_by_target_kind": by_kind,
        "unique_symbol_count": len({row.historical_symbol for row in requests}),
        "inputs": {
            "control_targets": {
                "path": str(control_targets_path),
                "sha256": _sha256(control_targets_path),
            },
            "treated_targets": {
                "path": str(treated_targets_path),
                "sha256": _sha256(treated_targets_path),
            },
        },
        "outputs": {"acquisition_queue": str(queue_path)},
        "policy": {
            "issuer_name_fuzzy_match_may_close_request": False,
            "current_ticker_cusip_may_close_request": False,
            "exact_historical_cusip9_required": True,
            "all_required_event_dates_preserved": True,
            "queue_rows_are_g5_evidence": False,
        },
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_historical_cusip_acquisition_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def stage_reviewed(
    *,
    acquisition_queue_path: Path,
    reviewed_evidence_path: Path,
    output_path: Path,
) -> dict:
    _qfields, queue = _read_csv(acquisition_queue_path)
    required_dates: dict[tuple[str, str], set[str]] = {}
    for row in queue:
        key = (row["target_kind"], row["historical_symbol"].upper())
        required_dates[key] = {
            item for item in row["required_event_dates"].split(";") if item
        }

    fields, rows = _read_csv(reviewed_evidence_path)
    required = {
        "target_kind", "historical_symbol", "cusip", "valid_from",
        "valid_through", "source_reference", "evidence_effective_at",
        "review_status", "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5HistoricalCusipError(
            f"reviewed evidence missing columns: {sorted(missing)}"
        )

    staged = []
    seen = set()
    for row_no, row in enumerate(rows, 2):
        key = (row["target_kind"].lower(), row["historical_symbol"].upper())
        if key not in required_dates:
            raise G5HistoricalCusipError(
                f"reviewed row {row_no}: target is not in acquisition queue"
            )
        if key in seen:
            raise G5HistoricalCusipError(
                f"reviewed row {row_no}: duplicate reviewed target"
            )
        seen.add(key)
        if row["review_status"] != "EXPLICIT_HISTORICAL_CUSIP_VERIFIED":
            raise G5HistoricalCusipError(
                f"reviewed row {row_no}: review_status is not closing-authorized"
            )
        if row["research_use_only"] != "1":
            raise G5HistoricalCusipError(
                f"reviewed row {row_no}: research_use_only must equal 1"
            )
        valid_from = row["valid_from"][:10]
        valid_through = row["valid_through"][:10]
        if not valid_from or not valid_through or valid_through < valid_from:
            raise G5HistoricalCusipError(
                f"reviewed row {row_no}: invalid validity interval"
            )
        if any(
            d < valid_from or d > valid_through
            for d in required_dates[key]
        ):
            raise G5HistoricalCusipError(
                f"reviewed row {row_no}: validity interval misses required dates"
            )
        if not row["source_reference"] or not row["evidence_effective_at"]:
            raise G5HistoricalCusipError(
                f"reviewed row {row_no}: source/effective evidence required"
            )
        staged.append(
            {
                "target_kind": key[0],
                "historical_symbol": key[1],
                "cusip": _normalize_cusip(row["cusip"]),
                "valid_from": valid_from,
                "valid_through": valid_through,
                "source_reference": row["source_reference"],
                "evidence_effective_at": row["evidence_effective_at"],
                "review_status": row["review_status"],
                "research_use_only": "1",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "target_kind", "historical_symbol", "cusip", "valid_from",
        "valid_through", "source_reference", "evidence_effective_at",
        "review_status", "research_use_only",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(
            staged,
            key=lambda row: (row["target_kind"], row["historical_symbol"]),
        ))

    return {
        "schema_version": SCHEMA_VERSION,
        "queue_request_count": len(required_dates),
        "staged_verified_request_count": len(staged),
        "remaining_request_count": len(required_dates) - len(staged),
        "output_path": str(output_path),
        "output_sha256": _sha256(output_path),
        "policy": {
            "explicit_historical_review_required": True,
            "validity_must_cover_all_required_event_dates": True,
            "staging_changes_canonical_g5_readiness": False,
        },
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or stage the G5 historical CUSIP acquisition lane."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    queue = sub.add_parser("queue")
    queue.add_argument("--control-targets", type=Path, required=True)
    queue.add_argument("--treated-targets", type=Path, required=True)
    queue.add_argument("--output-dir", type=Path, required=True)

    stage = sub.add_parser("stage-reviewed")
    stage.add_argument("--acquisition-queue", type=Path, required=True)
    stage.add_argument("--reviewed-evidence", type=Path, required=True)
    stage.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "queue":
        result = build(
            control_targets_path=args.control_targets,
            treated_targets_path=args.treated_targets,
            output_dir=args.output_dir,
        )
    else:
        result = stage_reviewed(
            acquisition_queue_path=args.acquisition_queue,
            reviewed_evidence_path=args.reviewed_evidence,
            output_path=args.output,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
