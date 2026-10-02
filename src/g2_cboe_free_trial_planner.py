from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_REQUIREMENTS = Path("data/processed/g2_vendor_requests/cboe_option_trades.csv")

TRIAL_DAYS = 14
TRIAL_POINTS_PER_DAY = 500
HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST = 15
MAX_RECORDS_PER_REQUEST = 10000
OPRA_EARLIEST_YEAR = 2012
ALL_ACCESS_PRODUCT_URL = "https://datashop.cboe.com/cboe-all-access-api"
OPTION_TRADES_REFERENCE_URL = (
    "https://api.livevol.com/v1/docs/Help/Api/"
    "GET-allaccess-time-and-sales-option-trades_symbol_root_expiry_strike_option_type_"
    "min_time_max_time_seq_no_exchange_id_condition_id_limit_min_size_max_size_min_price_"
    "max_price_date?apiGroupName=allaccess"
)
VENDOR_REPLY_DATE = "2026-09-30"
VENDOR_TRIAL_CONFIRMATION_DATE = "2026-10-02"


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"trade_date", "symbol_date_pair_count"}
    if not rows:
        raise ValueError(f"{path}: empty manifest")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    return rows


def plan(rows: list[dict[str, str]]) -> dict:
    per_day_request_budget = TRIAL_POINTS_PER_DAY // HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST
    request_budget = TRIAL_DAYS * per_day_request_budget

    ranked = sorted(
        (
            {
                "trade_date": row["trade_date"],
                "symbol_date_pair_count": int(row["symbol_date_pair_count"]),
            }
            for row in rows
        ),
        key=lambda row: (row["symbol_date_pair_count"], row["trade_date"]),
    )

    prefix_request_counts = []
    running_requests = 0
    for row in ranked:
        running_requests += row["symbol_date_pair_count"]
        prefix_request_counts.append(running_requests)

    max_complete_dates_by_budget = sum(
        total <= request_budget for total in prefix_request_counts
    )
    next_complete_date_request_floor = (
        prefix_request_counts[max_complete_dates_by_budget]
        if max_complete_dates_by_budget < len(prefix_request_counts)
        else None
    )

    selected = []
    used_requests = 0
    for row in ranked:
        needed = row["symbol_date_pair_count"]
        if used_requests + needed <= request_budget:
            selected.append(row)
            used_requests += needed

    selected_dates = {row["trade_date"] for row in selected}
    remaining = [
        {
            "trade_date": row["trade_date"],
            "symbol_date_pair_count": int(row["symbol_date_pair_count"]),
        }
        for row in rows
        if row["trade_date"] not in selected_dates
    ]

    trade_dates = sorted(row["trade_date"] for row in rows)

    return {
        "schema_version": "2",
        "purpose": (
            "Planning-only Cboe All Access API free-trial capacity estimate for the frozen Cboe "
            "G2 option-trade slice. This is not a coverage claim and performs no API call."
        ),
        "sources": {
            "all_access_product": ALL_ACCESS_PRODUCT_URL,
            "option_trades_reference": OPTION_TRADES_REFERENCE_URL,
            "vendor_reply": (
                "Ryan Lusk, Cboe Data Vantage, email received 2026-09-30: OPRA-related datasets "
                "are available from 2012 onward."
            ),
            "vendor_trial_confirmation": (
                "Ryan Lusk, Cboe Data Vantage, email received 2026-10-02: the All Access trial "
                "should be able to pull historical data via API; when signing up, select Allow "
                "for exceeding the daily credit limit, which he stated does not matter during "
                "the trial phase."
            ),
        },
        "provenance_reconciliation": {
            "vendor_confirmed_opra_earliest_year": OPRA_EARLIEST_YEAR,
            "vendor_reply_date": VENDOR_REPLY_DATE,
            "vendor_trial_confirmation_date": VENDOR_TRIAL_CONFIRMATION_DATE,
            "public_option_trades_reference_generic_earliest_year": 2003,
            "planner_earliest_year": OPRA_EARLIEST_YEAR,
            "reason": (
                "The public API reference's generic 2003 history statement is not used as provenance "
                "for OPRA Option Trades. Cboe Data Vantage states OPRA-related datasets begin in 2012."
            ),
            "manifest_first_date": trade_dates[0],
            "manifest_last_date": trade_dates[-1],
        },
        "documented_trial": {
            "days": TRIAL_DAYS,
            "points_per_day": TRIAL_POINTS_PER_DAY,
            "credit_card_authorization_required": True,
            "trial_sip_access": False,
            "overage_available": False,
            "historical_option_trades_access": "vendor_confirmed_eligible_not_runtime_verified",
            "historical_access_basis": (
                "Cboe Data Vantage confirmed by email on 2026-10-02 that the All Access trial should "
                "be able to pull historical data via API. No trial was activated, so runtime response "
                "fields, completeness, pagination behavior, and point consumption remain unverified."
            ),
            "trial_signup_overage_setting": "select_allow_per_vendor_confirmation",
            "trial_signup_overage_setting_basis": (
                "Vendor stated to select Allow for exceeding the daily credit limit and that it does "
                "not matter during the trial phase; this is not treated as paid-overage authorization."
            ),
        },
        "documented_historical_option_trades": {
            "earliest_year": OPRA_EARLIEST_YEAR,
            "points_per_request": HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST,
            "symbol_parameter": "single underlying symbol or OSI option string",
            "max_records_per_request": MAX_RECORDS_PER_REQUEST,
            "pagination_parameter": "seq_no",
            "pagination_points_per_page": HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST,
            "pagination_charge_basis": (
                "Each pagination page is a separate historical Option Trades request; the endpoint "
                "charges 15 points per historical request."
            ),
        },
        "assumption": (
            "Optimistic upper-bound capacity model: one historical request per underlying/date pair "
            "using limit=10000, with no extra pagination requests. Any underlying/date producing more "
            "than 10000 trades requires another seq_no request at 15 points and reduces capacity."
        ),
        "pagination_verified": True,
        "trial_historical_access_runtime_verified": False,
        "per_pair_record_counts_known": False,
        "coverage_claimed": False,
        "required_source_date_rows": len(rows),
        "required_underlying_date_pairs": sum(int(r["symbol_date_pair_count"]) for r in rows),
        "max_requests_per_day": per_day_request_budget,
        "daily_unused_points_at_request_cap": (
            TRIAL_POINTS_PER_DAY
            - per_day_request_budget * HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST
        ),
        "optimistic_request_budget": request_budget,
        "optimality_certificate": {
            "objective": "maximize fully completed source-date rows under the optimistic one-request-per-underlying/date assumption",
            "method": "sort source dates by required underlying/date requests ascending; the k cheapest dates minimize requests for any k-date solution",
            "max_complete_source_date_rows": max_complete_dates_by_budget,
            "selected_request_count": prefix_request_counts[max_complete_dates_by_budget - 1],
            "next_complete_source_date_rows": (
                max_complete_dates_by_budget + 1
                if max_complete_dates_by_budget < len(prefix_request_counts)
                else None
            ),
            "next_complete_request_floor": next_complete_date_request_floor,
            "next_complete_exceeds_budget": (
                next_complete_date_request_floor is not None
                and next_complete_date_request_floor > request_budget
            ),
            "mathematically_optimal_under_assumption": (
                len(selected) == max_complete_dates_by_budget
            ),
        },
        "optimistic_complete_source_date_rows": len(selected),
        "optimistic_complete_underlying_date_pairs": used_requests,
        "optimistic_points_used": used_requests * HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST,
        "unused_request_slots": request_budget - used_requests,
        "remaining_source_date_rows": len(remaining),
        "remaining_underlying_date_pairs": sum(r["symbol_date_pair_count"] for r in remaining),
        "remaining_dates": remaining,
        "selected_dates": [r["trade_date"] for r in selected],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan optimistic Cboe All Access free-trial capacity for frozen G2 option trades."
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = plan(_read(args.requirements))
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
