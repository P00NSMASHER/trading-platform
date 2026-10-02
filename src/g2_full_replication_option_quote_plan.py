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
        planned.append(
            {
                "trade_date": row["trade_date"],
                "record_kind": "option_quote",
                "historical_symbols": row["historical_symbols"],
                "unique_symbol_count": row["unique_symbol_count"],
                "symbol_date_pair_count": row["symbol_date_pair_count"],
                "route": "candidate_lseg_opra_tick_history_option_quotes",
                "candidate_source_family": "generic_authorized_market_data",
            }
        )

    planned.sort(key=lambda row: row["trade_date"])
    pairs = sum(int(row["symbol_date_pair_count"]) for row in planned)

    y2011 = [row for row in planned if row["trade_date"] < "2012-01-01"]
    later = [row for row in planned if row["trade_date"] >= "2012-01-01"]

    summary = {
        "schema_version": "1",
        "purpose": (
            "Deterministic candidate-source plan for the 414 option_quote rows required only "
            "by G2_FULL_REPLICATION. This does not alter G2_CHAMPION_MINIMUM or claim coverage."
        ),
        "full_replication_option_quote_source_date_rows": len(planned),
        "full_replication_option_quote_symbol_date_pairs": pairs,
        "unique_historical_underlyings": len(symbols),
        "first_trade_date": planned[0]["trade_date"],
        "last_trade_date": planned[-1]["trade_date"],
        "preferred_candidate": {
            "vendor": "LSEG",
            "product": "OPRA Tick History",
            "route": "candidate_lseg_opra_tick_history_option_quotes",
            "source_family": "generic_authorized_market_data",
            "current_documented_history": "Tick History from 1997",
            "content": "OPRA quotes/NBBO and full-tick workflows where licensed",
            "product_url": LSEG_PRODUCT_URL,
            "developer_reference_url": LSEG_TICK_HISTORY_URL,
            "status": "CANDIDATE_SOURCE_AVAILABLE_NOT_ACQUIRED",
        },
        "slices": {
            "2011": {
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
        "cost_aware_candidate_split": {
            "2011": {
                "vendor": "LSEG",
                "product": "OPRA Tick History",
                "source_date_rows": len(y2011),
                "symbol_date_pair_count": sum(
                    int(row["symbol_date_pair_count"]) for row in y2011
                ),
                "documented_history": "Tick History from 1997",
                "status": "QUOTE_LICENSE_DELIVERY_PENDING",
            },
            "2012_2015": {
                "vendor": "algoseek",
                "product": "US Options Trade and NBBO Quote",
                "source_date_rows": len(later),
                "symbol_date_pair_count": sum(
                    int(row["symbol_date_pair_count"]) for row in later
                ),
                "documented_history": (
                    "Dataset-specific TANQ start recorded as 2012-01-01; generic algoseek "
                    "marketing also states 2014 for lossless OPRA history, so delivered dates "
                    "must be validated before any coverage claim."
                ),
                "status": "QUOTE_LICENSE_DELIVERY_PENDING",
            },
            "selection_policy": (
                "Cost-aware acquisition preference only. LSEG remains the conservative all-years "
                "candidate above; neither split route counts as coverage until licensing, delivery, "
                "and content validation pass."
            ),
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
            "canonical_full_g2_gate_unchanged": True,
            "cost_aware_split_is_not_authorization": True,
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
