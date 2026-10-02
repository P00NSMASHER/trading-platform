from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"
)

LSEG_PRODUCT_URL = (
    "https://www.lseg.com/en/data-catalogue/derivatives/pricing/"
    "exchange-derivatives-options-price-reporting-authority-opra"
)
LSEG_TICK_HISTORY_URL = (
    "https://developers.lseg.com/en/article-catalog/article/"
    "options-tick-history-rest-api-python"
)
ALGOSEEK_OPTIONS_REFERENCE_URL = (
    "https://algoseek.com/docs/rest-api/reference/equity-options"
)
ALGOSEEK_TANQ_DATASET_URL = (
    "https://algoseek.com/dataset/us-options-trade-and-nbbo-quote/"
)
ALGOSEEK_TANQ_START = "2012-01-01"

FIELDS = [
    "trade_date",
    "record_kind",
    "historical_symbols",
    "unique_symbol_count",
    "symbol_date_pair_count",
    "route",
    "candidate_source_family",
]


def load_requirements(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("requirements file is empty")
    required = {
        "trade_date",
        "record_kind",
        "historical_symbols",
        "unique_symbol_count",
        "symbol_date_pair_count",
    }
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"requirements file missing columns: {missing}")
    return rows


def _route_for_date(trade_date: str) -> tuple[str, str]:
    if trade_date < ALGOSEEK_TANQ_START:
        return (
            "candidate_lseg_opra_tick_history_option_quotes",
            "LSEG Tick History",
        )
    return (
        "candidate_algoseek_us_options_tanq",
        "algoseek US Options Trade and NBBO Quote",
    )


def build_plan(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict]:
    quotes = [row for row in rows if row["record_kind"] == "option_quote"]
    if len(quotes) != 414:
        raise ValueError(f"expected 414 option_quote rows, found {len(quotes)}")

    planned = []
    symbols = set()
    for row in quotes:
        row_symbols = [s for s in row["historical_symbols"].split(";") if s]
        if int(row["unique_symbol_count"]) != len(row_symbols):
            raise ValueError(
                f"{row['trade_date']}: unique_symbol_count does not match historical_symbols"
            )
        symbols.update(row_symbols)
        route, _ = _route_for_date(row["trade_date"])
        planned.append(
            {
                "trade_date": row["trade_date"],
                "record_kind": "option_quote",
                "historical_symbols": row["historical_symbols"],
                "unique_symbol_count": row["unique_symbol_count"],
                "symbol_date_pair_count": row["symbol_date_pair_count"],
                "route": route,
                "candidate_source_family": "generic_authorized_market_data",
            }
        )

    planned.sort(key=lambda row: row["trade_date"])
    pairs = sum(int(row["symbol_date_pair_count"]) for row in planned)

    y2011 = [row for row in planned if row["trade_date"] < ALGOSEEK_TANQ_START]
    later = [row for row in planned if row["trade_date"] >= ALGOSEEK_TANQ_START]

    summary = {
        "schema_version": "2",
        "purpose": (
            "Deterministic cheap-first candidate-source plan for the 414 option_quote rows "
            "required only by G2_FULL_REPLICATION. This does not alter G2_CHAMPION_MINIMUM "
            "or claim coverage."
        ),
        "full_replication_option_quote_source_date_rows": len(planned),
        "full_replication_option_quote_symbol_date_pairs": pairs,
        "unique_historical_underlyings": len(symbols),
        "first_trade_date": planned[0]["trade_date"],
        "last_trade_date": planned[-1]["trade_date"],
        "preferred_candidate_split": [
            {
                "vendor": "LSEG",
                "product": "OPRA Tick History",
                "route": "candidate_lseg_opra_tick_history_option_quotes",
                "first_trade_date": y2011[0]["trade_date"],
                "last_trade_date": y2011[-1]["trade_date"],
                "source_date_rows": len(y2011),
                "symbol_date_pair_count": sum(
                    int(row["symbol_date_pair_count"]) for row in y2011
                ),
                "source_family": "generic_authorized_market_data",
                "history_basis": "Tick History covers the 2011 residual.",
                "product_url": LSEG_PRODUCT_URL,
                "developer_reference_url": LSEG_TICK_HISTORY_URL,
                "status": "CANDIDATE_SOURCE_AVAILABLE_NOT_ACQUIRED",
            },
            {
                "vendor": "algoseek",
                "product": "US Options Trade and NBBO Quote",
                "route": "candidate_algoseek_us_options_tanq",
                "first_trade_date": later[0]["trade_date"],
                "last_trade_date": later[-1]["trade_date"],
                "source_date_rows": len(later),
                "symbol_date_pair_count": sum(
                    int(row["symbol_date_pair_count"]) for row in later
                ),
                "source_family": "generic_authorized_market_data",
                "history_basis": (
                    "Dataset-specific algoseek options documentation and console list "
                    "U.S. equity-options coverage and TANQ from 2012; generic marketing "
                    "copy that says 2014 is treated as conflicting evidence requiring "
                    "delivery validation."
                ),
                "product_url": ALGOSEEK_TANQ_DATASET_URL,
                "reference_url": ALGOSEEK_OPTIONS_REFERENCE_URL,
                "status": "CANDIDATE_SOURCE_AVAILABLE_NOT_ACQUIRED",
            },
        ],
        "slices": {
            "2011": {
                "route": "candidate_lseg_opra_tick_history_option_quotes",
                "source_date_rows": len(y2011),
                "symbol_date_pair_count": sum(
                    int(row["symbol_date_pair_count"]) for row in y2011
                ),
                "unique_historical_underlyings": len(
                    {
                        symbol
                        for row in y2011
                        for symbol in row["historical_symbols"].split(";")
                        if symbol
                    }
                ),
            },
            "2012_2015": {
                "route": "candidate_algoseek_us_options_tanq",
                "source_date_rows": len(later),
                "symbol_date_pair_count": sum(
                    int(row["symbol_date_pair_count"]) for row in later
                ),
                "unique_historical_underlyings": len(
                    {
                        symbol
                        for row in later
                        for symbol in row["historical_symbols"].split(";")
                        if symbol
                    }
                ),
            },
        },
        "fidelity_requirement": {
            "tick_level_option_quote_updates": True,
            "required_fields": [
                "timestamp_or_date+time",
                "underlying_symbol",
                "option_symbol",
                "expiration",
                "strike",
                "option_type",
                "bid",
                "ask",
                "bid_size",
                "ask_size",
            ],
            "minute_snapshot_substitution_allowed": False,
        },
        "policy": {
            "candidate_source_is_not_coverage": True,
            "purchase_not_authorized": True,
            "license_and_delivery_validation_required": True,
            "conflicting_public_history_copy_requires_runtime_date_validation": True,
            "canonical_full_g2_gate_unchanged": True,
        },
    }
    return planned, summary


def write_plan(rows: list[dict[str, str]], output_csv: Path, output_summary: Path) -> dict:
    planned, summary = build_plan(rows)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(planned)
    output_summary.parent.mkdir(parents=True, exist_ok=True)
    output_summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the G2 full-replication option-quote candidate-source plan."
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-summary", type=Path, required=True)
    args = parser.parse_args()

    summary = write_plan(
        load_requirements(args.requirements),
        args.output_csv,
        args.output_summary,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
