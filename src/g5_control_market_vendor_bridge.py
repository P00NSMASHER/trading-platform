from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from g2_candidate_route_matrix import classify as classify_g2_route
from g2_full_replication_option_quote_plan import _route_for_date as option_quote_route


SCHEMA_VERSION = "1"
MARKET_KINDS = (
    "equity_trade",
    "equity_quote",
    "option_trade",
    "option_quote",
)

ROUTE_FILENAMES = {
    "candidate_tickdata_equity_trades": "tickdata_equity_trades.csv",
    "candidate_tickdata_equity_nbbo_quotes": "tickdata_equity_nbbo_quotes.csv",
    "candidate_databento_opra_trades": "databento_opra_trades.csv",
    "candidate_cboe_option_trades": "cboe_option_trades.csv",
    "candidate_lseg_opra_tick_history": "lseg_opra_tick_history.csv",
    "candidate_lseg_opra_tick_history_option_quotes": "lseg_opra_tick_history_option_quotes.csv",
    "candidate_thetadata_options_pro_option_quotes": "thetadata_option_quotes.csv",
}


@dataclass(frozen=True)
class IncrementalVendorRequest:
    trade_date: str
    record_kind: str
    historical_symbols: str
    unique_symbol_count: int
    symbol_date_pair_count: int
    route: str
    candidate_source_family: str
    g5_incremental_only: int = 1
    research_use_only: int = 1


class G5ControlMarketVendorBridgeError(ValueError):
    pass


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    return fields, rows


def _symbols(value: str, *, label: str) -> list[str]:
    items = [item.strip().upper() for item in str(value or "").split(";") if item.strip()]
    if len(items) != len(set(items)):
        raise G5ControlMarketVendorBridgeError(
            f"{label}: historical_symbols contains duplicates"
        )
    return sorted(items)


def _load_frozen_pairs(
    fields: list[str],
    rows: list[dict[str, str]],
) -> dict[str, set[tuple[str, str]]]:
    required = {"record_kind", "trade_date", "historical_symbols"}
    missing = required.difference(fields)
    if missing:
        raise G5ControlMarketVendorBridgeError(
            f"frozen requirements missing columns: {sorted(missing)}"
        )

    out = {kind: set() for kind in MARKET_KINDS}
    for row_no, row in enumerate(rows, 2):
        kind = row["record_kind"]
        if kind not in out:
            continue
        trade_date = row["trade_date"][:10]
        if not trade_date:
            raise G5ControlMarketVendorBridgeError(
                f"frozen requirements row {row_no}: trade_date required"
            )
        for symbol in _symbols(
            row["historical_symbols"],
            label=f"frozen requirements row {row_no}",
        ):
            out[kind].add((symbol, trade_date))
    return out


def _route(kind: str, trade_date: str) -> tuple[str, str]:
    if kind == "option_quote":
        route = option_quote_route(trade_date)
    else:
        try:
            route, _reason = classify_g2_route(
                {
                    "record_kind": kind,
                    "trade_date": trade_date,
                    "symbol_date_pair_count": "1",
                }
            )
        except ValueError as exc:
            raise G5ControlMarketVendorBridgeError(str(exc)) from exc

    source_family = (
        "cboe_option_trades"
        if route == "candidate_cboe_option_trades"
        else "generic_authorized_market_data"
    )
    return route, source_family


def build(
    *,
    g5_source_requirements_path: Path,
    frozen_g2_requirements_path: Path,
    output_dir: Path,
) -> dict:
    g5_fields, g5_rows = _read_csv(g5_source_requirements_path)
    required_g5 = {
        "record_kind",
        "trade_date",
        "unique_symbol_count",
        "historical_symbols",
        "symbol_date_pair_count",
        "frozen_g2_symbol_date_pair_count",
        "additional_g5_symbol_date_pair_count",
        "research_use_only",
    }
    missing_g5 = required_g5.difference(g5_fields)
    if missing_g5:
        raise G5ControlMarketVendorBridgeError(
            f"G5 source requirements missing columns: {sorted(missing_g5)}"
        )
    if not g5_rows:
        raise G5ControlMarketVendorBridgeError("G5 source requirements are empty")

    frozen_fields, frozen_rows = _read_csv(frozen_g2_requirements_path)
    frozen_pairs = _load_frozen_pairs(frozen_fields, frozen_rows)

    routed: list[IncrementalVendorRequest] = []
    expected_incremental_total = 0
    reconstructed_incremental_total = 0
    reconstructed_frozen_total = 0
    seen_g5_rows: set[tuple[str, str]] = set()

    for row_no, row in enumerate(g5_rows, 2):
        kind = row["record_kind"]
        trade_date = row["trade_date"][:10]
        if kind not in MARKET_KINDS:
            raise G5ControlMarketVendorBridgeError(
                f"G5 source row {row_no}: unsupported record_kind {kind!r}"
            )
        if not trade_date:
            raise G5ControlMarketVendorBridgeError(
                f"G5 source row {row_no}: trade_date required"
            )
        if row["research_use_only"] != "1":
            raise G5ControlMarketVendorBridgeError(
                f"G5 source row {row_no}: research_use_only must equal 1"
            )
        row_key = (kind, trade_date)
        if row_key in seen_g5_rows:
            raise G5ControlMarketVendorBridgeError(
                f"duplicate G5 source-date row: {kind}|{trade_date}"
            )
        seen_g5_rows.add(row_key)

        symbols = _symbols(
            row["historical_symbols"],
            label=f"G5 source row {row_no}",
        )
        unique_count = int(row["unique_symbol_count"])
        pair_count = int(row["symbol_date_pair_count"])
        expected_frozen = int(row["frozen_g2_symbol_date_pair_count"])
        expected_incremental = int(row["additional_g5_symbol_date_pair_count"])

        if unique_count != len(symbols) or pair_count != len(symbols):
            raise G5ControlMarketVendorBridgeError(
                f"G5 source row {row_no}: symbol counts do not match historical_symbols"
            )
        if expected_frozen + expected_incremental != pair_count:
            raise G5ControlMarketVendorBridgeError(
                f"G5 source row {row_no}: frozen + additional counts do not reconcile"
            )

        frozen = [
            symbol
            for symbol in symbols
            if (symbol, trade_date) in frozen_pairs[kind]
        ]
        incremental = [
            symbol
            for symbol in symbols
            if (symbol, trade_date) not in frozen_pairs[kind]
        ]
        if len(frozen) != expected_frozen:
            raise G5ControlMarketVendorBridgeError(
                f"G5 source row {row_no}: frozen overlap mismatch "
                f"{len(frozen)} != {expected_frozen}"
            )
        if len(incremental) != expected_incremental:
            raise G5ControlMarketVendorBridgeError(
                f"G5 source row {row_no}: incremental pair mismatch "
                f"{len(incremental)} != {expected_incremental}"
            )

        expected_incremental_total += expected_incremental
        reconstructed_incremental_total += len(incremental)
        reconstructed_frozen_total += len(frozen)

        if not incremental:
            continue
        route, source_family = _route(kind, trade_date)
        routed.append(
            IncrementalVendorRequest(
                trade_date=trade_date,
                record_kind=kind,
                historical_symbols=";".join(incremental),
                unique_symbol_count=len(incremental),
                symbol_date_pair_count=len(incremental),
                route=route,
                candidate_source_family=source_family,
            )
        )

    if reconstructed_incremental_total != expected_incremental_total:
        raise G5ControlMarketVendorBridgeError(
            "incremental pair total does not reconcile"
        )

    grouped: dict[str, list[IncrementalVendorRequest]] = defaultdict(list)
    for row in routed:
        grouped[row.route].append(row)

    output_dir.mkdir(parents=True, exist_ok=True)
    route_outputs: dict[str, str] = {}
    route_source_date_rows: dict[str, int] = {}
    route_pair_counts: dict[str, int] = {}

    for route in sorted(grouped):
        filename = ROUTE_FILENAMES.get(route)
        if filename is None:
            raise G5ControlMarketVendorBridgeError(
                f"no output filename configured for route {route}"
            )
        path = output_dir / filename
        rows = sorted(
            grouped[route],
            key=lambda item: (item.trade_date, item.record_kind),
        )
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(IncrementalVendorRequest.__dataclass_fields__),
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(asdict(row))
        route_outputs[route] = str(path)
        route_source_date_rows[route] = len(rows)
        route_pair_counts[route] = sum(row.symbol_date_pair_count for row in rows)

    by_kind = {
        kind: sum(
            row.symbol_date_pair_count
            for row in routed
            if row.record_kind == kind
        )
        for kind in MARKET_KINDS
    }
    distinct_symbols = {
        symbol
        for row in routed
        for symbol in row.historical_symbols.split(";")
        if symbol
    }

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Bridge only the incremental G5 control-history market-data pairs, after "
            "subtracting frozen G2 symbol/date coverage exactly, into the existing "
            "candidate vendor lanes. Candidate routing is acquisition planning only."
        ),
        "research_use_only": True,
        "g5_source_date_row_count": len(g5_rows),
        "incremental_source_date_row_count": len(routed),
        "frozen_g2_overlap_pair_count": reconstructed_frozen_total,
        "expected_incremental_g5_pair_count": expected_incremental_total,
        "incremental_g5_pair_count": reconstructed_incremental_total,
        "incremental_pair_count_by_record_kind": by_kind,
        "distinct_incremental_historical_symbol_count": len(distinct_symbols),
        "route_source_date_rows": dict(sorted(route_source_date_rows.items())),
        "route_symbol_date_pair_counts": dict(sorted(route_pair_counts.items())),
        "outputs": dict(sorted(route_outputs.items())),
        "policy": {
            "frozen_g2_pairs_are_removed_before_vendor_routing": True,
            "candidate_route_is_not_market_coverage": True,
            "authorization_and_license_validation_required": True,
            "purchase_authorized": False,
            "data_fetch_performed": False,
            "equity_quotes_require_tick_nbbo_fidelity": True,
            "option_quotes_require_tick_nbbo_fidelity": True,
            "minute_snapshot_substitution_allowed": False,
            "canonical_g2_coverage_unchanged": True,
            "canonical_g5_readiness_unchanged": True,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_control_market_vendor_bridge_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Route only incremental G5 control-history market-data pairs into "
            "existing candidate vendor lanes after exact frozen-G2 subtraction."
        )
    )
    parser.add_argument("--g5-source-requirements", type=Path, required=True)
    parser.add_argument("--frozen-g2-requirements", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        g5_source_requirements_path=args.g5_source_requirements,
        frozen_g2_requirements_path=args.frozen_g2_requirements,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
