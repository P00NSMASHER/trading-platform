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
                "public_cost_reference": "src/g2_tickapi_cost_estimator.py",
                "estimated_first_year_minimum_usd": 3821.00,
                "coverage_fit": "FULL_SCOPE_CANDIDATE",
                "license_fit": "PENDING_VENDOR_TERMS",
                "blocking_fact": "Vendor requires a phone call before written pricing/availability.",
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
                "blocking_fact": (
                    "Current TickHistory FAQ says delisted tickers are not available, so the service "
                    "cannot satisfy the full historical-symbol requirement by itself."
                ),
                "source_urls": [
                    "https://firstratedata.com/tick-data",
                    "https://tick.firstratedata.com/about/FAQ",
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
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
