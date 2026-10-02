from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)

TRIAL_DAYS = 14
PUBLISHED_TRIAL_POINTS_PER_DAY = 500
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
OPRA_HISTORY_REPLY_DATE = "2026-09-30"
TRIAL_LIMIT_CLARIFICATION_DATE = "2026-10-02"


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"record_kind", "trade_date", "symbol_date_pair_count"}
    if not rows:
        raise ValueError(f"{path}: empty manifest")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    return rows


def _eligible_option_trades(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    eligible = [
        row
        for row in rows
        if row["record_kind"] == "option_trade"
        and row["trade_date"] >= f"{OPRA_EARLIEST_YEAR}-01-01"
    ]
    if not eligible:
        raise ValueError("no Cboe-eligible option_trade rows")
    return sorted(eligible, key=lambda row: row["trade_date"])


def plan(rows: list[dict[str, str]]) -> dict:
    eligible = _eligible_option_trades(rows)
    trade_dates = [row["trade_date"] for row in eligible]
    first_page_requests = sum(int(row["symbol_date_pair_count"]) for row in eligible)
    nominal_points = first_page_requests * HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST

    return {
        "schema_version": "3",
        "purpose": (
            "Planning-only Cboe All Access API free-trial candidate scope for the frozen "
            "G2 option-trade requirements from the vendor-confirmed 2012 OPRA history floor. "
            "This is not a coverage claim and performs no API call."
        ),
        "sources": {
            "all_access_product": ALL_ACCESS_PRODUCT_URL,
            "option_trades_reference": OPTION_TRADES_REFERENCE_URL,
            "opra_history_vendor_reply": (
                "Ryan Lusk, Cboe Data Vantage, email received 2026-09-30: "
                "OPRA-related datasets are available from 2012 onward."
            ),
            "trial_credit_limit_vendor_reply": (
                "Ryan Lusk, Cboe Data Vantage, email received 2026-10-02: the All Access "
                "historical trial should work; select Allow for exceeding the daily credit limit, "
                "and the daily credit limit does not matter during the trial phase."
            ),
        },
        "provenance_reconciliation": {
            "vendor_confirmed_opra_earliest_year": OPRA_EARLIEST_YEAR,
            "opra_history_reply_date": OPRA_HISTORY_REPLY_DATE,
            "trial_limit_clarification_date": TRIAL_LIMIT_CLARIFICATION_DATE,
            "public_option_trades_reference_generic_earliest_year": 2003,
            "planner_earliest_year": OPRA_EARLIEST_YEAR,
            "manifest_first_date": trade_dates[0],
            "manifest_last_date": trade_dates[-1],
        },
        "documented_trial": {
            "days": TRIAL_DAYS,
            "published_points_per_day": PUBLISHED_TRIAL_POINTS_PER_DAY,
            "credit_card_authorization_required": True,
            "trial_sip_access": False,
            "signup_exceed_daily_credit_limit_setting": "ALLOW",
            "vendor_confirmed_daily_credit_limit_gates_trial": False,
            "historical_option_trades_access": "VENDOR_CONFIRMED_ELIGIBLE_RUNTIME_NOT_VERIFIED",
        },
        "documented_historical_option_trades": {
            "earliest_year": OPRA_EARLIEST_YEAR,
            "points_per_request": HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST,
            "symbol_parameter": "single underlying symbol or OSI option string",
            "max_records_per_request": MAX_RECORDS_PER_REQUEST,
            "pagination_parameter": "seq_no",
            "pagination_points_per_page": HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST,
        },
        "capacity_model": {
            "published_daily_point_limit_used_as_hard_trial_cap": False,
            "reason": (
                "Vendor clarification states the daily credit limit does not matter during the "
                "trial phase when signup is configured to Allow exceeding the limit."
            ),
            "required_first_page_requests": first_page_requests,
            "nominal_first_page_points": nominal_points,
            "average_first_page_requests_per_trial_day": first_page_requests / TRIAL_DAYS,
            "candidate_complete_source_date_rows": len(eligible),
            "candidate_complete_underlying_date_pairs": first_page_requests,
            "remaining_source_date_rows_due_to_credit_limit": 0,
            "remaining_underlying_date_pairs_due_to_credit_limit": 0,
        },
        "pagination_verified": True,
        "trial_historical_access_runtime_verified": False,
        "per_pair_record_counts_known": False,
        "coverage_claimed": False,
        "required_source_date_rows": len(eligible),
        "required_underlying_date_pairs": first_page_requests,
        "candidate_complete_source_date_rows": len(eligible),
        "candidate_complete_underlying_date_pairs": first_page_requests,
        "remaining_source_date_rows": 0,
        "remaining_underlying_date_pairs": 0,
        "selected_dates": trade_dates,
        "gates_before_use": [
            "Explicit user authorization is required before trial activation.",
            "Run the merged two-request historical acceptance probe and verify required fields.",
            "Verify seq_no pagination on a response that reaches the 10,000-row limit.",
            "Confirm trial/license terms permit the intended internal historical research use.",
            "Delivered rows must pass production date, symbol, schema, and content validation.",
        ],
        "warning": (
            "Vendor confirmation removes the old 500-points/day capacity ceiling from planning, "
            "but it does not prove runtime access, pagination completeness, request-rate behavior, "
            "license suitability, or G2 coverage."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan Cboe All Access trial candidate scope for frozen G2 option trades."
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
