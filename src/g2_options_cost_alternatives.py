from __future__ import annotations

import argparse
import json
from pathlib import Path

PRICING_AS_OF = "2026-10-02"


def build_alternatives() -> dict:
    return {
        "schema_version": "2",
        "purpose": (
            "Planning-only lower-cost alternatives for G2 option trades and strict tick-level "
            "option quotes. Temporary trial access, public pricing, or vendor availability does "
            "not establish retention rights, entitlement, delivery completeness, or G2 coverage."
        ),
        "pricing_as_of": PRICING_AS_OF,
        "option_trade_scope": {
            "source_date_rows": 414,
            "underlying_date_pairs": 3828,
            "historical_range": ["2011-03-21", "2015-05-20"],
        },
        "option_quote_scope": {
            "source_date_rows": 414,
            "underlying_date_pairs": 3828,
            "historical_range": ["2011-03-21", "2015-05-20"],
            "fidelity_requirement": "TICK_LEVEL_NBBO_WITH_SIZE",
        },
        "current_preferred_trade_routes": [
            {
                "vendor": "LSEG OPRA Tick History",
                "source_date_rows": 105,
                "underlying_date_pairs": 464,
                "historical_segment": ["2011-03-21", "2011-12-30"],
                "pricing_status": "REQUEST_SENT_AWAITING_REPLY",
                "role": "PRE_2012_COMPETITIVE_QUOTE",
            },
            {
                "vendor": "NxCore Historical by Nanex",
                "source_date_rows": 105,
                "underlying_date_pairs": 464,
                "historical_segment": ["2011-03-21", "2011-12-30"],
                "pricing_status": "CURRENT_PUBLIC_PRICE_NOT_POSTED_QUOTE_REQUIRED",
                "role": "PRE_2012_COMPETITIVE_QUOTE",
            },
            {
                "vendor": "Cboe All Access historical",
                "source_date_rows": 309,
                "underlying_date_pairs": 3364,
                "historical_segment": ["2012-01-03", "2015-05-20"],
                "pricing_status": "FREE_TRIAL_TECHNICAL_SCREEN",
                "runtime_status": "VENDOR_CONFIRMED_HISTORICAL_ACCESS_QUOTE_RUNTIME_NOT_VERIFIED",
                "retention_status": (
                    "DEFAULT_TERMINATION_DELETE_RETURN_UNLESS_ORDER_FORM_OVERRIDES"
                ),
                "role": "ZERO_COST_2012PLUS_SCREEN_NOT_DURABLE_COVERAGE",
            },
        ],
        "conditional_cheapest_full_option_route": {
            "status": "PREFERRED_IF_CBOE_RETENTION_AND_HISTORICAL_NBBO_RUNTIME_CLEAR",
            "expected_vendor_count": 2,
            "segments": [
                {
                    "vendor": "LSEG OR NxCore competitive 2011 quote",
                    "historical_segment": ["2011-03-21", "2011-12-30"],
                    "source_date_rows_per_record_kind": 105,
                    "underlying_date_pairs_per_record_kind": 464,
                    "record_kinds": ["option_trade", "option_quote"],
                    "pricing_status": "COMPETITIVE_QUOTES_PENDING",
                },
                {
                    "vendor": "Cboe All Access historical",
                    "historical_segment": ["2012-01-03", "2015-05-20"],
                    "source_date_rows_per_record_kind": 309,
                    "underlying_date_pairs_per_record_kind": 3364,
                    "record_kinds": ["option_trade", "option_quote"],
                    "trial_base_price_usd": 0,
                    "technical_status": (
                        "OPTION_TRADES_VENDOR_CONFIRMED_ELIGIBLE_OPTION_NBBO_RUNTIME_UNVERIFIED"
                    ),
                    "retention_status": (
                        "WRITTEN_ORDER_FORM_OR_VENDOR_RETENTION_PERMISSION_REQUIRED"
                    ),
                    "quote_request_volume_status": (
                        "UNKNOWN_CONTRACT_LEVEL_ENUMERATION_AND_PAGINATION_REQUIRED"
                    ),
                },
            ],
            "coverage_accounting": {
                "source_date_rows_per_record_kind": 414,
                "underlying_date_pairs_per_record_kind": 3828,
                "record_kinds": ["option_trade", "option_quote"],
            },
            "activation_rule": (
                "Do not bulk-acquire from the Cboe trial unless written retention rights allow "
                "continued internal research use after termination and the tiny historical NBBO "
                "smoke passes. Then enumerate every historical contract with reference/options, "
                "measure pagination/request-rate feasibility, and validate delivery before coverage."
            ),
            "validated_coverage_claimed": False,
        },
        "fallback_if_cboe_retention_or_quote_fails": {
            "status": "THETADATA_PLUS_PREHISTORY_VENDOR_CONDITIONAL",
            "segments": [
                {
                    "vendor": "LSEG OR NxCore pre-Theta historical",
                    "historical_segment": ["2011-03-21", "2012-01-27"],
                    "source_date_rows_per_record_kind": 123,
                    "underlying_date_pairs_per_record_kind": 814,
                    "record_kinds": ["option_trade", "option_quote"],
                    "pricing_status": "QUOTE_REQUIRED",
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
            "activation_rule": (
                "Do not purchase until vendor-specific license, retention, price, and delivery "
                "terms are acceptable."
            ),
        },
        "alternatives": [
            {
                "vendor": "NxCore Historical by Nanex",
                "route_status": "FULL_RANGE_CANDIDATE_PRICE_AND_LICENSE_PENDING",
                "documented_history_start_year": 2004,
                "eligible_trade_rows": 414,
                "eligible_quote_rows": 414,
                "eligible_pairs_per_record_kind": 3828,
                "targeted_2011_residual_rows_per_record_kind": 105,
                "targeted_2011_residual_pairs_per_record_kind": 464,
                "fidelity_fit": "FULL_TICK_TRADES_QUOTES_AND_NBBO",
                "delisted_symbol_support": "PUBLICLY_DOCUMENTED",
                "license_fit": "ONE_TIME_PRICE_RETENTION_AND_NONDISPLAY_TERMS_PENDING",
                "blocking_fact": (
                    "Historical purchases are publicly offered back to 2004, but exact 2011 OPRA "
                    "subset pricing and durable retention/non-display terms are not publicly posted."
                ),
                "source_urls": [
                    "https://www.nxcoredata.com/historical-nxcore-data/",
                    "https://www.nxcoredata.com/nxcore-overview/",
                    "https://www.nxcoredata.com/sample-nxcore-data/",
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
                "vendor": "Cboe All Access historical",
                "route_status": "ZERO_COST_TECHNICAL_SCREEN_RETENTION_BLOCKED",
                "documented_opra_floor_year": 2012,
                "eligible_trade_rows": 309,
                "eligible_trade_underlying_date_pairs": 3364,
                "candidate_quote_rows": 309,
                "candidate_quote_underlying_date_pairs": 3364,
                "trial_base_price_usd": 0,
                "fidelity_fit": "HISTORICAL_TICK_TRADES_AND_DOCUMENTED_NBBO_QUOTE_ENDPOINT",
                "license_fit": "RETENTION_ORDER_FORM_OR_WRITTEN_PERMISSION_REQUIRED",
                "blocking_fact": (
                    "Historical option-trade access is vendor-confirmed and the historical quote "
                    "endpoint is documented, but quote runtime access is unverified and the default "
                    "subscription agreement requires delete/return at termination unless the Order "
                    "Form expressly provides otherwise."
                ),
                "source_urls": [
                    "https://datashop.cboe.com/cboe-all-access-api",
                    "https://api.livevol.com/v1/docs/Help?apiGroupName=allaccess",
                    "https://datashop.cboe.com/documents/Cboe_RMA_Subscription_Services_Agreement.pdf",
                ],
            },
            {
                "vendor": "ThetaData Options PRO",
                "route_status": "CHEAP_CONDITIONAL_FALLBACK",
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
                "vendor": "Databento OPRA.PILLAR Trades",
                "route_status": "TRADE_ONLY_FALLBACK_COST_PROBE_BLOCKED",
                "documented_trade_history_start": "2013-04-01",
                "eligible_trade_rows": 226,
                "eligible_trade_underlying_date_pairs": 2875,
                "fidelity_fit": "TICK_TRADES_ONLY_NOT_STRICT_OPTION_QUOTES",
                "license_fit": "API_KEY_AND_COST_PROBE_PENDING",
                "blocking_fact": (
                    "Does not consolidate strict option quotes; exact cost probe cannot run until "
                    "DATABENTO_API_KEY is configured."
                ),
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
        "rejected_routes": [
            {
                "vendor": "ISE Historical Options Tick Data (HOT Data)",
                "route_status": "DISCONTINUED_DO_NOT_USE_STALE_PRICING",
                "discontinued_year": 2015,
                "reason": (
                    "ISE eliminated HOT Data in 2015. The historical $120/day, $1,000-minimum "
                    "pricing is the last pre-discontinuation fee, not a current purchase route."
                ),
                "source_url": (
                    "https://listingcenter.nasdaq.com/assets/rulebook/ise/filings/"
                    "SR-ISE-2015-24.pdf"
                ),
            }
        ],
        "policy": {
            "do_not_replace_routes_without_license_clearance": True,
            "temporary_trial_access_is_not_retention_authority": True,
            "strict_option_quote_universe_requires_contract_enumeration": True,
            "do_not_count_conflicting_history_as_proven": True,
            "candidate_is_not_coverage": True,
            "do_not_purchase_automatically": True,
            "validated_g2_coverage_unchanged": True,
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
