from __future__ import annotations

import argparse
import json
from pathlib import Path

PRICING_AS_OF = "2026-10-02"


def build_alternatives() -> dict:
    return {
        "schema_version": "1",
        "purpose": (
            "Planning-only lower-cost alternatives for G2 option trades and the separate "
            "full-replication option-quote layer. Pricing/availability does not establish "
            "license suitability, delivery, or G2 coverage."
        ),
        "pricing_as_of": PRICING_AS_OF,
        "option_trade_scope": {
            "champion_minimum_source_date_rows": 414,
            "underlying_date_pairs": 3828,
            "historical_range": ["2011-03-21", "2015-05-20"],
        },
        "option_quote_scope": {
            "full_replication_source_date_rows": 414,
            "underlying_date_pairs": 3828,
            "historical_range": ["2011-03-21", "2015-05-20"],
        },
        "current_preferred_trade_routes": [
            {
                "vendor": "LSEG Tick History",
                "source_date_rows": 105,
                "underlying_date_pairs": 464,
                "historical_segment": ["2011-03-21", "2011-12-30"],
                "pricing_status": "REQUEST_SENT_AWAITING_REPLY",
            },
            {
                "vendor": "Cboe DataShop Option Trades",
                "source_date_rows": 83,
                "underlying_date_pairs": 489,
                "historical_segment": ["2012-01-03", "2013-03-28"],
                "pricing_status": "TRIAL_OR_PAID_ROUTE_PENDING",
            },
            {
                "vendor": "Databento OPRA.PILLAR Trades",
                "source_date_rows": 226,
                "underlying_date_pairs": 2875,
                "historical_segment": ["2013-04-01", "2015-05-20"],
                "pricing_status": "COST_PROBE_BLOCKED_API_KEY_NOT_CONFIGURED",
            },
        ],
        "conditional_cheapest_full_option_route": {
            "status": "PREFERRED_IF_THETADATA_WRITTEN_LICENSE_CLEARANCE_IS_RECEIVED",
            "expected_vendor_count": 2,
            "segments": [
                {
                    "vendor": "LSEG OPRA Tick History",
                    "historical_segment": ["2011-03-21", "2012-01-27"],
                    "source_date_rows_per_record_kind": 123,
                    "underlying_date_pairs_per_record_kind": 814,
                    "record_kinds": ["option_trade", "option_quote"],
                    "pricing_status": "QUOTE_AND_ENTITLEMENT_PENDING",
                },
                {
                    "vendor": "ThetaData Options PRO",
                    "historical_segment": ["2012-06-29", "2015-05-20"],
                    "source_date_rows_per_record_kind": 291,
                    "underlying_date_pairs_per_record_kind": 3014,
                    "record_kinds": ["option_trade", "option_quote"],
                    "pricing_status": "SALES_CLASSIFICATION_AND_RETENTION_TERMS_PENDING",
                    "public_retail_monthly_price_usd": 160.00,
                    "public_commercial_monthly_price_usd": 1600.00,
                    "public_startup_monthly_price_as_low_as_usd": 500.00,
                },
            ],
            "coverage_accounting": {
                "source_date_rows_per_record_kind": 414,
                "underlying_date_pairs_per_record_kind": 3828,
                "record_kinds": ["option_trade", "option_quote"],
            },
            "replaces_if_cleared": [
                "Cboe DataShop Option Trades",
                "Databento OPRA.PILLAR Trades",
            ],
            "activation_rule": (
                "Do not switch routes or purchase until written ThetaData license/retention "
                "terms and LSEG price/entitlement are acceptable."
            ),
        },
        "alternatives": [
            {
                "vendor": "ThetaData Options PRO",
                "route_status": "CHEAP_CONDITIONAL_CONSOLIDATION",
                "public_retail_monthly_price_usd": 160.00,
                "public_commercial_monthly_price_usd": 1600.00,
                "public_startup_monthly_price_as_low_as_usd": 500.00,
                "documented_trade_history_start": "2012-06-01",
                "frozen_first_eligible_date": "2012-06-29",
                "eligible_trade_rows": 291,
                "eligible_trade_underlying_date_pairs": 3014,
                "eligible_quote_rows": 291,
                "eligible_quote_underlying_date_pairs": 3014,
                "pre_history_residual_rows_per_record_kind": 123,
                "pre_history_residual_pairs_per_record_kind": 814,
                "fidelity_fit": "TICK_TRADES_AND_EVERY_OPRA_NBBO_QUOTE",
                "license_fit": "SALES_CLASSIFICATION_AND_RETENTION_TERMS_PENDING",
                "blocking_fact": (
                    "Retail pricing is individual-use; business/non-display classification and "
                    "retention rights for the research pipeline require written sales confirmation."
                ),
                "source_urls": [
                    "https://thetadata.net/pricing",
                    "https://www.thetadata.net/commercial-use",
                    "https://thetadata.net/docs/Articles/Data-And-Requests/Making-Requests.html",
                ],
            },
            {
                "vendor": "algoseek Options Trade and NBBO Quote",
                "route_status": "ROBUST_BUT_HIGHER_COST_AND_HISTORY_CONFLICT",
                "public_dataset_monthly_price_usd": 2000.00,
                "public_options_package_monthly_price_usd": 3000.00,
                "conservative_documented_tick_start": "2014-01-01",
                "conservative_frozen_eligible_rows_per_record_kind": 131,
                "conservative_frozen_pairs_per_record_kind": 2178,
                "fidelity_fit": "TICK_TRADES_AND_NBBO_QUOTES",
                "license_fit": "HISTORICAL_RESEARCH_PACKAGE_OR_DATASET_LICENSE",
                "blocking_fact": (
                    "Current algoseek pages conflict on whether strict tick OPRA history begins in "
                    "2012 or 2014. Until sales confirms the exact TANQ dataset/granularity, only the "
                    "conservative 2014+ frozen slice is treated as proven."
                ),
                "source_urls": [
                    "https://algoseek.com/dataset/us-options-trade-and-nbbo-quote/",
                    "https://algoseek.com/pricing/",
                ],
            },
            {
                "vendor": "LSEG OPRA Tick History",
                "route_status": "FULL_RANGE_CANDIDATE_PRICE_PENDING",
                "documented_tick_history_start_year": 1997,
                "eligible_trade_rows": 414,
                "eligible_quote_rows": 414,
                "eligible_pairs_per_record_kind": 3828,
                "fidelity_fit": "FULL_TICK_OPRA",
                "license_fit": "QUOTE_AND_ENTITLEMENT_PENDING",
                "blocking_fact": "Exact scope pricing and entitlement response is still pending.",
            },
            {
                "vendor": "Cboe Custom Tick OPRA",
                "route_status": "TECHNICALLY_AVAILABLE_ECONOMICALLY_REJECTED",
                "fidelity_fit": "FULL_TICK_OPRA",
                "scope_constraint": "FULL_OPRA_UNIVERSE_ONLY",
                "pricing_status": "WRITTEN_QUOTE_RECEIVED_OUTSIDE_TARGET_BUDGET",
                "blocking_fact": (
                    "Cboe confirmed availability but will not sell only the requested underlyings; "
                    "the current custom full-universe quote is outside the project's cheap-path scope."
                ),
            },
        ],
        "policy": {
            "do_not_replace_preferred_routes_without_license_clearance": True,
            "do_not_count_conflicting_history_as_proven": True,
            "candidate_is_not_coverage": True,
            "do_not_purchase_automatically": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build G2 options lower-cost alternative receipt.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_alternatives()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
