from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_VENDOR_DIR = Path("data/processed/g2_vendor_requests")
DEFAULT_SOURCE_BLUEPRINT = Path(
    "data/processed/real_data_release_sprint/production_source_contract_blueprint.json"
)

ROUTES = {
    "candidate_tickdata_equity_trades": {
        "vendor": "Tick Data",
        "product_request": "U.S. equities tick-by-tick trades",
        "file": "tickdata_equity_trades.csv",
        "record_kind": "equity_trade",
        "fidelity_requirements": [
            "tick-level trade timestamps",
            "trade price and size",
            "all requested symbols/dates",
            "no daily or minute aggregation",
        ],
    },
    "candidate_tickdata_equity_nbbo_quotes": {
        "vendor": "Tick Data",
        "product_request": "U.S. equities tick-by-tick consolidated NBBO quotes",
        "file": "tickdata_equity_nbbo_quotes.csv",
        "record_kind": "equity_quote",
        "fidelity_requirements": [
            "tick-level NBBO quote updates",
            "bid/ask prices and sizes",
            "all requested symbols/dates",
            "no interval-snapshot substitution",
        ],
    },
    "candidate_databento_opra_trades": {
        "vendor": "Databento",
        "product_request": "OPRA historical option trades",
        "file": "databento_opra_trades.csv",
        "record_kind": "option_trade",
        "fidelity_requirements": [
            "trade-level timestamps",
            "underlying and option contract identifiers",
            "expiration, strike, option type, trade price and size",
            "all requested underlyings/dates",
            "no minute or daily aggregation",
        ],
    },
    "candidate_cboe_option_trades": {
        "vendor": "Cboe DataShop",
        "product_request": "Historical Option Trades",
        "file": "cboe_option_trades.csv",
        "record_kind": "option_trade",
        "fidelity_requirements": [
            "trade-level timestamps",
            "underlying and option contract identifiers",
            "expiration, strike, option type, trade price and size",
            "all requested underlyings/dates",
            "no interval-snapshot substitution",
        ],
    },
    "candidate_lseg_opra_tick_history": {
        "vendor": "LSEG Tick History",
        "product_request": "OPRA historical last-sale/tick trades",
        "file": "lseg_opra_tick_history.csv",
        "record_kind": "option_trade",
        "fidelity_requirements": [
            "trade-level timestamps",
            "underlying and option contract identifiers",
            "expiration, strike, option type, trade price and size",
            "all requested underlyings/dates",
            "no minute or daily aggregation",
        ],
    },
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_packets(vendor_dir: Path, source_blueprint: Path) -> dict:
    blueprint = json.loads(source_blueprint.read_text(encoding="utf-8"))
    source_types = blueprint["source_types"]
    packets = []

    for route, cfg in ROUTES.items():
        path = vendor_dir / cfg["file"]
        rows = _read_csv(path)
        if not rows:
            raise ValueError(f"{path}: empty request manifest")
        if {row["route"] for row in rows} != {route}:
            raise ValueError(f"{path}: route mismatch")
        dates = sorted(row["trade_date"] for row in rows)
        symbols = sorted({
            symbol
            for row in rows
            for symbol in row["historical_symbols"].split(";")
            if symbol
        })
        packets.append({
            "route": route,
            "vendor": cfg["vendor"],
            "product_request": cfg["product_request"],
            "request_manifest": f"data/processed/g2_vendor_requests/{cfg['file']}",
            "record_kind": cfg["record_kind"],
            "first_trade_date": dates[0],
            "last_trade_date": dates[-1],
            "source_date_rows": len(rows),
            "symbol_date_pair_count": sum(int(row["symbol_date_pair_count"]) for row in rows),
            "unique_historical_symbols": len(symbols),
            "historical_symbols": symbols,
            "required_canonical_fields": source_types[cfg["record_kind"]]["required_canonical_fields"],
            "fidelity_requirements": cfg["fidelity_requirements"],
            "request_policy": {
                "quote_or_availability_request_only": True,
                "do_not_purchase_automatically": True,
                "license_terms_must_be_reviewed": True,
                "delivery_does_not_count_as_g2_until_validated": True,
            },
        })

    packets.sort(key=lambda packet: packet["route"])
    return {
        "schema_version": "1",
        "purpose": (
            "Vendor quote/order packets for G2_CHAMPION_MINIMUM. "
            "These packets request scope only; they do not authorize purchase or claim coverage."
        ),
        "packet_count": len(packets),
        "champion_minimum_source_date_rows": sum(p["source_date_rows"] for p in packets),
        "total_record_kind_symbol_date_pairs": sum(p["symbol_date_pair_count"] for p in packets),
        "packets": packets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build G2 vendor quote/order packets.")
    parser.add_argument("--vendor-dir", type=Path, default=DEFAULT_VENDOR_DIR)
    parser.add_argument("--source-blueprint", type=Path, default=DEFAULT_SOURCE_BLUEPRINT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = build_packets(args.vendor_dir, args.source_blueprint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
