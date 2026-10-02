from pathlib import Path

import g2_cboe_free_trial_planner as planner


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_cboe_trial_planner_uses_vendor_confirmed_full_2012plus_scope():
    result = planner.plan(planner._read(REQ))

    assert result["schema_version"] == "3"
    assert result["provenance_reconciliation"] == {
        "vendor_confirmed_opra_earliest_year": 2012,
        "opra_history_reply_date": "2026-09-30",
        "trial_limit_clarification_date": "2026-10-02",
        "public_option_trades_reference_generic_earliest_year": 2003,
        "planner_earliest_year": 2012,
        "manifest_first_date": "2012-01-03",
        "manifest_last_date": "2015-05-20",
    }
    assert result["documented_trial"] == {
        "days": 14,
        "published_points_per_day": 500,
        "credit_card_authorization_required": True,
        "trial_sip_access": False,
        "signup_exceed_daily_credit_limit_setting": "ALLOW",
        "vendor_confirmed_daily_credit_limit_gates_trial": False,
        "historical_option_trades_access": "VENDOR_CONFIRMED_ELIGIBLE_RUNTIME_NOT_VERIFIED",
    }

    assert result["required_source_date_rows"] == 309
    assert result["required_underlying_date_pairs"] == 3364
    assert result["candidate_complete_source_date_rows"] == 309
    assert result["candidate_complete_underlying_date_pairs"] == 3364
    assert result["remaining_source_date_rows"] == 0
    assert result["remaining_underlying_date_pairs"] == 0
    assert len(result["selected_dates"]) == 309
    assert result["selected_dates"][0] == "2012-01-03"
    assert result["selected_dates"][-1] == "2015-05-20"

    capacity = result["capacity_model"]
    assert capacity["published_daily_point_limit_used_as_hard_trial_cap"] is False
    assert capacity["required_first_page_requests"] == 3364
    assert capacity["nominal_first_page_points"] == 50460
    assert capacity["average_first_page_requests_per_trial_day"] == 3364 / 14
    assert capacity["remaining_source_date_rows_due_to_credit_limit"] == 0
    assert capacity["remaining_underlying_date_pairs_due_to_credit_limit"] == 0

    assert result["pagination_verified"] is True
    assert result["trial_historical_access_runtime_verified"] is False
    assert result["per_pair_record_counts_known"] is False
    assert result["coverage_claimed"] is False
    assert any("Explicit user authorization" in x for x in result["gates_before_use"])
    assert any("acceptance probe" in x for x in result["gates_before_use"])
    assert any("seq_no pagination" in x for x in result["gates_before_use"])


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
