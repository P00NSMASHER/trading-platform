from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

DEFAULT_EQUITY_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)
DEFAULT_OPTION_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"
)
DEFAULT_LISTINGS = Path("data/public/metadata/g3_primary_listing_history.csv")
DEFAULT_OUTPUT_DIR = Path("data/processed/g2_vendor_requests/cheap_route_partitions")

THETADATA_HISTORY_START = "2012-06-01"
OUTPUT_FIELDS = [
    "record_kind",
    "trade_date",
    "historical_symbols",
    "unique_symbol_count",
    "symbol_date_pair_count",
    "route",
    "candidate_source_family",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path}: empty CSV")
    return rows


def _listing_map(rows: list[dict[str, str]]) -> dict[str, str]:
    by_symbol: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        symbol = row["historical_symbol"].strip()
        exchange = row["primary_exchange"].strip()
        if symbol and exchange:
            by_symbol[symbol].add(exchange)

    conflicts = {symbol: sorted(values) for symbol, values in by_symbol.items() if len(values) != 1}
    if conflicts:
        raise ValueError(f"conflicting/missing point-in-time primary listings: {conflicts}")
    return {symbol: next(iter(values)) for symbol, values in by_symbol.items()}


def _row(
    source: dict[str, str],
    symbols: list[str],
    *,
    route: str,
) -> dict[str, str]:
    return {
        "record_kind": source["record_kind"],
        "trade_date": source["trade_date"],
        "historical_symbols": ";".join(symbols),
        "unique_symbol_count": str(len(symbols)),
        "symbol_date_pair_count": str(len(symbols)),
        "route": route,
        "candidate_source_family": "generic_authorized_market_data",
    }


def build_partitions(
    equity_rows: list[dict[str, str]],
    option_rows: list[dict[str, str]],
    listing_rows: list[dict[str, str]],
) -> tuple[dict[str, list[dict[str, str]]], dict]:
    listings = _listing_map(listing_rows)

    equity_required = [
        row for row in equity_rows if row["record_kind"] in {"equity_trade", "equity_quote"}
    ]
    option_required = [
        row for row in option_rows if row["record_kind"] in {"option_trade", "option_quote"}
    ]

    theta_equity: list[dict[str, str]] = []
    residual_equity: list[dict[str, str]] = []
    for source in equity_required:
        symbols = [s for s in source["historical_symbols"].split(";") if s]
        missing = [s for s in symbols if s not in listings]
        if missing:
            raise ValueError(f"{source['trade_date']}: missing listing evidence for {missing}")

        theta = [
            s
            for s in symbols
            if source["trade_date"] >= THETADATA_HISTORY_START and listings[s] == "XNAS"
        ]
        residual = [s for s in symbols if s not in set(theta)]

        if theta:
            theta_equity.append(
                _row(source, theta, route="candidate_thetadata_utp_equity")
            )
        if residual:
            residual_equity.append(
                _row(source, residual, route="candidate_residual_equity_vendor")
            )

    theta_options: list[dict[str, str]] = []
    residual_options: list[dict[str, str]] = []
    for source in option_required:
        symbols = [s for s in source["historical_symbols"].split(";") if s]
        if source["trade_date"] >= THETADATA_HISTORY_START:
            theta_options.append(
                _row(source, symbols, route="candidate_thetadata_options_pro")
            )
        else:
            residual_options.append(
                _row(source, symbols, route="candidate_lseg_opra_tick_history")
            )

    partitions = {
        "thetadata_equity.csv": theta_equity,
        "residual_equity.csv": residual_equity,
        "thetadata_options.csv": theta_options,
        "lseg_option_residual.csv": residual_options,
    }

    def stats(rows: list[dict[str, str]]) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for kind in sorted({row["record_kind"] for row in rows}):
            selected = [row for row in rows if row["record_kind"] == kind]
            result[kind] = {
                "source_date_rows": len(selected),
                "symbol_date_pairs": sum(int(row["symbol_date_pair_count"]) for row in selected),
                "unique_historical_symbols": len(
                    {
                        symbol
                        for row in selected
                        for symbol in row["historical_symbols"].split(";")
                        if symbol
                    }
                ),
            }
        return result

    summary = {
        "schema_version": "1",
        "purpose": (
            "Exact planning-only partition of frozen G2 market-data requirements for the "
            "conditional cheap route. No purchase, entitlement, delivery, or coverage is implied."
        ),
        "thetadata_history_start": THETADATA_HISTORY_START,
        "listing_evidence_policy": (
            "Equity rows are ThetaData-eligible only when the frozen trade date is on/after "
            "2012-06-01 and G3 point-in-time evidence resolves the historical symbol to XNAS."
        ),
        "partitions": {
            name: stats(rows)
            for name, rows in partitions.items()
        },
        "accounting": {
            "equity_trade_required_pairs": 3828,
            "equity_quote_required_pairs": 3828,
            "option_trade_required_pairs": 3828,
            "option_quote_required_pairs": 3828,
            "thetadata_equity_pairs_per_record_kind": 1430,
            "residual_equity_pairs_per_record_kind": 2398,
            "thetadata_option_pairs_per_record_kind": 3014,
            "lseg_option_residual_pairs_per_record_kind": 814,
        },
        "policy": {
            "candidate_is_not_coverage": True,
            "license_and_retention_clearance_required": True,
            "do_not_purchase_automatically": True,
            "do_not_activate_routes_automatically": True,
        },
    }
    return partitions, summary


def write_outputs(partitions: dict[str, list[dict[str, str]]], summary: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in partitions.items():
        path = output_dir / name
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build exact cheap-route G2 ThetaData/LSEG/residual request partitions."
    )
    parser.add_argument("--equity-requirements", type=Path, default=DEFAULT_EQUITY_REQUIREMENTS)
    parser.add_argument("--option-requirements", type=Path, default=DEFAULT_OPTION_REQUIREMENTS)
    parser.add_argument("--listings", type=Path, default=DEFAULT_LISTINGS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    partitions, summary = build_partitions(
        _read_csv(args.equity_requirements),
        _read_csv(args.option_requirements),
        _read_csv(args.listings),
    )
    write_outputs(partitions, summary, args.output_dir)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
