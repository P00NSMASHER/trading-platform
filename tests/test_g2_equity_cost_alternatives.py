from pathlib import Path
import json

import g2_equity_cost_alternatives as alternatives


ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "data/processed/g2_vendor_requests/equity_cost_alternatives.json"


def test_equity_cost_alternatives_preserve_license_gates():
    payload = alternatives.build_alternatives()

    assert payload["equity_scope"] == {
        "source_date_rows": 828,
        "trade_rows": 414,
        "quote_rows": 414,
        "record_kind_symbol_date_pairs": 7656,
        "historical_range": ["2011-03-21", "2015-05-20"],
    }

    by_vendor = {item["vendor"]: item for item in payload["alternatives"]}

    assert by_vendor["Tick Data"]["public_data_store_minimum_new_client_usd"] == 1000.00
    assert by_vendor["Tick Data"]["public_data_store_minimum_returning_client_usd"] == 500.00
    assert by_vendor["Tick Data"]["tickapi_estimated_first_year_minimum_usd"] == 3821.00
    assert by_vendor["Tick Data"]["route_status"] == "CURRENT_PREFERRED_CANDIDATE"

    theta_equity = by_vendor["ThetaData Stocks PRO (UTP subset)"]
    assert theta_equity["eligible_source_date_rows_per_record_kind"] == 291
    assert theta_equity["eligible_symbol_date_pairs_per_record_kind"] == 1430
    assert theta_equity["eligible_unique_symbols"] == 55
    assert theta_equity["required_symbol_date_pairs_per_record_kind"] == 3828
    assert theta_equity["residual_symbol_date_pairs_per_record_kind"] == 2398
    assert theta_equity["coverage_fit"] == "PARTIAL_POINT_IN_TIME_XNAS_UTP_SLICE"
    assert theta_equity["license_fit"] == "PRIVATE_RESEARCH_CONFIRMED_BOUNDED_RAW_RETENTION"
    assert theta_equity["pricing_status"] == "WRITTEN_STOCK_PRO_160_USD_MONTH_COMBINED_WITH_OPTIONS_320_USD_MONTH"
    assert theta_equity["written_stock_pro_monthly_price_usd"] == 160.00
    assert theta_equity["written_combined_options_stock_monthly_price_usd"] == 320.00
    assert theta_equity["raw_unmodified_retention"] == "DELETE_WITHIN_30_DAYS_AFTER_SUBSCRIPTION_BILLING_PERIOD_ENDS"
    assert theta_equity["derived_research_retention"] == "ALLOWED_AFTER_RAW_DELETION"

    assert by_vendor["Massive Stocks Advanced"]["public_monthly_price_usd"] == 199.00
    assert by_vendor["Massive Stocks Advanced"]["coverage_fit"] == "FULL_SCOPE_TECHNICAL_FIT"
    assert by_vendor["Massive Stocks Advanced"]["license_fit"] == "WRITTEN_TERMS_CLEARANCE_REQUIRED"

    assert by_vendor["Massive Stocks Business"]["public_monthly_price_usd"] == 2499.00
    assert by_vendor["Massive Stocks Business"]["license_fit"] == "ORDER_TERMS_AND_RETENTION_REVIEW_REQUIRED"

    assert by_vendor["FirstRate Data TickHistory"]["coverage_fit"] == "INCOMPLETE_FROZEN_SYMBOL_UNIVERSE"
    assert by_vendor["FirstRate Data TickHistory"]["license_fit"] == "RESEARCH_FRIENDLY"
    assert by_vendor["FirstRate Data TickHistory"]["direct_frozen_symbol_matches"] == 106
    assert by_vendor["FirstRate Data TickHistory"]["missing_frozen_symbols"] == 40
    assert by_vendor["FirstRate Data TickHistory"]["covered_symbol_date_pairs_per_record_kind"] == 2750
    assert by_vendor["FirstRate Data TickHistory"]["required_symbol_date_pairs_per_record_kind"] == 3828
    assert by_vendor["FirstRate Data TickHistory"]["fully_satisfied_market_dates_per_record_kind"] == 118

    assert payload["policy"] == {
        "do_not_replace_preferred_route_without_license_clearance": True,
        "candidate_is_not_coverage": True,
        "do_not_purchase_automatically": True,
    }


def test_committed_equity_cost_alternatives_match_generator():
    assert json.loads(COMMITTED.read_text(encoding="utf-8")) == alternatives.build_alternatives()
