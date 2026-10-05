from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


SCHEMA_VERSION = "1"

READY_FIELDS = [
    "request_id",
    "permno",
    "historical_symbol",
    "trade_date",
    "hint_source",
    "identity_status",
    "research_use_only",
]


@dataclass(frozen=True)
class SymbolLead:
    historical_symbol: str
    canonical_permno_hint: str
    samplefirms_permno_hint: str
    required_dates: tuple[str, ...]

    @property
    def permno(self) -> str:
        return self.canonical_permno_hint or self.samplefirms_permno_hint

    @property
    def source(self) -> str:
        if self.canonical_permno_hint:
            return "SYMBOL_LEVEL_CANONICAL_PERMNO_ACQUISITION_LEAD"
        if self.samplefirms_permno_hint:
            return "SYMBOL_LEVEL_SAMPLEFIRMS_PERMNO_ACQUISITION_LEAD"
        return ""


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


def _request_id(symbol: str, trade_date: str, permno: str) -> str:
    raw = f"{symbol}|{trade_date}|{permno}".encode("utf-8")
    return "G5SID-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def _load_symbol_leads(
    fields: list[str],
    rows: list[dict[str, str]],
) -> tuple[dict[str, SymbolLead], set[tuple[str, str]]]:
    required = {
        "historical_symbol",
        "required_date_count",
        "first_required_date",
        "last_required_date",
        "required_dates",
        "canonical_permno_hint",
        "samplefirms_permno_hint",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise ValueError(
            f"identity interval requests missing columns: {sorted(missing)}"
        )
    if not rows:
        raise ValueError("identity interval requests are empty")

    leads: dict[str, SymbolLead] = {}
    interval_pairs: set[tuple[str, str]] = set()
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        if not symbol or symbol in leads:
            raise ValueError(
                f"identity interval row {row_no}: historical_symbol must be unique and nonblank"
            )
        if row["research_use_only"] != "1":
            raise ValueError(
                f"identity interval row {row_no}: research_use_only must equal 1"
            )

        dates = [value for value in row["required_dates"].split(";") if value]
        if not dates or dates != sorted(set(dates)):
            raise ValueError(
                f"identity interval row {row_no}: required_dates must be sorted and unique"
            )
        if len(dates) != int(row["required_date_count"]):
            raise ValueError(
                f"identity interval row {row_no}: required_date_count mismatch"
            )
        if row["first_required_date"] != dates[0] or row["last_required_date"] != dates[-1]:
            raise ValueError(
                f"identity interval row {row_no}: first/last required date mismatch"
            )

        canonical = row["canonical_permno_hint"]
        sample = row["samplefirms_permno_hint"]
        if canonical and sample and canonical != sample:
            raise ValueError(
                f"symbol-level PERMNO hint conflict for {symbol}: {canonical} != {sample}"
            )

        lead = SymbolLead(
            historical_symbol=symbol,
            canonical_permno_hint=canonical,
            samplefirms_permno_hint=sample,
            required_dates=tuple(dates),
        )
        leads[symbol] = lead
        for trade_date in dates:
            pair = (symbol, trade_date)
            if pair in interval_pairs:
                raise ValueError(
                    f"duplicate interval symbol-date requirement: {symbol}|{trade_date}"
                )
            interval_pairs.add(pair)
    return leads, interval_pairs


def build(
    *,
    identity_queue_path: Path,
    interval_requests_path: Path,
    output_dir: Path,
) -> dict:
    queue_fields, queue_rows = _read_csv(identity_queue_path)
    required_queue = {
        "historical_symbol",
        "trade_date",
        "identity_status",
        "canonical_permno",
        "samplefirms_permno",
        "research_use_only",
    }
    missing_queue = required_queue.difference(queue_fields)
    if missing_queue:
        raise ValueError(
            f"identity queue missing columns: {sorted(missing_queue)}"
        )
    if not queue_rows:
        raise ValueError("identity queue is empty")

    interval_fields, interval_rows = _read_csv(interval_requests_path)
    symbol_leads, interval_pairs = _load_symbol_leads(
        interval_fields,
        interval_rows,
    )

    queue_pairs: set[tuple[str, str]] = set()
    normalized_queue: list[dict[str, str]] = []
    for row_no, row in enumerate(queue_rows, 2):
        symbol = row["historical_symbol"].upper()
        trade_date = row["trade_date"][:10]
        if not symbol or not trade_date:
            raise ValueError(
                f"identity queue row {row_no}: historical_symbol/trade_date required"
            )
        if row["research_use_only"] != "1":
            raise ValueError(
                f"identity queue row {row_no}: research_use_only must equal 1"
            )
        pair = (symbol, trade_date)
        if pair in queue_pairs:
            raise ValueError(
                f"duplicate identity queue requirement: {symbol}|{trade_date}"
            )
        queue_pairs.add(pair)
        normalized = dict(row)
        normalized["historical_symbol"] = symbol
        normalized["trade_date"] = trade_date
        normalized_queue.append(normalized)

    if queue_pairs != interval_pairs:
        missing_from_intervals = sorted(queue_pairs - interval_pairs)
        extra_in_intervals = sorted(interval_pairs - queue_pairs)
        raise ValueError(
            "identity interval/date-level scope mismatch: "
            f"missing={missing_from_intervals[:5]} extra={extra_in_intervals[:5]}"
        )

    ready: list[dict[str, str]] = []
    residual: list[dict[str, str]] = []
    exact_date_ready = 0
    symbol_level_added = 0
    symbol_level_canonical_added = 0
    symbol_level_sample_added = 0

    for row in sorted(
        normalized_queue,
        key=lambda item: (item["trade_date"], item["historical_symbol"]),
    ):
        symbol = row["historical_symbol"]
        trade_date = row["trade_date"]
        canonical = row["canonical_permno"]
        sample = row["samplefirms_permno"]

        if canonical and sample and canonical != sample:
            raise ValueError(
                f"date-level PERMNO hint conflict for {symbol}|{trade_date}: "
                f"{canonical} != {sample}"
            )

        direct_permno = canonical or sample
        direct_source = (
            "CANONICAL_G2_PERMNO"
            if canonical
            else "SAMPLEFIRMS_EXACT_DATE_PERMNO_LEAD"
            if sample
            else ""
        )

        symbol_lead = symbol_leads.get(symbol)
        if symbol_lead is None:
            raise ValueError(f"missing symbol-level identity request for {symbol}")
        symbol_permno = symbol_lead.permno

        if direct_permno and symbol_permno and direct_permno != symbol_permno:
            raise ValueError(
                f"date/symbol-level PERMNO hint conflict for {symbol}|{trade_date}: "
                f"{direct_permno} != {symbol_permno}"
            )

        permno = direct_permno or symbol_permno
        if not permno:
            residual.append(dict(row))
            continue

        if direct_permno:
            hint_source = direct_source
            exact_date_ready += 1
        else:
            hint_source = symbol_lead.source
            symbol_level_added += 1
            if hint_source == "SYMBOL_LEVEL_CANONICAL_PERMNO_ACQUISITION_LEAD":
                symbol_level_canonical_added += 1
            elif hint_source == "SYMBOL_LEVEL_SAMPLEFIRMS_PERMNO_ACQUISITION_LEAD":
                symbol_level_sample_added += 1
            else:
                raise ValueError(
                    f"symbol-level PERMNO lead source missing for {symbol}|{trade_date}"
                )

        ready.append(
            {
                "request_id": _request_id(symbol, trade_date, permno),
                "permno": permno,
                "historical_symbol": symbol,
                "trade_date": trade_date,
                "hint_source": hint_source,
                "identity_status": row["identity_status"],
                "research_use_only": "1",
            }
        )

    if len(ready) + len(residual) != len(queue_rows):
        raise ValueError("expanded Stocknames handoff accounting does not reconcile")
    if exact_date_ready + symbol_level_added != len(ready):
        raise ValueError("ready Stocknames request accounting does not reconcile")

    output_dir.mkdir(parents=True, exist_ok=True)
    ready_path = output_dir / "g5_control_identity_stocknames_expanded_ready_queue.csv"
    residual_path = output_dir / "g5_control_identity_stocknames_symbol_discovery_queue.csv"

    with ready_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=READY_FIELDS)
        writer.writeheader()
        writer.writerows(ready)

    with residual_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=queue_fields)
        writer.writeheader()
        writer.writerows(residual)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Expand the G5 dated Stocknames validation handoff by using only "
            "symbol-level PERMNO hints already reconciled by the interval-request "
            "planner as acquisition leads for otherwise no-hint dates. Every date "
            "still requires authorized dated Stocknames validation; no identity "
            "continuity is inferred."
        ),
        "research_use_only": True,
        "identity_queue_count": len(queue_rows),
        "symbol_level_request_count": len(symbol_leads),
        "exact_date_ready_request_count": exact_date_ready,
        "symbol_level_lead_added_request_count": symbol_level_added,
        "symbol_level_canonical_lead_added_request_count": symbol_level_canonical_added,
        "symbol_level_samplefirms_lead_added_request_count": symbol_level_sample_added,
        "expanded_stocknames_ready_request_count": len(ready),
        "residual_symbol_discovery_request_count": len(residual),
        "request_ids_unique": len({row["request_id"] for row in ready}) == len(ready),
        "inputs": {
            "identity_queue_path": str(identity_queue_path),
            "identity_queue_sha256": _sha256(identity_queue_path),
            "interval_requests_path": str(interval_requests_path),
            "interval_requests_sha256": _sha256(interval_requests_path),
        },
        "outputs": {
            "expanded_stocknames_ready_queue": str(ready_path),
            "residual_symbol_discovery_queue": str(residual_path),
        },
        "policy": {
            "symbol_level_permno_is_acquisition_lead_only": True,
            "symbol_level_permno_is_identity_evidence": False,
            "cross_date_identity_continuity_assumed": False,
            "authorized_stocknames_validation_still_required": True,
            "requested_date_must_be_inside_authorized_name_interval": True,
            "historical_symbol_must_match_authorized_name_interval": True,
            "scope_must_exactly_match_date_level_identity_queue": True,
            "handoff_rows_are_g5_evidence": False,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_control_identity_stocknames_lead_expansion_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Expand G5 Stocknames acquisition routing with reconciled symbol-level "
            "PERMNO leads while preserving exact dated validation."
        )
    )
    parser.add_argument("--identity-queue", type=Path, required=True)
    parser.add_argument("--interval-requests", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        identity_queue_path=args.identity_queue,
        interval_requests_path=args.interval_requests,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
