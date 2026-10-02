from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)

MASSIVE_HISTORY_START = "2003-09-10"
INDIVIDUAL_ADVANCED_USD_PER_MONTH = 199
BUSINESS_USD_PER_MONTH = 2499

SOURCES = {
    "stocks_overview": "https://massive.com/stocks",
    "stocks_pricing": "https://massive.com/pricing?product=stocks",
    "business_pricing": "https://massive.com/business",
    "trades_flat_files": "https://massive.com/docs/flat-files/stocks/trades",
    "quotes_flat_files": "https://massive.com/docs/flat-files/stocks/quotes",
}


def load_requirements(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "record_kind",
        "trade_date",
        "historical_symbols",
        "symbol_date_pair_count",
    }
    if not rows:
        raise ValueError("requirements file is empty")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"requirements file missing columns: {missing}")
    return rows


def build_plan(rows: list[dict[str, str]]) -> dict:
    equity = [
        row for row in rows if row["record_kind"] in {"equity_trade", "equity_quote"}
    ]
    if not equity:
        raise ValueError("requirements contain no equity rows")

    trade_rows = [row for row in equity if row["record_kind"] == "equity_trade"]
    quote_rows = [row for row in equity if row["record_kind"] == "equity_quote"]
    trade_by_date = {row["trade_date"]: row for row in trade_rows}
    quote_by_date = {row["trade_date"]: row for row in quote_rows}

    if set(trade_by_date) != set(quote_by_date):
        raise ValueError("equity trade/quote date sets differ")

    unique_symbols: set[str] = set()
    pair_count = 0
    for day in sorted(trade_by_date):
        trade = trade_by_date[day]
        quote = quote_by_date[day]
        if trade["historical_symbols"] != quote["historical_symbols"]:
            raise ValueError(f"{day}: equity trade/quote symbol sets differ")
        pair_count += int(trade["symbol_date_pair_count"])
        unique_symbols.update(
            symbol for symbol in trade["historical_symbols"].split(";") if symbol
        )

    earliest = min(trade_by_date)
    latest = max(trade_by_date)
    if earliest < MASSIVE_HISTORY_START:
        raise ValueError(
            f"frozen requirement starts {earliest}, before Massive history floor "
            f"{MASSIVE_HISTORY_START}"
        )

    return {
        "schema_version": "1",
        "purpose": (
            "No-purchase cost/coverage plan for using Massive historical U.S. stocks data "
            "as a G2_CHAMPION_MINIMUM equity candidate. This does not assert subscription "
            "eligibility, entitlement, licensing, delivery, or validated G2 coverage."
        ),
        "frozen_scope": {
            "equity_trade_source_date_rows": len(trade_rows),
            "equity_quote_source_date_rows": len(quote_rows),
            "equity_source_date_rows_total": len(equity),
            "equity_symbol_date_pairs_per_record_kind": pair_count,
            "unique_historical_symbols": len(unique_symbols),
            "first_required_date": earliest,
            "last_required_date": latest,
        },
        "candidate": {
            "vendor": "Massive",
            "source_family": "generic_authorized_market_data",
            "history_start": MASSIVE_HISTORY_START,
            "active_and_delisted_tickers_documented": True,
            "tick_trades_documented": True,
            "nbbo_quotes_documented": True,
            "individual_advanced": {
                "published_monthly_usd": INDIVIDUAL_ADVANCED_USD_PER_MONTH,
                "eligibility": "individual_use_non_pros_only",
                "g2_purchase_status": "NOT_PURCHASED",
            },
            "business": {
                "published_monthly_usd": BUSINESS_USD_PER_MONTH,
                "eligibility": "business_use",
                "g2_purchase_status": "NOT_PURCHASED",
            },
            "selection_rule": (
                "Use the $199 individual route only if the account/use case independently "
                "qualifies for Massive's individual non-professional terms. Otherwise price "
                "the business route or another vendor. Never infer eligibility from repository "
                "purpose or user status."
            ),
            "coverage_status": "CANDIDATE_NOT_COUNTED",
            "activation_requirements": [
                "explicitly verified license/plan eligibility",
                "authorized historical data entitlement",
                "nonblank license reference",
                "exact delivered-file SHA-256 binding",
                "canonical trade and quote schema validation",
                "all required historical symbols observed for each required date",
            ],
        },
        "sources": SOURCES,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a no-purchase Massive equity candidate plan for G2."
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = build_plan(load_requirements(args.requirements))
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
