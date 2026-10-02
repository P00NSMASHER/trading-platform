from pathlib import Path

import g2_cboe_free_trial_plan as plan


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_legacy_2011_cboe_plan_is_fail_closed():
    rows = plan.load_2011_option_requirements(REQ)
    out = plan.build_plan(rows)

    assert len(rows) == 105
    assert sum(r["request_count"] for r in rows) == 464
    assert out["schema_version"] == "2"
    assert out["vendor_provenance"] == {
        "vendor_confirmed_opra_earliest_year": 2012,
        "history_reply_date": "2026-09-30",
        "trial_confirmation_date": "2026-10-02",
        "reason": "Cboe Data Vantage states OPRA-related datasets are available from 2012 onward.",
    }
    assert out["frozen_2011_scope"] == {
        "source_date_rows": 105,
        "underlying_date_pairs": 464,
        "first_trade_date": "2011-03-21",
        "last_trade_date": "2011-12-30",
    }
    assert out["cboe_eligible"] is False
    assert out["scheduled_first_page_requests"] == 0
    assert out["scheduled_points"] == 0
    assert out["covered_source_dates"] == 0
    assert out["residual_source_dates"] == 105
    assert out["residual_symbol_date_pairs"] == 464
    assert len(out["residual"]) == 105
    assert out["requests"] == []
    assert out["coverage_claimed"] is False
    assert "Do not activate or use the Cboe All Access trial for these 2011 OPRA rows" in out["warning"]


def test_legacy_2011_cboe_plan_keeps_reserved_requests_metadata_only():
    rows = plan.load_2011_option_requirements(REQ)
    out = plan.build_plan(rows, reserved_requests=46)

    assert out["reserved_requests_for_pagination"] == 46
    assert out["scheduled_first_page_requests"] == 0
    assert out["residual_source_dates"] == 105
    assert out["residual_symbol_date_pairs"] == 464


def test_legacy_2011_cboe_plan_rejects_non_2011_rows():
    rows = plan.load_2011_option_requirements(REQ)
    bad = [dict(rows[0], trade_date="2012-01-03")]
    import pytest

    with pytest.raises(ValueError, match="only 2011 option-trade rows"):
        plan.build_plan(bad)
