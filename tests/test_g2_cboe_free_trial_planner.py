from pathlib import Path

import g2_cboe_free_trial_planner as planner


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/g2_vendor_requests/cboe_option_trades.csv"


def test_cboe_trial_planner_matches_frozen_scope_and_vendor_provenance():
    result = planner.plan(planner._read(REQ))

    assert result["provenance_reconciliation"] == {
        "vendor_confirmed_opra_earliest_year": 2012,
        "vendor_reply_date": "2026-09-30",
        "public_option_trades_reference_generic_earliest_year": 2003,
        "planner_earliest_year": 2012,
        "reason": (
            "The public API reference's generic 2003 history statement is not used as provenance "
            "for OPRA Option Trades. Cboe Data Vantage states OPRA-related datasets begin in 2012."
        ),
        "manifest_first_date": "2012-01-03",
        "manifest_last_date": "2013-03-28",
    }
    assert result["documented_trial"] == {
        "days": 14,
        "points_per_day": 500,
        "credit_card_authorization_required": True,
        "trial_sip_access": False,
        "overage_available": False,
        "historical_option_trades_access": "documented_eligible_not_runtime_verified",
        "historical_access_basis": (
            "The All Access product page says the trial is not eligible for SIP access, while "
            "the Option Trades reference prices historical requests at 15 points and states that "
            "SIP subscription is required for live or delayed requests. No trial was activated."
        ),
    }
    assert result["documented_historical_option_trades"] == {
        "earliest_year": 2012,
        "points_per_request": 15,
        "symbol_parameter": "single underlying symbol or OSI option string",
        "max_records_per_request": 10000,
        "pagination_parameter": "seq_no",
        "pagination_points_per_page": 15,
        "pagination_charge_basis": (
            "Each pagination page is a separate historical Option Trades request; the endpoint "
            "charges 15 points per historical request."
        ),
    }

    assert result["required_source_date_rows"] == 83
    assert result["required_underlying_date_pairs"] == 489
    assert result["max_requests_per_day"] == 33
    assert result["daily_unused_points_at_request_cap"] == 5
    assert result["optimistic_request_budget"] == 462
    assert result["optimistic_complete_source_date_rows"] == 81
    assert result["optimistic_complete_underlying_date_pairs"] == 445
    assert result["optimistic_points_used"] == 6675
    assert result["unused_request_slots"] == 17
    assert result["remaining_source_date_rows"] == 2
    assert result["remaining_underlying_date_pairs"] == 44
    assert result["remaining_dates"] == [
        {"trade_date": "2012-01-20", "symbol_date_pair_count": 22},
        {"trade_date": "2012-01-23", "symbol_date_pair_count": 22},
    ]

    assert result["pagination_verified"] is True
    assert result["trial_historical_access_runtime_verified"] is False
    assert result["per_pair_record_counts_known"] is False
    assert result["coverage_claimed"] is False


def test_cboe_trial_planner_respects_daily_point_cap():
    result = planner.plan(planner._read(REQ))
    assert result["max_requests_per_day"] * 15 <= 500
    assert (result["max_requests_per_day"] + 1) * 15 > 500
    assert result["optimistic_request_budget"] == 14 * result["max_requests_per_day"]
    assert result["optimistic_points_used"] <= 14 * 500
