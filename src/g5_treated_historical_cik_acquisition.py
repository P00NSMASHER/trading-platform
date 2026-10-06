from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class CikAcquisitionRequest:
    request_id: str
    historical_symbol: str
    required_event_dates: str
    event_count: int
    earliest_event_date: str
    latest_event_date: str
    preferred_routes: str = (
        "SEC_ARCHIVAL_FILINGS;SEC_COMPANY_SEARCH;"
        "EXPLICIT_AUTHORIZED_HISTORICAL_IDENTIFIER_REFERENCE"
    )
    required_evidence: str = (
        "HISTORICAL_SYMBOL;CIK;VALID_FROM;VALID_THROUGH;"
        "SOURCE_REFERENCE;EVIDENCE_EFFECTIVE_AT"
    )
    status: str = "HISTORICAL_CIK_EVIDENCE_REQUIRED"
    research_use_only: int = 1


@dataclass(frozen=True)
class ReviewedCikRow:
    historical_symbol: str
    cik: str
    valid_from: str
    valid_through: str
    source_reference: str
    evidence_effective_at: str
    review_status: str
    research_use_only: int = 1


class G5HistoricalCikAcquisitionError(ValueError):
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


def _request_id(symbol: str, dates: list[str]) -> str:
    raw = f"{symbol}|{';'.join(dates)}".encode("utf-8")
    return "G5CIK-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def _normalize_cik(value: str) -> str:
    raw = str(value or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    if not raw.isdigit():
        raise G5HistoricalCikAcquisitionError(
            f"CIK must be numeric: {value!r}"
        )
    return raw.zfill(10)


def build_queue(
    *,
    events_path: Path,
    historical_cik_map_path: Path,
    output_dir: Path,
) -> dict:
    event_fields, events = _read_csv(events_path)
    required_events = {"historical_symbol", "first_documented_illicit_trade_ts"}
    missing = required_events.difference(event_fields)
    if missing:
        raise G5HistoricalCikAcquisitionError(
            f"events missing columns: {sorted(missing)}"
        )

    map_fields, map_rows = _read_csv(historical_cik_map_path)
    required_map = {"historical_symbol", "cik"}
    missing = required_map.difference(map_fields)
    if missing:
        raise G5HistoricalCikAcquisitionError(
            f"historical CIK map missing columns: {sorted(missing)}"
        )
    mapped = {row["historical_symbol"].upper() for row in map_rows if row["cik"]}

    dates_by_symbol: dict[str, set[str]] = {}
    total_events = 0
    mapped_events = 0
    for row_no, row in enumerate(events, 2):
        symbol = row["historical_symbol"].upper()
        event_date = row["first_documented_illicit_trade_ts"][:10]
        if not symbol or not event_date:
            raise G5HistoricalCikAcquisitionError(
                f"event row {row_no}: symbol/date required"
            )
        total_events += 1
        if symbol in mapped:
            mapped_events += 1
            continue
        dates_by_symbol.setdefault(symbol, set()).add(event_date)

    requests = []
    for symbol, date_set in sorted(dates_by_symbol.items()):
        dates = sorted(date_set)
        requests.append(
            CikAcquisitionRequest(
                request_id=_request_id(symbol, dates),
                historical_symbol=symbol,
                required_event_dates=";".join(dates),
                event_count=sum(
                    1
                    for row in events
                    if row["historical_symbol"].upper() == symbol
                ),
                earliest_event_date=dates[0],
                latest_event_date=dates[-1],
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    queue_path = output_dir / "g5_treated_historical_cik_acquisition_queue.csv"
    with queue_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(CikAcquisitionRequest.__dataclass_fields__)
        )
        writer.writeheader()
        for row in requests:
            writer.writerow(asdict(row))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Compress treated-event historical CIK gaps into one acquisition "
            "request per historical symbol while preserving every exact event date."
        ),
        "research_use_only": True,
        "treated_event_count": total_events,
        "already_mapped_event_count": mapped_events,
        "missing_cik_event_count": total_events - mapped_events,
        "missing_cik_unique_symbol_count": len(requests),
        "request_count": len(requests),
        "inputs": {
            "events": {"path": str(events_path), "sha256": _sha256(events_path)},
            "historical_cik_map": {
                "path": str(historical_cik_map_path),
                "sha256": _sha256(historical_cik_map_path),
            },
        },
        "outputs": {"acquisition_queue": str(queue_path)},
        "policy": {
            "current_ticker_cik_may_close_request": False,
            "historical_symbol_specific_evidence_required": True,
            "all_required_event_dates_preserved": True,
            "queue_rows_are_g5_evidence": False,
        },
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_treated_historical_cik_acquisition_summary.json").write_text(
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
    queue_fields, queue_rows = _read_csv(acquisition_queue_path)
    if not {"historical_symbol", "required_event_dates"}.issubset(queue_fields):
        raise G5HistoricalCikAcquisitionError("invalid acquisition queue schema")
    required_symbols = {
        row["historical_symbol"].upper(): set(
            x for x in row["required_event_dates"].split(";") if x
        )
        for row in queue_rows
    }

    fields, rows = _read_csv(reviewed_evidence_path)
    required = {
        "historical_symbol",
        "cik",
        "valid_from",
        "valid_through",
        "source_reference",
        "evidence_effective_at",
        "review_status",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5HistoricalCikAcquisitionError(
            f"reviewed evidence missing columns: {sorted(missing)}"
        )

    staged: list[ReviewedCikRow] = []
    seen: set[str] = set()
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        if symbol not in required_symbols:
            raise G5HistoricalCikAcquisitionError(
                f"reviewed row {row_no}: symbol {symbol} is not in acquisition queue"
            )
        if symbol in seen:
            raise G5HistoricalCikAcquisitionError(
                f"reviewed row {row_no}: duplicate reviewed symbol {symbol}"
            )
        seen.add(symbol)
        if row["research_use_only"] != "1":
            raise G5HistoricalCikAcquisitionError(
                f"reviewed row {row_no}: research_use_only must equal 1"
            )
        if row["review_status"] != "EXPLICIT_HISTORICAL_CIK_VERIFIED":
            raise G5HistoricalCikAcquisitionError(
                f"reviewed row {row_no}: review_status is not closing-authorized"
            )
        if not row["source_reference"] or not row["evidence_effective_at"]:
            raise G5HistoricalCikAcquisitionError(
                f"reviewed row {row_no}: source/effective evidence required"
            )
        valid_from = row["valid_from"][:10]
        valid_through = row["valid_through"][:10]
        if not valid_from or not valid_through or valid_through < valid_from:
            raise G5HistoricalCikAcquisitionError(
                f"reviewed row {row_no}: valid interval invalid"
            )
        required_dates = required_symbols[symbol]
        if any(d < valid_from or d > valid_through for d in required_dates):
            raise G5HistoricalCikAcquisitionError(
                f"reviewed row {row_no}: validity interval does not cover every required event date"
            )

        staged.append(
            ReviewedCikRow(
                historical_symbol=symbol,
                cik=_normalize_cik(row["cik"]),
                valid_from=valid_from,
                valid_through=valid_through,
                source_reference=row["source_reference"],
                evidence_effective_at=row["evidence_effective_at"],
                review_status=row["review_status"],
            )
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(ReviewedCikRow.__dataclass_fields__)
        )
        writer.writeheader()
        for row in sorted(staged, key=lambda item: item.historical_symbol):
            writer.writerow(asdict(row))

    return {
        "schema_version": SCHEMA_VERSION,
        "research_use_only": True,
        "acquisition_symbol_count": len(required_symbols),
        "reviewed_input_row_count": len(rows),
        "staged_verified_symbol_count": len(staged),
        "remaining_symbol_count": len(required_symbols) - len(staged),
        "output_path": str(output_path),
        "output_sha256": _sha256(output_path),
        "policy": {
            "current_ticker_lookup_is_sufficient_evidence": False,
            "explicit_historical_review_required": True,
            "validity_must_cover_all_required_event_dates": True,
            "staging_changes_canonical_g5_readiness": False,
        },
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }



def merge_reviewed_map(
    *,
    base_map_path: Path,
    staged_reviewed_path: Path,
    output_path: Path,
) -> dict:
    base_fields, base_rows = _read_csv(base_map_path)
    if not {"historical_symbol", "cik"}.issubset(base_fields):
        raise G5HistoricalCikAcquisitionError("invalid base historical CIK map")

    staged_fields, staged_rows = _read_csv(staged_reviewed_path)
    if not {"historical_symbol", "cik"}.issubset(staged_fields):
        raise G5HistoricalCikAcquisitionError("invalid staged reviewed CIK map")

    merged: dict[str, dict[str, str]] = {}
    for row_no, row in enumerate(base_rows, 2):
        symbol = row["historical_symbol"].upper()
        cik_value = _normalize_cik(row["cik"])
        if symbol in merged and merged[symbol]["cik"] != cik_value:
            raise G5HistoricalCikAcquisitionError(
                f"base map row {row_no}: conflicting CIK for {symbol}"
            )
        merged[symbol] = {
            "historical_symbol": symbol,
            "cik": cik_value,
            "notes": row.get("notes", ""),
        }

    added = 0
    reused = 0
    for row_no, row in enumerate(staged_rows, 2):
        symbol = row["historical_symbol"].upper()
        cik_value = _normalize_cik(row["cik"])
        prior = merged.get(symbol)
        if prior is not None:
            if prior["cik"] != cik_value:
                raise G5HistoricalCikAcquisitionError(
                    f"staged row {row_no}: conflicts with existing CIK for {symbol}"
                )
            reused += 1
            continue
        merged[symbol] = {
            "historical_symbol": symbol,
            "cik": cik_value,
            "notes": (
                "G5 reviewed historical CIK evidence: "
                + row.get("source_reference", "")
            ),
        }
        added += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["historical_symbol", "cik", "notes"]
        )
        writer.writeheader()
        for symbol in sorted(merged):
            writer.writerow(merged[symbol])

    return {
        "schema_version": SCHEMA_VERSION,
        "base_symbol_count": len({row["historical_symbol"].upper() for row in base_rows}),
        "staged_input_count": len(staged_rows),
        "added_symbol_count": added,
        "already_present_same_cik_count": reused,
        "merged_symbol_count": len(merged),
        "output_path": str(output_path),
        "output_sha256": _sha256(output_path),
        "policy": {
            "existing_conflicting_cik_may_be_overwritten": False,
            "reviewed_rows_only": True,
        },
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or stage the treated historical-CIK acquisition lane."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    queue = sub.add_parser("queue")
    queue.add_argument("--events", type=Path, required=True)
    queue.add_argument("--historical-cik-map", type=Path, required=True)
    queue.add_argument("--output-dir", type=Path, required=True)

    stage = sub.add_parser("stage-reviewed")
    stage.add_argument("--acquisition-queue", type=Path, required=True)
    stage.add_argument("--reviewed-evidence", type=Path, required=True)
    stage.add_argument("--output", type=Path, required=True)

    merge = sub.add_parser("merge-reviewed")
    merge.add_argument("--base-map", type=Path, required=True)
    merge.add_argument("--staged-reviewed", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "queue":
        result = build_queue(
            events_path=args.events,
            historical_cik_map_path=args.historical_cik_map,
            output_dir=args.output_dir,
        )
    elif args.command == "stage-reviewed":
        result = stage_reviewed(
            acquisition_queue_path=args.acquisition_queue,
            reviewed_evidence_path=args.reviewed_evidence,
            output_path=args.output,
        )
    else:
        result = merge_reviewed_map(
            base_map_path=args.base_map,
            staged_reviewed_path=args.staged_reviewed,
            output_path=args.output,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
