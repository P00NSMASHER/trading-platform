from pathlib import Path
import json

import g2_options_cost_alternatives as alternatives


ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "data/processed/g2_vendor_requests/options_cost_alternatives.json"


def test_options_cost_tree_reflects_cboe_2012plus_and_2011_competition():
    payload = alternatives.build_alternatives()

    assert payload["schema_version"] == "2"
    assert payload["option_trade_scope"] == {
        "source_date_rows": 414,
        "underlying_date_pairs": 3828,
        "historical_range": ["2011-03-21", "2015-05-20"],
    }
    assert payload["option_quote_scope"]["source_date_rows"] == 414
    assert payload["option_quote_scope"]["fidelity_requirement"] == "TICK_LEVEL_NBBO_WITH_SIZE"

    current = {item["vendor"]: item for item in payload["current_preferred_trade_routes"]}
    assert current["LSEG OPRA Tick History"]["source_date_rows"] == 105
    assert current["LSEG OPRA Tick History"]["underlying_date_pairs"] == 464
    assert current["NxCore Historical by Nanex"]["source_date_rows"] == 105
    assert current["NxCore Historical by Nanex"]["underlying_date_pairs"] == 464

    cboe = current["Cboe All Access historical"]
    assert cboe["source_date_rows"] == 309
    assert cboe["underlying_date_pairs"] == 3364
    assert cboe["historical_segment"] == ["2012-01-03", "2015-05-20"]
    assert cboe["pricing_status"] == "FREE_TRIAL_TECHNICAL_SCREEN"
    assert "DELETE_RETURN" in cboe["retention_status"]

    cheapest = payload["conditional_cheapest_full_option_route"]
    assert cheapest["status"] == "PREFERRED_IF_CBOE_RETENTION_AND_HISTORICAL_NBBO_RUNTIME_CLEAR"
    assert cheapest["expected_vendor_count"] == 2
    assert cheapest["coverage_accounting"] == {
        "source_date_rows_per_record_kind": 414,
        "underlying_date_pairs_per_record_kind": 3828,
        "record_kinds": ["option_trade", "option_quote"],
    }
    segments = {item["vendor"]: item for item in cheapest["segments"]}
    assert segments["LSEG OR NxCore competitive 2011 quote"]["source_date_rows_per_record_kind"] == 105
    assert segments["LSEG OR NxCore competitive 2011 quote"]["underlying_date_pairs_per_record_kind"] == 464
    assert segments["Cboe All Access historical"]["source_date_rows_per_record_kind"] == 309
    assert segments["Cboe All Access historical"]["underlying_date_pairs_per_record_kind"] == 3364
    assert segments["Cboe All Access historical"]["trial_base_price_usd"] == 0
    assert "reference/options" in cheapest["activation_rule"]
    assert cheapest["validated_coverage_claimed"] is False


def test_full_range_and_fallback_candidates_remain_fail_closed():
    payload = alternatives.build_alternatives()
    by_vendor = {item["vendor"]: item for item in payload["alternatives"]}

    nx = by_vendor["NxCore Historical by Nanex"]
    assert nx["documented_history_start_year"] == 2004
    assert nx["eligible_trade_rows"] == 414
    assert nx["eligible_quote_rows"] == 414
    assert nx["eligible_pairs_per_record_kind"] == 3828
    assert nx["targeted_2011_residual_rows_per_record_kind"] == 105
    assert nx["targeted_2011_residual_pairs_per_record_kind"] == 464
    assert nx["delisted_symbol_support"] == "PUBLICLY_DOCUMENTED"
    assert nx["license_fit"] == "ONE_TIME_PRICE_RETENTION_AND_NONDISPLAY_TERMS_PENDING"

    lseg = by_vendor["LSEG OPRA Tick History"]
    assert lseg["eligible_trade_rows"] == 414
    assert lseg["eligible_quote_rows"] == 414
    assert lseg["eligible_pairs_per_record_kind"] == 3828

    cboe = by_vendor["Cboe All Access historical"]
    assert cboe["route_status"] == "ZERO_COST_TECHNICAL_SCREEN_RETENTION_BLOCKED"
    assert cboe["documented_opra_floor_year"] == 2012
    assert cboe["eligible_trade_rows"] == 309
    assert cboe["candidate_quote_rows"] == 309
    assert cboe["trial_base_price_usd"] == 0
    assert "RETENTION" in cboe["license_fit"]

    theta = by_vendor["ThetaData Options PRO"]
    assert theta["route_status"] == "CHEAP_CONDITIONAL_FALLBACK"
    assert theta["public_retail_monthly_price_usd"] == 160.00
    assert theta["eligible_trade_rows"] == 291
    assert theta["eligible_quote_rows"] == 291
    assert theta["pre_history_residual_rows_per_record_kind"] == 123
    assert theta["pre_history_residual_pairs_per_record_kind"] == 814

    databento = by_vendor["Databento OPRA.PILLAR Trades"]
    assert databento["eligible_trade_rows"] == 226
    assert databento["eligible_trade_underlying_date_pairs"] == 2875
    assert "TRADE_ONLY" in databento["route_status"]

    rejected = {item["vendor"]: item for item in payload["rejected_routes"]}
    ise = rejected["ISE Historical Options Tick Data (HOT Data)"]
    assert ise["route_status"] == "DISCONTINUED_DO_NOT_USE_STALE_PRICING"
    assert ise["discontinued_year"] == 2015

    fallback = payload["fallback_if_cboe_retention_or_quote_fails"]
    assert fallback["status"] == "THETADATA_PLUS_PREHISTORY_VENDOR_CONDITIONAL"
    fallback_segments = {item["vendor"]: item for item in fallback["segments"]}
    assert fallback_segments["LSEG OR NxCore pre-Theta historical"]["source_date_rows_per_record_kind"] == 123
    assert fallback_segments["ThetaData Options PRO"]["source_date_rows_per_record_kind"] == 291

    assert payload["policy"] == {
        "do_not_replace_routes_without_license_clearance": True,
        "temporary_trial_access_is_not_retention_authority": True,
        "strict_option_quote_universe_requires_contract_enumeration": True,
        "do_not_count_conflicting_history_as_proven": True,
        "candidate_is_not_coverage": True,
        "do_not_purchase_automatically": True,
        "validated_g2_coverage_unchanged": True,
    }


def test_committed_options_cost_alternatives_match_generator():
    assert json.loads(COMMITTED.read_text(encoding="utf-8")) == alternatives.build_alternatives()
