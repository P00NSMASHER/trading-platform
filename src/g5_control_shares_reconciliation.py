from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "1"
NY = ZoneInfo("America/New_York")
ACQUISITION_ROUTE = "PUBLIC_SEC_XBRL_OR_AUTHORIZED_EXCHANGE_REFERENCE"


class G5ControlSharesReconciliationError(ValueError):
    pass


@dataclass(frozen=True)
class ReusedSharesResolution:
    historical_symbol: str
    trade_date: str
    latest_acceptable_available_at_utc: str
    shares_outstanding: str
    available_at: str
    source_reference: str
    source_tag: str
    resolution_status: str = "REUSE_CANONICAL_G4_RESOLUTION"
    research_use_only: int = 1


@dataclass(frozen=True)
class SharesAcquisitionRequest:
    historical_symbol: str
    trade_date: str
    latest_acceptable_available_at_utc: str
    gap_reason: str
    existing_resolution_status: str
    existing_available_at: str
    preferred_route: str = ACQUISITION_ROUTE
    required_fields: str = (
        "historical_symbol;trade_date;fact_date;available_at;"
        "shares_outstanding;source_reference"
    )
    max_fact_staleness_days: int = 130
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


def _parse_date(value: str, *, label: str) -> str:
    raw = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise G5ControlSharesReconciliationError(
            f"{label} must be a valid YYYY-MM-DD date"
        ) from exc


def _parse_ts(value: str, *, label: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise G5ControlSharesReconciliationError(f"{label} is blank")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G5ControlSharesReconciliationError(
            f"{label} must be a valid ISO timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise G5ControlSharesReconciliationError(
            f"{label} must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _parse_local_minute(value: str, *, label: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.strptime(raw, "%H:%M")
    except ValueError as exc:
        raise G5ControlSharesReconciliationError(
            f"{label} must be HH:MM"
        ) from exc
    return parsed.strftime("%H:%M")


def _shares_cutoff(row: dict[str, str], *, row_no: int) -> datetime:
    trade_date = _parse_date(
        row.get("trade_date", ""), label=f"history row {row_no} trade_date"
    )
    minutes: list[str] = []
    for field in ("normal_minutes_local", "event_minutes_local"):
        for raw in str(row.get(field, "") or "").split(";"):
            raw = raw.strip()
            if raw:
                minutes.append(
                    _parse_local_minute(
                        raw, label=f"history row {row_no} {field}"
                    )
                )
    if not minutes:
        raise G5ControlSharesReconciliationError(
            f"history row {row_no}: shares-required row has no admissible cutoff minute"
        )

    # event_minutes_local contains both the previous completed minute and the event
    # target minute. Taking the earliest required minute is deliberately conservative:
    # a reused shares fact must have been available before every downstream G5 use.
    minute = min(minutes)
    local = datetime.fromisoformat(f"{trade_date}T{minute}:00").replace(tzinfo=NY)
    return local.astimezone(timezone.utc)


def _fmt_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _load_required_shares(path: Path) -> list[dict[str, str]]:
    fields, rows = _read_csv(path)
    required = {
        "historical_symbol",
        "trade_date",
        "normal_minutes_local",
        "event_minutes_local",
        "require_shares_outstanding",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5ControlSharesReconciliationError(
            f"control-history requirements missing columns: {sorted(missing)}"
        )

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row_no, row in enumerate(rows, 2):
        if row["research_use_only"] != "1":
            raise G5ControlSharesReconciliationError(
                f"history row {row_no}: research_use_only must equal 1"
            )
        flag = row["require_shares_outstanding"]
        if flag not in {"0", "1"}:
            raise G5ControlSharesReconciliationError(
                f"history row {row_no}: require_shares_outstanding must be 0 or 1"
            )
        if flag == "0":
            continue
        symbol = row["historical_symbol"].upper()
        trade_date = _parse_date(
            row["trade_date"], label=f"history row {row_no} trade_date"
        )
        if not symbol:
            raise G5ControlSharesReconciliationError(
                f"history row {row_no}: historical_symbol required"
            )
        key = (symbol, trade_date)
        if key in seen:
            raise G5ControlSharesReconciliationError(
                f"duplicate shares-required control-history pair: {symbol}|{trade_date}"
            )
        seen.add(key)
        out.append(
            {
                "historical_symbol": symbol,
                "trade_date": trade_date,
                "cutoff": _fmt_ts(_shares_cutoff(row, row_no=row_no)),
            }
        )
    if not out:
        raise G5ControlSharesReconciliationError(
            "control-history requirements contain no shares-required rows"
        )
    return out


def _load_g4_resolutions(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    fields, rows = _read_csv(path)
    required = {
        "historical_symbol",
        "trade_date",
        "shares_outstanding",
        "resolution_status",
        "available_at",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5ControlSharesReconciliationError(
            f"canonical G4 shares resolutions missing columns: {sorted(missing)}"
        )

    out: dict[tuple[str, str], dict[str, str]] = {}
    for row_no, row in enumerate(rows, 2):
        if row["research_use_only"] != "1":
            raise G5ControlSharesReconciliationError(
                f"G4 row {row_no}: research_use_only must equal 1"
            )
        symbol = row["historical_symbol"].upper()
        trade_date = _parse_date(
            row["trade_date"], label=f"G4 row {row_no} trade_date"
        )
        if not symbol:
            raise G5ControlSharesReconciliationError(
                f"G4 row {row_no}: historical_symbol required"
            )
        key = (symbol, trade_date)
        if key in out:
            raise G5ControlSharesReconciliationError(
                f"duplicate canonical G4 shares resolution: {symbol}|{trade_date}"
            )
        if row["resolution_status"] == "resolved":
            try:
                shares = int(row["shares_outstanding"])
            except ValueError as exc:
                raise G5ControlSharesReconciliationError(
                    f"G4 row {row_no}: resolved shares_outstanding must be positive integer"
                ) from exc
            if shares <= 0:
                raise G5ControlSharesReconciliationError(
                    f"G4 row {row_no}: resolved shares_outstanding must be positive integer"
                )
            _parse_ts(row["available_at"], label=f"G4 row {row_no} available_at")
        out[key] = row
    return out


def build(
    *,
    control_history_path: Path,
    canonical_g4_shares_path: Path,
    output_dir: Path,
) -> dict:
    required_rows = _load_required_shares(control_history_path)
    g4 = _load_g4_resolutions(canonical_g4_shares_path)

    reused: list[ReusedSharesResolution] = []
    gaps: list[SharesAcquisitionRequest] = []
    gap_counts: Counter[str] = Counter()

    for item in sorted(
        required_rows,
        key=lambda row: (row["trade_date"], row["historical_symbol"]),
    ):
        symbol = item["historical_symbol"]
        trade_date = item["trade_date"]
        cutoff = _parse_ts(item["cutoff"], label=f"G5 cutoff {symbol}|{trade_date}")
        current = g4.get((symbol, trade_date))

        reason = ""
        if current is None:
            reason = "NO_CANONICAL_G4_ROW"
        elif current["resolution_status"] != "resolved":
            reason = "CANONICAL_G4_NOT_RESOLVED"
        else:
            available = _parse_ts(
                current["available_at"],
                label=f"G4 available_at {symbol}|{trade_date}",
            )
            if available > cutoff:
                reason = "CANONICAL_G4_AVAILABLE_AFTER_G5_CUTOFF"

        if reason:
            gap_counts[reason] += 1
            gaps.append(
                SharesAcquisitionRequest(
                    historical_symbol=symbol,
                    trade_date=trade_date,
                    latest_acceptable_available_at_utc=item["cutoff"],
                    gap_reason=reason,
                    existing_resolution_status=(
                        current["resolution_status"] if current else ""
                    ),
                    existing_available_at=(current["available_at"] if current else ""),
                )
            )
            continue

        assert current is not None
        reused.append(
            ReusedSharesResolution(
                historical_symbol=symbol,
                trade_date=trade_date,
                latest_acceptable_available_at_utc=item["cutoff"],
                shares_outstanding=current["shares_outstanding"],
                available_at=current["available_at"],
                source_reference=current.get("source_reference", ""),
                source_tag=current.get("source_tag", ""),
            )
        )

    if len(reused) + len(gaps) != len(required_rows):
        raise G5ControlSharesReconciliationError(
            "G5 shares reconciliation does not account for every requirement"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    reuse_path = output_dir / "g5_control_shares_g4_reuse.csv"
    gap_path = output_dir / "g5_control_shares_acquisition_queue.csv"
    summary_path = output_dir / "g5_control_shares_reconciliation_summary.json"

    with reuse_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(ReusedSharesResolution.__dataclass_fields__)
        )
        writer.writeheader()
        for row in reused:
            writer.writerow(asdict(row))

    with gap_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(SharesAcquisitionRequest.__dataclass_fields__)
        )
        writer.writeheader()
        for row in gaps:
            writer.writerow(asdict(row))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Reconcile every point-in-time shares requirement in the G5 primary-control "
            "history footprint against canonical G4 shares evidence. Exact symbol/date "
            "G4 rows are reused only when already resolved and available before the "
            "conservative earliest G5 cutoff; all remaining rows become explicit "
            "incremental acquisition requests."
        ),
        "research_use_only": True,
        "required_shares_symbol_date_count": len(required_rows),
        "canonical_g4_reuse_count": len(reused),
        "incremental_g5_shares_acquisition_count": len(gaps),
        "gap_reason_counts": dict(sorted(gap_counts.items())),
        "distinct_required_historical_symbol_count": len(
            {row["historical_symbol"] for row in required_rows}
        ),
        "distinct_incremental_historical_symbol_count": len(
            {row.historical_symbol for row in gaps}
        ),
        "inputs": {
            "control_history": {
                "path": str(control_history_path),
                "sha256": _sha256(control_history_path),
            },
            "canonical_g4_shares": {
                "path": str(canonical_g4_shares_path),
                "sha256": _sha256(canonical_g4_shares_path),
            },
        },
        "outputs": {
            "canonical_g4_reuse": str(reuse_path),
            "incremental_acquisition_queue": str(gap_path),
            "summary": str(summary_path),
        },
        "acquisition_contract": {
            "preferred_route": ACQUISITION_ROUTE,
            "minimum_fields": [
                "historical_symbol",
                "trade_date",
                "fact_date",
                "available_at",
                "shares_outstanding",
                "source_reference",
            ],
            "fact_date_must_not_exceed_trade_date": True,
            "maximum_fact_staleness_days": 130,
            "available_at_must_not_exceed_g5_cutoff": True,
        },
        "policy": {
            "exact_symbol_date_reuse_only": True,
            "canonical_g4_resolution_must_be_resolved": True,
            "canonical_g4_availability_rechecked_for_g5_cutoff": True,
            "earliest_required_minute_used_conservatively": True,
            "planning_rows_are_g5_evidence": False,
            "purchase_authorized": False,
            "data_fetch_performed": False,
            "canonical_g4_coverage_unchanged": True,
            "canonical_g5_readiness_unchanged": True,
        },
        "g5_dates_resolved_change": 0,
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
            "Reconcile G5 control-history point-in-time shares requirements against "
            "canonical G4 shares evidence and emit the exact incremental gap queue."
        )
    )
    parser.add_argument("--control-history", type=Path, required=True)
    parser.add_argument("--canonical-g4-shares", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        control_history_path=args.control_history,
        canonical_g4_shares_path=args.canonical_g4_shares,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
