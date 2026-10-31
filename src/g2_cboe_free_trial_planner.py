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
PUBLISHED_TRIAL_OVERAGE_AVAILABLE = False
HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST = 15
REFERENCE_OPTIONS_POINTS_PER_REQUEST = 1
HISTORICAL_OPTION_QUOTES_POINTS_PER_REQUEST = 15
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
PUBLIC_TRIAL_PAGE_RECHECK_DATE = "2026-10-05"


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


def _trade_only_first_page_budget() -> dict[str, int]:
    requests_per_day = PUBLISHED_TRIAL_POINTS_PER_DAY // HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST
    return {
        "requests_per_day": requests_per_day,
        "requests_total": requests_per_day * TRIAL_DAYS,
        "unused_points_per_day": (
            PUBLISHED_TRIAL_POINTS_PER_DAY
            - requests_per_day * HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST
        ),
    }


def _maximize_complete_dates(
    eligible: list[dict[str, str]],
    request_budget: int,
) -> dict:
    ranked = sorted(
        eligible,
        key=lambda row: (
            int(row["symbol_date_pair_count"]),
            row["trade_date"],
        ),
    )
    chosen: list[dict[str, str]] = []
    used = 0
    for row in ranked:
        cost = int(row["symbol_date_pair_count"])
        if used + cost > request_budget:
            continue
        chosen.append(row)
        used += cost

    next_count = len(chosen) + 1
    cheapest_next_total = sum(
        int(row["symbol_date_pair_count"])
        for row in ranked[:next_count]
    )
    return {
        "selected": chosen,
        "requests_used": used,
        "next_date_count": next_count,
        "cheapest_next_total": cheapest_next_total,
    }


def plan(rows: list[dict[str, str]]) -> dict:
    eligible = _eligible_option_trades(rows)
    trade_dates = [row["trade_date"] for row in eligible]
    first_page_requests = sum(int(row["symbol_date_pair_count"]) for row in eligible)
    nominal_points = first_page_requests * HISTORICAL_OPTION_TRADES_POINTS_PER_REQUEST

    budget = _trade_only_first_page_budget()
    optimized = _maximize_complete_dates(eligible, budget["requests_total"])
    selected = optimized["selected"]
    selected_pairs = optimized["requests_used"]
    selected_dates = sorted(row["trade_date"] for row in selected)

    if len(selected) != 180 or selected_pairs != 460:
        raise ValueError(
            "frozen Cboe trade-only trial optimum drifted: "
            f"dates={len(selected)} pairs={selected_pairs}"
        )
    if optimized["cheapest_next_total"] != 467:
        raise ValueError(
            "frozen Cboe trade-only optimality certificate drifted: "
            f"{optimized['cheapest_next_total']}"
        )

    return {
        "schema_version": "4",
        "purpose": (
            "Planning-only Cboe All Access API free-trial candidate scope for frozen "
            "G2 option trades from the vendor-confirmed 2012 OPRA planning floor. "
            "The current public product page's 500-points/day limit is treated as the "
            "fail-closed capacity ceiling because trial overage is explicitly unavailable. "
            "No API call or coverage claim is made."
        ),
        "sources": {
            "all_access_product": ALL_ACCESS_PRODUCT_URL,
            "option_trades_reference": OPTION_TRADES_REFERENCE_URL,
            "opra_history_vendor_reply": (
                "Ryan Lusk, Cboe Data Vantage, email received 2026-09-30: "
                "OPRA-related datasets are available from 2012 onward."
            ),
            "trial_credit_limit_vendor_reply": (
                "Ryan Lusk, Cboe Data Vantage, email received 2026-10-02: historical "
                "data should be available via the API; select Allow for exceeding the "
                "daily credit limit; it does not matter during the trial phase."
            ),
            "current_public_trial_terms": (
                "Cboe All Access product page rechecked 2026-10-05: Free Trial has "
                "500 points/day, overage rates N/A, and overage usage is not available "
                "for trial subscriptions."
            ),
        },
        "provenance_reconciliation": {
            "vendor_confirmed_opra_earliest_year": OPRA_EARLIEST_YEAR,
            "opra_history_reply_date": OPRA_HISTORY_REPLY_DATE,
            "trial_limit_clarification_date": TRIAL_LIMIT_CLARIFICATION_DATE,
            "public_trial_page_recheck_date": PUBLIC_TRIAL_PAGE_RECHECK_DATE,
            "public_option_trades_reference_generic_earliest_year": 2003,
            "planner_earliest_year": OPRA_EARLIEST_YEAR,
            "manifest_first_date": trade_dates[0],
            "manifest_last_date": trade_dates[-1],
            "trial_capacity_guidance_conflict": True,
            "conflict_resolution": (
                "Treat the published 500-points/day ceiling as binding until runtime "
                "evidence or an explicit written vendor statement says the trial itself "
                "can exceed 500 points/day. The instruction to select Allow is not treated "
                "as proof that trial overage is available."
            ),
        },
        "documented_trial": {
            "days": TRIAL_DAYS,
            "published_points_per_day": PUBLISHED_TRIAL_POINTS_PER_DAY,
            "credit_card_authorization_required": True,
            "trial_sip_access": False,
            "signup_exceed_setting": "ALLOW",
            "published_trial_overage_available": PUBLISHED_TRIAL_OVERAGE_AVAILABLE,
            "daily_point_limit_used_as_hard_planning_cap": True,
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
            "scope": "OPTION_TRADES_FIRST_PAGE_ONLY",
            "published_daily_point_limit_used_as_hard_trial_cap": True,
            "max_first_page_trade_requests_per_day": budget["requests_per_day"],
            "unused_points_per_day_after_trade_requests": budget["unused_points_per_day"],
            "max_first_page_trade_requests_over_trial": budget["requests_total"],
            "required_first_page_requests": first_page_requests,
            "nominal_first_page_points": nominal_points,
            "candidate_complete_source_date_rows": len(selected),
            "candidate_complete_underlying_date_pairs": selected_pairs,
            "remaining_source_date_rows_due_to_trial_capacity": len(eligible) - len(selected),
            "remaining_underlying_date_pairs_due_to_trial_capacity": (
                first_page_requests - selected_pairs
            ),
            "optimality_certificate": {
                "180_cheapest_complete_dates_requests": selected_pairs,
                "181_cheapest_complete_dates_requests": optimized["cheapest_next_total"],
                "request_budget": budget["requests_total"],
                "maximum_complete_source_dates": len(selected),
            },
        },
        "strict_option_quote_capacity": {
            "status": "UNMODELED_FAIL_CLOSED",
            "reference_options_points_per_underlying_date": REFERENCE_OPTIONS_POINTS_PER_REQUEST,
            "historical_quote_points_per_contract_page": HISTORICAL_OPTION_QUOTES_POINTS_PER_REQUEST,
            "reason": (
                "Full strict option-quote acquisition requires one historical contract-list "
                "request per underlying/date plus one or more 15-point quote pages per option "
                "contract. Historical contract counts and quote-page counts are not yet known, "
                "so the free trial cannot be claimed to cover any complete quote source-date "
                "set in advance."
            ),
            "full_replication_free_trial_claimed": False,
        },
        "pagination_mechanics_documented": True,
        "pagination_runtime_verified": False,
        "trial_historical_access_runtime_verified": False,
        "per_pair_record_counts_known": False,
        "coverage_claimed": False,
        "required_source_date_rows": len(eligible),
        "required_underlying_date_pairs": first_page_requests,
        "candidate_complete_source_date_rows": len(selected),
        "candidate_complete_underlying_date_pairs": selected_pairs,
        "remaining_source_date_rows": len(eligible) - len(selected),
        "remaining_underlying_date_pairs": first_page_requests - selected_pairs,
        "selected_dates": selected_dates,
        "gates_before_use": [
            "Explicit user authorization is required before trial activation.",
            "Run the merged bounded historical acceptance probes and verify required fields.",
            "Runtime-verify the effective trial point ceiling before scheduling requests.",
            "Verify seq_no pagination on a response that reaches the 10,000-row limit.",
            "Obtain written retention authority before any bulk acquisition.",
            "Delivered rows must pass production date, symbol, schema, and content validation.",
        ],
        "warning": (
            "The 180-date/460-pair figure is an optimistic option-trade first-page ceiling "
            "that spends the entire published free-trial request budget on trade requests. "
            "Pagination, reference/options calls, option-quote requests, retries, or any other "
            "API usage can only reduce it. It is not a G2 coverage claim."
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
