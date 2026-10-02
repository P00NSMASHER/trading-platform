from pathlib import Path

import g2_cboe_free_trial_plan as plan


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_cboe_free_trial_plan_respects_vendor_confirmed_2012_history_floor():
    rows = plan.load_option_trade_requirements(REQ)
    out = plan.build_plan(rows)

    assert len(rows) == 414
    assert sum(int(r["request_count"]) for r in rows) == 3828

    assert out["vendor_confirmed_opra_start"] == "2012-01-01"
    assert out["eligible_source_dates"] == 309
    assert out["eligible_symbol_date_pairs"] == 3364
    assert out["ineligible_pre_2012_source_dates"] == 105
    assert out["ineligible_pre_2012_symbol_date_pairs"] == 464
    assert out["ineligible_pre_2012_first_date"] == "2011-03-21"
    assert out["ineligible_pre_2012_last_date"] == "2011-12-30"


def test_cboe_free_trial_plan_never_emits_a_2011_request():
    out = plan.build_plan(plan.load_option_trade_requirements(REQ))

    assert len(out["requests"]) == 3364
    assert all(row["trade_date"] >= "2012-01-01" for row in out["requests"])
    assert not any(row["trade_date"].startswith("2011-") for row in out["requests"])
    assert all(
        row["points_per_historical_request"] == 15
        and row["limit"] == 10000
        and row["seq_no"] == 0
        for row in out["requests"]
    )


def test_cboe_free_trial_plan_uses_vendor_trial_credit_guidance_fail_closed():
    out = plan.build_plan(plan.load_option_trade_requirements(REQ))

    assert out["free_trial_days"] == 14
    assert out["daily_credit_limit_enforced_for_plan"] is False
    assert "Ryan Lusk" in out["daily_credit_limit_basis"]
    assert "no 2011 request is emitted" in out["warning"]
    assert "acceptance probe" in out["warning"]
    assert "rate limits" in out["warning"]
