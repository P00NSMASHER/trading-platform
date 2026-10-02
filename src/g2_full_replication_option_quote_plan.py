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
THETADATA_OPTIONS_DOC_URL = (
    "https://docs.thetadata.us/Articles/Getting-Started/Subscriptions.html"
)
THETADATA_QUOTE_DOC_URL = (
    "https://docs.thetadata.us/operations/option_history_quote.html"
)
THETADATA_PRICING_URL = "https://thetadata.net/pricing"
THETADATA_FIRST_ACCESS = "2012-06-01"
ALGOSEEK_TANQ_DATASET_URL = (
    "https://algoseek.com/dataset/us-options-trade-and-nbbo-quote/"
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


def _route_for_date(trade_date: str) -> str:
    if trade_date < THETADATA_FIRST_ACCESS:
        return "candidate_lseg_opra_tick_history_option_quotes"
    return "candidate_thetadata_options_pro_option_quotes"


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
                "route": _route_for_date(row["trade_date"]),
                "candidate_source_family": "generic_authorized_market_data",
            }
        )

    planned.sort(key=lambda row: row["trade_date"])
    pairs = sum(int(row["symbol_date_pair_count"]) for row in planned)

    pre_theta = [row for row in planned if row["trade_date"] < THETADATA_FIRST_ACCESS]
    theta = [row for row in planned if row["trade_date"] >= THETADATA_FIRST_ACCESS]

    summary = {
        "schema_version": "3",
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
                "first_trade_date": pre_theta[0]["trade_date"],
                "last_trade_date": pre_theta[-1]["trade_date"],
                "source_date_rows": len(pre_theta),
                "symbol_date_pair_count": sum(
                    int(row["symbol_date_pair_count"]) for row in pre_theta
                ),
                "source_family": "generic_authorized_market_data",
                "history_basis": (
                    "LSEG Tick History is the residual candidate before ThetaData's "
                    "documented 2012-06-01 tick-history floor."
                ),
                "product_url": LSEG_PRODUCT_URL,
                "developer_reference_url": LSEG_TICK_HISTORY_URL,
                "status": "CANDIDATE_SOURCE_AVAILABLE_NOT_ACQUIRED",
            },
            {
                "vendor": "ThetaData",
                "product": "Options Pro historical quote",
                "route": "candidate_thetadata_options_pro_option_quotes",
                "first_trade_date": theta[0]["trade_date"],
                "last_trade_date": theta[-1]["trade_date"],
                "source_date_rows": len(theta),
                "symbol_date_pair_count": sum(
                    int(row["symbol_date_pair_count"]) for row in theta
                ),
                "source_family": "generic_authorized_market_data",
                "history_basis": (
                    "ThetaData documents Options PRO tick-level history from 2012-06-01; "
                    "the historical Quote endpoint returns every OPRA NBBO quote with "
                    "bid/ask prices and sizes."
                ),
                "subscription_reference_url": THETADATA_OPTIONS_DOC_URL,
                "quote_schema_url": THETADATA_QUOTE_DOC_URL,
                "pricing_url": THETADATA_PRICING_URL,
                "license_status": "PENDING_WRITTEN_USE_CLASSIFICATION_AND_RETENTION_TERMS",
                "status": "CANDIDATE_SOURCE_AVAILABLE_NOT_ACQUIRED",
            },
        ],
        "fallback_candidates": [
            {
                "vendor": "algoseek",
                "product": "US Options Trade and NBBO Quote",
                "route": "candidate_algoseek_us_options_tanq",
                "eligible_start": "2012-01-01",
                "product_url": ALGOSEEK_TANQ_DATASET_URL,
                "reason": (
                    "Dataset-specific coverage reaches 2012 and satisfies tick NBBO fidelity, "
                    "but current published recurring pricing is materially higher than ThetaData "
                    "and the free Sandbox is not assumed to expose a selectable 2011-2015 year."
                ),
                "status": "FALLBACK_QUOTE_REQUIRED_NOT_ACQUIRED",
            }
        ],
        "slices": {
            "pre_2012_06_01": {
                "route": "candidate_lseg_opra_tick_history_option_quotes",
                "source_date_rows": len(pre_theta),
                "symbol_date_pair_count": sum(
                    int(row["symbol_date_pair_count"]) for row in pre_theta
                ),
                "unique_historical_underlyings": len(
                    {
                        symbol
                        for row in pre_theta
                        for symbol in row["historical_symbols"].split(";")
                        if symbol
                    }
                ),
            },
            "2012_06_01_onward": {
                "route": "candidate_thetadata_options_pro_option_quotes",
                "source_date_rows": len(theta),
                "symbol_date_pair_count": sum(
                    int(row["symbol_date_pair_count"]) for row in theta
                ),
                "unique_historical_underlyings": len(
                    {
                        symbol
                        for row in theta
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
            "thetadata_retail_license_not_assumed": True,
            "retention_rights_not_assumed": True,
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
