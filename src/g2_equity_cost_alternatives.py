from __future__ import annotations

import argparse
import json
from pathlib import Path

PRICING_AS_OF = "2026-10-02"


def build_alternatives() -> dict:
    return {
        "schema_version": "1",
        "purpose": (
            "Planning-only lower-cost alternatives for the 828-row G2_CHAMPION_MINIMUM "
            "equity scope. Availability/pricing does not establish license suitability or G2 coverage."
        ),
        "pricing_as_of": PRICING_AS_OF,
        "equity_scope": {
            "source_date_rows": 828,
            "trade_rows": 414,
            "quote_rows": 414,
            "record_kind_symbol_date_pairs": 7656,
            "historical_range": ["2011-03-21", "2015-05-20"],
        },
        "alternatives": [
            {
                "vendor": "Tick Data",
                "route_status": "CURRENT_PREFERRED_CANDIDATE",
                "public_data_store_minimum_new_client_usd": 1000.00,
                "public_data_store_minimum_returning_client_usd": 500.00,
                "data_store_pricing_source_url": "https://www.tickdata.com/tickdatastore",
                "tickapi_cost_reference": "src/g2_tickapi_cost_estimator.py",
                "tickapi_estimated_first_year_minimum_usd": 3821.00,
                "coverage_fit": "FULL_SCOPE_CANDIDATE",
                "license_fit": "PENDING_VENDOR_TERMS",
                "blocking_fact": (
                    "Vendor requires a phone call before written pricing/availability. Public Data "
                    "Store pricing supports custom symbol/date ranges with a $1,000 new-client minimum, "
                    "so price the one-time Data Store route before considering the 12-month TickAPI floor."
                ),
            },
            {
                "vendor": "ThetaData Stocks PRO (UTP subset)",
                "route_status": "CHEAP_PARTIAL_BUNDLE_CANDIDATE",
                "documented_utp_history_start": "2012-06-01",
                "frozen_first_eligible_date": "2012-06-29",
                "post_history_date_universe": 291,
                "eligible_source_date_rows_per_record_kind": 230,
                "eligible_symbol_date_pairs_per_record_kind": 1430,
                "eligible_unique_symbols": 55,
                "required_symbol_date_pairs_per_record_kind": 3828,
                "residual_source_date_rows_per_record_kind": 380,
                "residual_symbol_date_pairs_per_record_kind": 2398,
                "coverage_fit": "PARTIAL_POINT_IN_TIME_XNAS_UTP_SLICE",
                "fidelity_fit": "TICK_TRADES_AND_NBBO_QUOTES",
                "license_fit": "SALES_CLASSIFICATION_RETENTION_AND_BUNDLE_QUOTE_PENDING",
                "pricing_status": "BUNDLE_QUOTE_REQUEST_SENT_2026-10-02",
                "derivation_basis": (
                    "The frozen post-2012-06 equity requirements were joined to G3 point-in-time "
                    "primary-listing evidence. Exactly 55 XNAS symbols across 230 non-empty request dates account for 1,430 of 3,828 "
                    "symbol/date pairs per equity record kind; no listing-evidence conflicts remain."
                ),
                "blocking_fact": (
                    "ThetaData documents UTP tick history from 2012-06-01, but the pre-history and "
                    "CTA/XASE residual still needs another source. Written license classification, "
                    "retention terms, and the requested options+stocks bundle quote remain pending."
                ),
                "source_urls": [
                    "https://thetadata.net/pricing",
                    "https://thetadata.net/docs/Articles/Getting-Started/Subscriptions.html",
                ],
            },
            {
                "vendor": "Massive Stocks Advanced",
                "route_status": "CHEAPER_CONDITIONAL_ALTERNATIVE",
                "public_monthly_price_usd": 199.00,
                "coverage_start": "2003-09-10",
                "coverage_fit": "FULL_SCOPE_TECHNICAL_FIT",
                "license_fit": "WRITTEN_TERMS_CLEARANCE_REQUIRED",
                "blocking_fact": (
                    "Default individual market-data terms are personal/non-business and generally "
                    "display-only unless another agreement applies; historical extraction/backtest "
                    "retention must be cleared before use."
                ),
                "source_urls": [
                    "https://massive.com/pricing?product=stocks",
                    "https://massive.com/legal/market-data-terms-of-service",
                ],
            },
            {
                "vendor": "Massive Stocks Business",
                "route_status": "BUSINESS_USE_CONDITIONAL_ALTERNATIVE",
                "public_monthly_price_usd": 2499.00,
                "coverage_fit": "FULL_SCOPE_TECHNICAL_FIT",
                "license_fit": "ORDER_TERMS_AND_RETENTION_REVIEW_REQUIRED",
                "blocking_fact": (
                    "Business plan advertises 20+ years of historical trades and quotes, but the "
                    "specific order terms must permit the intended internal research retention/use."
                ),
                "source_urls": ["https://massive.com/business"],
            },
            {
                "vendor": "FirstRate Data TickHistory",
                "route_status": "PARTIAL_ONLY",
                "coverage_start": "2010-01-01",
                "coverage_fit": "INCOMPLETE_FROZEN_SYMBOL_UNIVERSE",
                "license_fit": "RESEARCH_FRIENDLY",
                "direct_frozen_symbol_matches": 106,
                "missing_frozen_symbols": 40,
                "covered_symbol_date_pairs_per_record_kind": 2750,
                "required_symbol_date_pairs_per_record_kind": 3828,
                "covered_fraction_per_record_kind": 2750 / 3828,
                "fully_satisfied_market_dates_per_record_kind": 118,
                "blocking_fact": (
                    "Public tick-history scope is incomplete for the frozen universe: a direct ticker "
                    "listing audit matches 106/146 historical symbols and 2,750/3,828 symbol-date pairs "
                    "per equity record kind. FirstRate's general FAQ describes some delisted coverage, "
                    "while its tick-history-specific FAQ remains more restrictive; do not infer the "
                    "missing 40 symbols without exact confirmation."
                ),
                "source_urls": [
                    "https://firstratedata.com/tick-data",
                    "https://tick.firstratedata.com/about/FAQ",
                    "https://firstratedata.com/about/FAQ",
                    "https://firstratedata.com/about/license",
                ],
            },
        ],
        "policy": {
            "do_not_replace_preferred_route_without_license_clearance": True,
            "candidate_is_not_coverage": True,
            "do_not_purchase_automatically": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build G2 equity lower-cost alternative receipt.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_alternatives()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
