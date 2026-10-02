from datetime import date
from pathlib import Path

import g2_databento_probe as probe


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"
CHAMPION_REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_databento_probe_matches_frozen_g2_requirements():
    manifest = probe.build_probe_manifest(probe.load_requirements(REQ))

    assert manifest["dataset"] == "OPRA.PILLAR"
    assert manifest["databento_historical_start"] == "2013-04-01"
    assert manifest["total_required_option_dates"] == 414
    assert manifest["eligible_option_dates"] == 226
    assert manifest["ineligible_pre_databento_dates"] == 188
    assert manifest["eligible_underlying_date_pairs"] == 2875
    assert manifest["candidate_direct_g2_rows"] == 226
    assert manifest["quote_trial_rows_not_counted"] == 226

    assert all(
        date.fromisoformat(row["trade_date"]) >= date(2013, 4, 1)
        for row in manifest["eligible"]
    )
    assert all(
        date.fromisoformat(day) < date(2013, 4, 1)
        for day in manifest["ineligible_dates"]
    )


def test_trade_requests_are_direct_candidates_but_quote_trials_are_not_counted():
    manifest = probe.build_probe_manifest(probe.load_requirements(REQ))

    for row in manifest["eligible"]:
        trade = row["requests"]["option_trade"]
        quote = row["requests"]["option_quote_trial"]

        assert trade["dataset"] == "OPRA.PILLAR"
        assert trade["schema"] == "trades"
        assert trade["stype_in"] == "parent"
        assert trade["g2_status"] == "candidate_direct_coverage"

        assert quote["dataset"] == "OPRA.PILLAR"
        assert quote["schema"] == "cbbo-1m"
        assert quote["g2_status"] == "fidelity_review_required_not_counted"
        assert "not historical tick-by-tick" in quote["reason"]

        assert all(symbol.endswith(".OPT") for symbol in trade["symbols"])
        assert trade["symbols"] == quote["symbols"]
        assert "estimated_cost_usd" not in trade
        assert "estimated_cost_usd" not in quote


def test_day_bounds_preserve_new_york_timezone():
    start, end = probe._day_bounds(date(2013, 4, 1))
    assert start == "2013-04-01T00:00:00-04:00"
    assert end == "2013-04-02T00:00:00-04:00"

    start, end = probe._day_bounds(date(2014, 12, 18))
    assert start == "2014-12-18T00:00:00-05:00"
    assert end == "2014-12-19T00:00:00-05:00"


def test_databento_probe_matches_champion_minimum_scope():
    manifest = probe.build_probe_manifest(probe.load_requirements(CHAMPION_REQ))

    assert manifest["total_required_option_dates"] == 414
    assert manifest["eligible_option_dates"] == 226
    assert manifest["ineligible_pre_databento_dates"] == 188
    assert manifest["eligible_underlying_date_pairs"] == 2875
    assert manifest["candidate_direct_g2_rows"] == 226
    assert manifest["champion_minimum_total_rows"] == 1242
    assert manifest["candidate_champion_minimum_rows"] == 226
    assert manifest["remaining_champion_minimum_rows_after_all_eligible_option_trades"] == 1016
    assert manifest["candidate_champion_minimum_fraction"] == 226 / 1242
