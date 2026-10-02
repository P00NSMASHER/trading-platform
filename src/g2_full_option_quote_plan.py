from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"
)
DEFAULT_SOURCE_BLUEPRINT = Path(
    "data/processed/real_data_release_sprint/production_source_contract_blueprint.json"
)

ROUTES = (
    {
        "route": "candidate_lseg_opra_tick_quotes_2011",
        "vendor": "LSEG Tick History",
        "product_request": "OPRA consolidated tick-level option quotes",
        "source_family": "generic_authorized_market_data",
        "start": date(2011, 1, 1),
        "end": date(2011, 12, 31),
        "acquisition_status": "QUOTE_REQUESTED_AVAILABILITY_PRICING_PENDING",
    },
    {
        "route": "candidate_algoseek_opra_tick_quotes_2012_2015",
        "vendor": "algoseek",
        "product_request": "US Options Trade and NBBO Quote tick data",
        "source_family": "generic_authorized_market_data",
        "start": date(2012, 1, 1),
        "end": date(2015, 12, 31),
        "acquisition_status": "QUOTE_AND_SANDBOX_TERMS_REQUESTED",
    },
)

FIDELITY_REQUIREMENTS = [
    "tick-level quote updates",
    "underlying and option contract identifiers",
    "expiration, strike, and option type",
    "bid and ask prices with bid_size and ask_size",
    "all requested underlyings and dates",
    "no minute-bar or interval-snapshot substitution",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path}: empty requirements")
    return rows


def _route_for(day: date) -> dict:
    matches = [route for route in ROUTES if route["start"] <= day <= route["end"]]
    if len(matches) != 1:
        raise ValueError(f"{day.isoformat()}: expected exactly one quote route")
    return matches[0]


def build_plan(requirements: Path, source_blueprint: Path) -> dict:
    rows = [row for row in _read_csv(requirements) if row["record_kind"] == "option_quote"]
    if not rows:
        raise ValueError("requirements contain no option_quote rows")

    blueprint = json.loads(source_blueprint.read_text(encoding="utf-8"))
    required_fields = blueprint["source_types"]["option_quote"]["required_canonical_fields"]

    grouped: dict[str, list[dict[str, str]]] = {route["route"]: [] for route in ROUTES}
    for row in rows:
        day = date.fromisoformat(row["trade_date"])
        grouped[_route_for(day)["route"]].append(row)

    packets = []
    for route in ROUTES:
        route_rows = grouped[route["route"]]
        if not route_rows:
            raise ValueError(f"{route['route']}: empty route")
        dates = sorted(row["trade_date"] for row in route_rows)
        symbols = sorted(
            {
                symbol
                for row in route_rows
                for symbol in row["historical_symbols"].split(";")
                if symbol
            }
        )
        packets.append(
            {
                "route": route["route"],
                "vendor": route["vendor"],
                "product_request": route["product_request"],
                "source_family": route["source_family"],
                "record_kind": "option_quote",
                "first_trade_date": dates[0],
                "last_trade_date": dates[-1],
                "source_date_rows": len(route_rows),
                "symbol_date_pair_count": sum(
                    int(row["symbol_date_pair_count"]) for row in route_rows
                ),
                "unique_historical_symbols": len(symbols),
                "required_canonical_fields": required_fields,
                "fidelity_requirements": FIDELITY_REQUIREMENTS,
                "acquisition_status": route["acquisition_status"],
                "request_policy": {
                    "quote_or_availability_request_only": True,
                    "do_not_purchase_automatically": True,
                    "license_terms_must_be_reviewed": True,
                    "delivery_does_not_count_as_g2_until_validated": True,
                },
            }
        )

    return {
        "schema_version": "1",
        "purpose": (
            "Planning-only vendor split for the 414 option_quote rows that are required for "
            "G2_FULL_REPLICATION but intentionally excluded from the 1,242-row "
            "G2_CHAMPION_MINIMUM acquisition plan. This artifact does not authorize purchase "
            "or claim coverage."
        ),
        "champion_minimum_source_date_rows": 1242,
        "full_replication_source_date_rows": 1656,
        "additional_option_quote_source_date_rows": len(rows),
        "additional_option_quote_symbol_date_pairs": sum(
            int(row["symbol_date_pair_count"]) for row in rows
        ),
        "packet_count": len(packets),
        "packets": packets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the fail-closed G2 full-replication option-quote vendor plan."
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--source-blueprint", type=Path, default=DEFAULT_SOURCE_BLUEPRINT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = build_plan(args.requirements, args.source_blueprint)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
