from pathlib import Path

import g2_cboe_free_trial_planner as planner


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_cboe_trial_planner_reconciles_vendor_reply_with_public_trial_cap():
    result = planner.plan(planner._read(REQ))

    assert result["schema_version"] == "4"
    provenance = result["provenance_reconciliation"]
    assert provenance["vendor_confirmed_opra_earliest_year"] == 2012
    assert provenance["opra_history_reply_date"] == "2026-09-30"
    assert provenance["trial_limit_clarification_date"] == "2026-10-02"
    assert provenance["public_trial_page_recheck_date"] == "2026-10-05"
    assert provenance["public_option_trades_reference_generic_earliest_year"] == 2003
    assert provenance["planner_earliest_year"] == 2012
    assert provenance["manifest_first_date"] == "2012-01-03"
    assert provenance["manifest_last_date"] == "2015-05-20"
    assert provenance["trial_capacity_guidance_conflict"] is True

    trial = result["documented_trial"]
    assert trial == {
        "days": 14,
        "published_points_per_day": 500,
        "credit_card_authorization_required": True,
        "trial_sip_access": False,
        "signup_exceed_setting": "ALLOW",
        "published_trial_overage_available": False,
        "daily_point_limit_used_as_hard_planning_cap": True,
        "historical_option_trades_access": "VENDOR_CONFIRMED_ELIGIBLE_RUNTIME_NOT_VERIFIED",
    }


def test_trade_only_free_trial_capacity_is_fail_closed_and_optimal():
    result = planner.plan(planner._read(REQ))

    assert result["required_source_date_rows"] == 309
    assert result["required_underlying_date_pairs"] == 3364

    capacity = result["capacity_model"]
    assert capacity["scope"] == "OPTION_TRADES_FIRST_PAGE_ONLY"
    assert capacity["published_daily_point_limit_used_as_hard_trial_cap"] is True
    assert capacity["max_first_page_trade_requests_per_day"] == 33
    assert capacity["unused_points_per_day_after_trade_requests"] == 5
    assert capacity["max_first_page_trade_requests_over_trial"] == 462
    assert capacity["required_first_page_requests"] == 3364
    assert capacity["nominal_first_page_points"] == 50460

    assert result["candidate_complete_source_date_rows"] == 180
    assert result["candidate_complete_underlying_date_pairs"] == 460
    assert result["remaining_source_date_rows"] == 129
    assert result["remaining_underlying_date_pairs"] == 2904
    assert len(result["selected_dates"]) == 180

    certificate = capacity["optimality_certificate"]
    assert certificate == {
        "180_cheapest_complete_dates_requests": 460,
        "181_cheapest_complete_dates_requests": 467,
        "request_budget": 462,
        "maximum_complete_source_dates": 180,
    }


def test_quote_capacity_remains_unmodeled_and_never_becomes_coverage():
    result = planner.plan(planner._read(REQ))
    quote = result["strict_option_quote_capacity"]

    assert quote["status"] == "UNMODELED_FAIL_CLOSED"
    assert quote["reference_options_points_per_underlying_date"] == 1
    assert quote["historical_quote_points_per_contract_page"] == 15
    assert quote["full_replication_free_trial_claimed"] is False
    assert result["pagination_mechanics_documented"] is True
    assert result["pagination_runtime_verified"] is False
    assert result["trial_historical_access_runtime_verified"] is False
    assert result["per_pair_record_counts_known"] is False
    assert result["coverage_claimed"] is False


def test_cboe_trial_planner_filters_out_pre_2012_and_non_option_rows():
    rows = planner._read(REQ)
    eligible = planner._eligible_option_trades(rows)

    assert len(eligible) == 309
    assert all(row["record_kind"] == "option_trade" for row in eligible)
    assert all(row["trade_date"] >= "2012-01-01" for row in eligible)


def test_committed_cboe_trial_capacity_plan_matches_planner():
    import json

    generated = planner.plan(planner._read(REQ))
    committed = json.loads(
        (ROOT / "data/processed/g2_vendor_requests/cboe_trial_capacity_plan.json").read_text(
            encoding="utf-8"
        )
    )
    assert generated == committed
    assert committed["trial_historical_access_runtime_verified"] is False
    assert committed["coverage_claimed"] is False
