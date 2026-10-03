from pathlib import Path
import json

import g2_options_cost_alternatives as alternatives


ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "data/processed/g2_vendor_requests/options_cost_alternatives.json"


def test_options_cost_alternatives_preserve_history_and_license_gates():
    payload = alternatives.build_alternatives()

    assert payload["option_trade_scope"] == {
        "champion_minimum_source_date_rows": 414,
        "underlying_date_pairs": 3828,
        "historical_range": ["2011-03-21", "2015-05-20"],
    }
    assert payload["option_quote_scope"]["full_replication_source_date_rows"] == 414

    current = {item["vendor"]: item for item in payload["current_preferred_trade_routes"]}
    assert current["LSEG Tick History"]["source_date_rows"] == 105
    assert current["Cboe DataShop Option Trades"]["source_date_rows"] == 83
    assert current["Databento OPRA.PILLAR Trades"]["source_date_rows"] == 226

    cheapest = payload["conditional_cheapest_full_option_route"]
    assert cheapest["status"] == "PREFERRED_THETADATA_CLEARED_LSEG_PRICE_PENDING"
    assert cheapest["expected_vendor_count"] == 2
    assert cheapest["coverage_accounting"] == {
        "source_date_rows_per_record_kind": 414,
        "underlying_date_pairs_per_record_kind": 3828,
        "record_kinds": ["option_trade", "option_quote"],
    }
    segments = {item["vendor"]: item for item in cheapest["segments"]}
    assert segments["LSEG OPRA Tick History"]["source_date_rows_per_record_kind"] == 123
    assert segments["LSEG OPRA Tick History"]["underlying_date_pairs_per_record_kind"] == 814
    assert segments["ThetaData Options PRO"]["source_date_rows_per_record_kind"] == 291
    assert segments["ThetaData Options PRO"]["underlying_date_pairs_per_record_kind"] == 3014
    assert segments["ThetaData Options PRO"]["pricing_status"] == "WRITTEN_160_USD_MONTH_PRIVATE_RESEARCH_ELIGIBLE_RETENTION_CONDITIONAL"
    assert segments["ThetaData Options PRO"]["written_monthly_price_usd"] == 160.00
    assert segments["ThetaData Options PRO"]["private_research_eligible"] is True
    assert segments["ThetaData Options PRO"]["raw_data_delete_days_after_billing_period_end"] == 30
    assert segments["ThetaData Options PRO"]["derived_or_modified_data_retention_allowed"] is True
    assert cheapest["replaces_if_cleared"] == [
        "Cboe DataShop Option Trades",
        "Databento OPRA.PILLAR Trades",
    ]

    by_vendor = {item["vendor"]: item for item in payload["alternatives"]}

    theta = by_vendor["ThetaData Options PRO"]
    assert theta["public_retail_monthly_price_usd"] == 160.00
    assert theta["public_commercial_monthly_price_usd"] == 1600.00
    assert theta["public_startup_monthly_price_as_low_as_usd"] == 500.00
    assert theta["eligible_trade_rows"] == 291
    assert theta["eligible_trade_underlying_date_pairs"] == 3014
    assert theta["eligible_quote_rows"] == 291
    assert theta["eligible_quote_underlying_date_pairs"] == 3014
    assert theta["pre_history_residual_rows_per_record_kind"] == 123
    assert theta["pre_history_residual_pairs_per_record_kind"] == 814
    assert theta["license_fit"] == "PRIVATE_RESEARCH_ELIGIBLE_RAW_DELETE_30_DAYS_AFTER_BILLING_DERIVED_RETENTION_ALLOWED"
    assert theta["written_monthly_price_usd"] == 160.00
    assert theta["private_research_eligible"] is True
    assert theta["raw_data_delete_days_after_billing_period_end"] == 30
    assert theta["derived_or_modified_data_retention_allowed"] is True

    algo = by_vendor["algoseek Options Trade and NBBO Quote"]
    assert algo["conservative_frozen_eligible_rows_per_record_kind"] == 131
    assert algo["conservative_frozen_pairs_per_record_kind"] == 2178
    assert "HISTORY_CONFLICT" in algo["route_status"]

    lseg = by_vendor["LSEG OPRA Tick History"]
    assert lseg["eligible_trade_rows"] == 414
    assert lseg["eligible_quote_rows"] == 414
    assert lseg["eligible_pairs_per_record_kind"] == 3828
    assert lseg["license_fit"] == "QUOTE_AND_ENTITLEMENT_PENDING"

    cboe = by_vendor["Cboe Custom Tick OPRA"]
    assert cboe["route_status"] == "TECHNICALLY_AVAILABLE_ECONOMICALLY_REJECTED"
    assert cboe["pricing_status"] == "WRITTEN_QUOTE_RECEIVED_OUTSIDE_TARGET_BUDGET"

    assert payload["policy"] == {
        "do_not_replace_preferred_routes_without_license_clearance": True,
        "do_not_count_conflicting_history_as_proven": True,
        "candidate_is_not_coverage": True,
        "do_not_purchase_automatically": True,
    }


def test_committed_options_cost_alternatives_match_generator():
    assert json.loads(COMMITTED.read_text(encoding="utf-8")) == alternatives.build_alternatives()
