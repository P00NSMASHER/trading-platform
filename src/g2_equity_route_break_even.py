from __future__ import annotations

import argparse
import json
from pathlib import Path

PRICING_AS_OF = "2026-10-02"

TICKDATA_NEW_CLIENT_MINIMUM_USD = 1000.00
TICKDATA_RETURNING_CLIENT_MINIMUM_USD = 500.00

FIRSTRATE_ADDITIONAL_TICKERS = 31
FIRSTRATE_PUBLIC_10_PLUS_PRICE_PER_TICKER_USD = 19.95
FIRSTRATE_INDICATIVE_COST_USD = round(
    FIRSTRATE_ADDITIONAL_TICKERS * FIRSTRATE_PUBLIC_10_PLUS_PRICE_PER_TICKER_USD,
    2,
)

FULL_TICKAPI_FIRST_YEAR_USD = 3821.00
RESIDUAL_TICKAPI_FIRST_YEAR_USD = 3338.66

FULL_TICKDATA_SYMBOLS = 146
FULL_TICKDATA_SYMBOL_YEARS = 193
RESIDUAL_TICKDATA_SYMBOLS = 61
RESIDUAL_TICKDATA_SYMBOL_YEARS = 82


def build_break_even() -> dict:
    combined_tickapi_before_theta = round(
        RESIDUAL_TICKAPI_FIRST_YEAR_USD + FIRSTRATE_INDICATIVE_COST_USD,
        2,
    )
    combined_tickapi_delta_before_theta = round(
        combined_tickapi_before_theta - FULL_TICKAPI_FIRST_YEAR_USD,
        2,
    )

    new_client_known_floor = round(
        TICKDATA_NEW_CLIENT_MINIMUM_USD + FIRSTRATE_INDICATIVE_COST_USD,
        2,
    )
    returning_client_known_floor = round(
        TICKDATA_RETURNING_CLIENT_MINIMUM_USD + FIRSTRATE_INDICATIVE_COST_USD,
        2,
    )

    return {
        "schema_version": "1",
        "purpose": (
            "Planning-only break-even receipt for the full Tick Data equity route versus the "
            "conditional ThetaData + FirstRate + Tick Data residual route. Public minimums and "
            "sticker prices are not vendor quotes and do not authorize a purchase."
        ),
        "pricing_as_of": PRICING_AS_OF,
        "scope": {
            "full_tickdata": {
                "unique_symbols": FULL_TICKDATA_SYMBOLS,
                "symbol_years": FULL_TICKDATA_SYMBOL_YEARS,
            },
            "combined_route_tickdata_residual": {
                "unique_symbols": RESIDUAL_TICKDATA_SYMBOLS,
                "symbol_years": RESIDUAL_TICKDATA_SYMBOL_YEARS,
            },
            "firstrate_additional_tickers": FIRSTRATE_ADDITIONAL_TICKERS,
        },
        "public_price_inputs": {
            "tickdata_new_client_minimum_usd": TICKDATA_NEW_CLIENT_MINIMUM_USD,
            "tickdata_returning_client_minimum_usd": TICKDATA_RETURNING_CLIENT_MINIMUM_USD,
            "firstrate_10_plus_price_per_ticker_usd": (
                FIRSTRATE_PUBLIC_10_PLUS_PRICE_PER_TICKER_USD
            ),
            "firstrate_31_ticker_indicative_cost_usd": FIRSTRATE_INDICATIVE_COST_USD,
            "theta_stocks_incremental_bundle_cost_usd": None,
            "tickdata_full_data_store_quote_usd": None,
            "tickdata_residual_data_store_quote_usd": None,
        },
        "tickapi_comparison": {
            "full_scope_first_year_usd": FULL_TICKAPI_FIRST_YEAR_USD,
            "residual_first_year_usd": RESIDUAL_TICKAPI_FIRST_YEAR_USD,
            "residual_plus_firstrate_before_theta_usd": combined_tickapi_before_theta,
            "combined_minus_full_before_theta_usd": combined_tickapi_delta_before_theta,
            "combined_route_can_beat_full_tickapi_with_nonnegative_theta_cost": (
                combined_tickapi_before_theta < FULL_TICKAPI_FIRST_YEAR_USD
            ),
            "decision": (
                "REJECT_COMBINED_ROUTE_FOR_TICKAPI_COST_OPTIMIZATION"
                if combined_tickapi_before_theta >= FULL_TICKAPI_FIRST_YEAR_USD
                else "CONDITIONAL"
            ),
        },
        "data_store_break_even": {
            "new_client_combined_known_floor_before_theta_delivery_tax_usd": (
                new_client_known_floor
            ),
            "returning_client_combined_known_floor_before_theta_delivery_tax_usd": (
                returning_client_known_floor
            ),
            "new_client_full_route_public_floor_usd": TICKDATA_NEW_CLIENT_MINIMUM_USD,
            "returning_client_full_route_public_floor_usd": (
                TICKDATA_RETURNING_CLIENT_MINIMUM_USD
            ),
            "exact_condition": (
                "combined route is cheaper only when "
                "tickdata_residual_quote + firstrate_cost + theta_incremental_cost "
                "< tickdata_full_quote, after comparing like-for-like delivery fees and taxes"
            ),
            "minimum_full_quote_to_beat_if_residual_hits_new_client_minimum_and_theta_is_free_usd": (
                new_client_known_floor
            ),
            "minimum_full_quote_to_beat_if_residual_hits_returning_minimum_and_theta_is_free_usd": (
                returning_client_known_floor
            ),
            "status": "AWAIT_EXACT_TICKDATA_AND_THETADATA_QUOTES",
        },
        "policy": {
            "public_minimum_is_not_quote": True,
            "firstrate_sticker_price_is_not_license_clearance": True,
            "theta_incremental_cost_not_assumed": True,
            "delivery_support_fee_and_tax_not_assumed": True,
            "do_not_switch_route_automatically": True,
            "do_not_purchase_automatically": True,
            "validated_g2_coverage_unchanged": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the G2 equity route break-even planning receipt."
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = build_break_even()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
