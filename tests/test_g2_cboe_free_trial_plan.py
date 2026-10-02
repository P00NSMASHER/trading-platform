from pathlib import Path

import g2_cboe_free_trial_plan as plan


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_cboe_free_trial_maximal_2011_plan():
    rows = plan.load_2011_option_requirements(REQ)
    out = plan.build_plan(rows, reserved_requests=0)

    assert len(rows) == 105
    assert sum(r["request_count"] for r in rows) == 464
    assert out["free_trial"]["max_trial_requests"] == 462
    assert out["scheduled_first_page_requests"] == 462
    assert out["scheduled_points"] == 6930
    assert out["covered_source_dates"] == 104
    assert out["residual_source_dates"] == 1
    assert out["residual_symbol_date_pairs"] == 2
    assert out["residual"] == [
        {"trade_date": "2011-03-21", "symbols": ["JNPR", "VMW"], "request_count": 2}
    ]


def test_cboe_free_trial_plan_with_pagination_reserve():
    rows = plan.load_2011_option_requirements(REQ)
    out = plan.build_plan(rows, reserved_requests=46)

    assert out["scheduled_first_page_requests"] == 416
    assert out["scheduled_points"] == 6240
    assert out["covered_source_dates"] == 102
    assert out["residual_source_dates"] == 3
    assert out["residual_symbol_date_pairs"] == 48
    assert [r["trade_date"] for r in out["residual"]] == [
        "2011-03-25",
        "2011-12-27",
        "2011-12-28",
    ]
    assert max(r["trial_day"] for r in out["requests"]) <= 14
    assert all(r["points"] == 15 and r["limit"] == 10000 for r in out["requests"])
    assert "planning upper bound" in out["warning"]


def test_free_trial_daily_request_cap_is_conservative():
    rows = plan.load_2011_option_requirements(REQ)
    out = plan.build_plan(rows, reserved_requests=0)
    counts = {}
    for row in out["requests"]:
        counts[row["trial_day"]] = counts.get(row["trial_day"], 0) + 1

    assert len(counts) == 14
    assert max(counts.values()) <= 33
    assert all(n * 15 <= 500 for n in counts.values())
