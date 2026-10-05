from pathlib import Path

import g2_cboe_free_trial_planner as planner


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_cboe_trial_planner_fails_closed_on_public_vendor_capacity_conflict():
    result = planner.plan(planner._read(REQ))

    assert result["schema_version"] == "4"
    assert result["provenance_reconciliation"] == {
        "vendor_confirmed_opra_earliest_year": 2012,
        "opra_history_reply_date": "2026-09-30",
        "trial_limit_clarification_date": "2026-10-02",
        "public_option_trades_reference_generic_earliest_year": 2003,
        "planner_earliest_year": 2012,
        "manifest_first_date": "2012-01-03",
        "manifest_last_date": "2015-05-20",
        "trial_capacity_status": "UNRESOLVED_PUBLIC_VENDOR_CONFLICT",
    }
    assert result["documented_trial"] == {
        "days": 14,
        "published_points_per_day": 500,
        "published_overage_available_for_trial": False,
        "published_requests_per_day_at_15_points": 33,
        "published_max_first_page_requests": 462,
        "credit_card_authorization_required": True,
        "trial_sip_access": False,
        "signup_exceed_daily_credit_limit_setting_vendor_guidance": "ALLOW",
        "vendor_email_says_daily_credit_limit_gates_trial": False,
        "vendor_email_conflicts_with_current_public_terms": True,
        "historical_option_trades_access": "VENDOR_CONFIRMED_ELIGIBLE_RUNTIME_NOT_VERIFIED",
    }

    assert result["eligible_source_date_rows"] == 309
    assert result["eligible_underlying_date_pairs"] == 3364
    assert result["candidate_complete_source_date_rows"] == 180
    assert result["candidate_complete_underlying_date_pairs"] == 460
    assert result["remaining_source_date_rows"] == 129
    assert result["remaining_underlying_date_pairs"] == 2904
    assert len(result["selected_dates"]) == 180
    assert len(result["all_eligible_dates"]) == 309

    capacity = result["capacity_model"]
    assert capacity["status"] == "CONSERVATIVE_PUBLIC_CAP_UPPER_BOUND"
    assert capacity["published_daily_point_limit_used_as_hard_trial_cap"] is True
    assert capacity["required_first_page_requests"] == 3364
    assert capacity["nominal_first_page_points"] == 50460
    assert capacity["public_trial_total_nominal_points"] == 7000
    assert capacity["public_max_first_page_requests"] == 462
    assert capacity["public_selected_first_page_requests"] == 460
    assert capacity["public_selected_first_page_points"] == 6900
    assert capacity["remaining_source_date_rows_due_to_credit_limit"] == 129
    assert capacity["remaining_underlying_date_pairs_due_to_credit_limit"] == 2904
    assert capacity["pagination_can_only_reduce_candidate_coverage"] is True

    assert result["pagination_verified"] is True
    assert result["trial_historical_access_runtime_verified"] is False
    assert result["trial_capacity_override_runtime_verified"] is False
    assert result["per_pair_record_counts_known"] is False
    assert result["coverage_claimed"] is False
    assert any("Explicit user authorization" in x for x in result["gates_before_use"])
    assert any("acceptance probe" in x for x in result["gates_before_use"])
    assert any("500-points/day" in x for x in result["gates_before_use"])
    assert any("Order Form" in x for x in result["gates_before_use"])


def test_public_cap_first_page_plan_is_optimal_by_complete_date_count():
    rows = planner._eligible_option_trades(planner._read(REQ))
    selected, used = planner._public_cap_first_page_plan(rows)

    ranked_counts = sorted(int(row["symbol_date_pair_count"]) for row in rows)
    assert len(selected) == 180
    assert used == 460
    assert sum(ranked_counts[:180]) == 460
    assert sum(ranked_counts[:181]) > planner.PUBLIC_MAX_FIRST_PAGE_REQUESTS


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
    assert committed["trial_capacity_override_runtime_verified"] is False
    assert committed["coverage_claimed"] is False
