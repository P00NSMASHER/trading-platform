from pathlib import Path

import g2_massive_equity_plan as planner


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_massive_plan_matches_frozen_equity_scope_and_fails_closed():
    result = planner.build_plan(planner.load_requirements(REQ))

    assert result["frozen_scope"] == {
        "equity_trade_source_date_rows": 414,
        "equity_quote_source_date_rows": 414,
        "equity_source_date_rows_total": 828,
        "equity_symbol_date_pairs_per_record_kind": 3828,
        "unique_historical_symbols": 146,
        "first_required_date": "2011-03-21",
        "last_required_date": "2015-05-20",
    }

    candidate = result["candidate"]
    assert candidate["history_start"] == "2003-09-10"
    assert candidate["active_and_delisted_tickers_documented"] is True
    assert candidate["tick_trades_documented"] is True
    assert candidate["nbbo_quotes_documented"] is True
    assert candidate["individual_advanced"]["published_monthly_usd"] == 199
    assert candidate["individual_advanced"]["eligibility"] == "individual_use_non_pros_only"
    assert candidate["business"]["published_monthly_usd"] == 2499
    assert candidate["coverage_status"] == "CANDIDATE_NOT_COUNTED"
    assert "Never infer eligibility" in candidate["selection_rule"]
    assert candidate["individual_advanced"]["g2_purchase_status"] == "NOT_PURCHASED"
    assert candidate["business"]["g2_purchase_status"] == "NOT_PURCHASED"
