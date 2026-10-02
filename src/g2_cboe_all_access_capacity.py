from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)

HISTORICAL_POINTS_PER_REQUEST = 15
TIER3_MONTHLY_POINTS = 1_250_000
TIER3_MONTHLY_BASE_USD = 2_499
PAGE_LIMIT_ROWS = 10_000
HISTORICAL_START_YEAR = 2003
OPRA_EARLIEST_YEAR = 2012

FREE_TRIAL_POINTS_PER_DAY = 500
FREE_TRIAL_DAYS = 14


def load_requirements(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"record_kind", "trade_date", "historical_symbols", "symbol_date_pair_count"}
    if not rows:
        raise ValueError("requirements file is empty")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"requirements file missing columns: {missing}")
    return rows


def build_capacity(rows: list[dict[str, str]]) -> dict:
    if len(rows) != 1242:
        raise ValueError(f"expected canonical champion-minimum 1242 rows, found {len(rows)}")

    equity_trades = [r for r in rows if r["record_kind"] == "equity_trade"]
    equity_quotes = [r for r in rows if r["record_kind"] == "equity_quote"]
    option_trades = [r for r in rows if r["record_kind"] == "option_trade"]
    cboe_option_trades = [r for r in option_trades if r["trade_date"] >= "2012-01-01"]
    unsupported_option_trades = [r for r in option_trades if r["trade_date"] < "2012-01-01"]

    if len(equity_trades) != 414 or len(equity_quotes) != 414 or len(option_trades) != 414:
        raise ValueError("unexpected champion-minimum record-kind counts")

    equity_pairs = sum(int(r["symbol_date_pair_count"]) for r in equity_trades)
    equity_quote_pairs = sum(int(r["symbol_date_pair_count"]) for r in equity_quotes)
    option_pairs = sum(int(r["symbol_date_pair_count"]) for r in option_trades)
    cboe_option_pairs = sum(int(r["symbol_date_pair_count"]) for r in cboe_option_trades)
    unsupported_option_pairs = sum(
        int(r["symbol_date_pair_count"]) for r in unsupported_option_trades
    )
    if equity_pairs != equity_quote_pairs:
        raise ValueError("equity trade/quote pair counts do not reconcile")

    # One historical trades-and-quotes request per equity symbol/date can carry
    # both the equity_trade and equity_quote raw events needed downstream.
    first_page_requests = equity_pairs + cboe_option_pairs
    first_page_points = first_page_requests * HISTORICAL_POINTS_PER_REQUEST
    max_tier3_requests = TIER3_MONTHLY_POINTS // HISTORICAL_POINTS_PER_REQUEST
    spare_requests = max_tier3_requests - first_page_requests

    sample_date = "2012-01-03"
    sample_symbol = "AF"

    return {
        "schema_version": "1",
        "purpose": (
            "Capacity model for using one Cboe All Access Tier 3 month as a candidate "
            "Cboe-supported acquisition subset for G2_CHAMPION_MINIMUM. Cboe-confirmed "
            "OPRA history begins in 2012, so 2011 option trades remain outside this model. "
            "This is not a purchase, authorization claim, or G2 coverage receipt."
        ),
        "documented_vendor_facts": {
            "historical_start_year": HISTORICAL_START_YEAR,
            "vendor_confirmed_opra_earliest_year": OPRA_EARLIEST_YEAR,
            "historical_points_per_request": HISTORICAL_POINTS_PER_REQUEST,
            "response_page_limit_rows": PAGE_LIMIT_ROWS,
            "tier3_monthly_points": TIER3_MONTHLY_POINTS,
            "tier3_monthly_base_usd": TIER3_MONTHLY_BASE_USD,
            "free_trial_points_per_day": FREE_TRIAL_POINTS_PER_DAY,
            "free_trial_days": FREE_TRIAL_DAYS,
        },
        "frozen_scope": {
            "champion_minimum_source_date_rows": len(rows),
            "equity_source_date_rows": len(equity_trades) + len(equity_quotes),
            "option_trade_source_date_rows": len(option_trades),
            "cboe_supported_option_trade_source_date_rows": len(cboe_option_trades),
            "unsupported_2011_option_trade_source_date_rows": len(unsupported_option_trades),
            "equity_symbol_date_pairs": equity_pairs,
            "option_symbol_date_pairs": option_pairs,
            "cboe_supported_option_symbol_date_pairs": cboe_option_pairs,
            "unsupported_2011_option_symbol_date_pairs": unsupported_option_pairs,
        },
        "candidate_request_model": {
            "equity_endpoint": "time-and-sales/trades-and-quotes",
            "equity_mode": "ALL_QUOTES",
            "equity_first_page_requests": equity_pairs,
            "equity_first_page_points": equity_pairs * HISTORICAL_POINTS_PER_REQUEST,
            "option_endpoint": "time-and-sales/option-trades",
            "option_first_page_requests": cboe_option_pairs,
            "option_first_page_points": cboe_option_pairs * HISTORICAL_POINTS_PER_REQUEST,
            "total_first_page_requests": first_page_requests,
            "total_first_page_points": first_page_points,
            "tier3_first_page_point_fraction": first_page_points / TIER3_MONTHLY_POINTS,
            "tier3_max_15_point_requests": max_tier3_requests,
            "tier3_spare_15_point_requests_after_first_pages": spare_requests,
            "average_total_pages_per_symbol_date_pair_supported": max_tier3_requests / first_page_requests,
            "average_extra_pages_per_symbol_date_pair_supported": spare_requests / first_page_requests,
        },
        "free_trial_acceptance_probe": {
            "total_points": 2 * HISTORICAL_POINTS_PER_REQUEST,
            "equity": {
                "date": sample_date,
                "symbol": sample_symbol,
                "endpoint": "time-and-sales/trades-and-quotes",
                "mode": "ALL_QUOTES",
                "limit": PAGE_LIMIT_ROWS,
                "required_fields": [
                    "timestamp",
                    "underlying_trade_price",
                    "underlying_trade_size",
                    "bid",
                    "ask",
                    "bid_size",
                    "ask_size",
                ],
            },
            "option": {
                "date": sample_date,
                "symbol": sample_symbol,
                "endpoint": "time-and-sales/option-trades",
                "limit": PAGE_LIMIT_ROWS,
                "required_fields": [
                    "timestamp",
                    "security",
                    "root",
                    "expiry",
                    "strike",
                    "option_type",
                    "option_trade_price",
                    "option_trade_size",
                ],
            },
        },
        "out_of_scope": {
            "option_trade_source_date_rows": len(unsupported_option_trades),
            "option_symbol_date_pairs": unsupported_option_pairs,
            "historical_range": [
                min(r["trade_date"] for r in unsupported_option_trades),
                max(r["trade_date"] for r in unsupported_option_trades),
            ],
            "reason": "Cboe Data Vantage confirmed OPRA-related datasets begin in 2012.",
        },
        "gates_before_purchase": [
            "Run the two-request free-trial acceptance probe and verify historical response fields are populated without live/delayed SIP entitlements.",
            "Verify pagination semantics and next-sequence handling on at least one response that reaches the 10,000-row limit.",
            "Map Cboe response types to the production historical_market_backfill canonical fields and pass content validation.",
            "Confirm the subscription/license_reference permits the intended internal historical research use.",
            "Keep the 2011 option-trade slice on a separate source route; Cboe does not supply that OPRA period.",
        ],
        "warning": (
            "Point capacity alone does not establish completeness. High-volume symbol/dates may need "
            "multiple 15-point pages, and a paid plan must not be purchased until the free-trial "
            "acceptance checks prove historical field availability and parser compatibility."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Model Cboe All Access capacity for G2 champion minimum.")
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = build_capacity(load_requirements(args.requirements))
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
