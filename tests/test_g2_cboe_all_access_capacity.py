from pathlib import Path

import g2_cboe_all_access_capacity as capacity


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"


def test_cboe_all_access_tier3_capacity_matches_frozen_scope():
    payload = capacity.build_capacity(capacity.load_requirements(REQ))

    assert payload["frozen_scope"] == {
        "champion_minimum_source_date_rows": 1242,
        "equity_source_date_rows": 828,
        "option_trade_source_date_rows": 414,
        "cboe_supported_option_trade_source_date_rows": 309,
        "unsupported_2011_option_trade_source_date_rows": 105,
        "equity_symbol_date_pairs": 3828,
        "option_symbol_date_pairs": 3828,
        "cboe_supported_option_symbol_date_pairs": 3364,
        "unsupported_2011_option_symbol_date_pairs": 464,
    }

    model = payload["candidate_request_model"]
    assert model["equity_endpoint"] == "time-and-sales/trades-and-quotes"
    assert model["equity_mode"] == "ALL_QUOTES"
    assert model["equity_first_page_requests"] == 3828
    assert model["equity_first_page_points"] == 57420
    assert model["option_endpoint"] == "time-and-sales/option-trades"
    assert model["option_first_page_requests"] == 3364
    assert model["option_first_page_points"] == 50460
    assert model["total_first_page_requests"] == 7192
    assert model["total_first_page_points"] == 107880
    assert model["tier3_first_page_point_fraction"] == 107880 / 1_250_000
    assert model["tier3_max_15_point_requests"] == 83333
    assert model["tier3_spare_15_point_requests_after_first_pages"] == 76141
    assert model["average_total_pages_per_symbol_date_pair_supported"] == 83333 / 7192
    assert model["average_extra_pages_per_symbol_date_pair_supported"] == 76141 / 7192


def test_cboe_all_access_free_trial_acceptance_probe_is_minimal_and_non_purchase():
    payload = capacity.build_capacity(capacity.load_requirements(REQ))
    probe = payload["free_trial_acceptance_probe"]

    assert probe["total_points"] == 30
    assert probe["equity"]["date"] == "2012-01-03"
    assert probe["equity"]["symbol"] == "AF"
    assert probe["equity"]["endpoint"] == "time-and-sales/trades-and-quotes"
    assert probe["equity"]["mode"] == "ALL_QUOTES"
    assert probe["equity"]["limit"] == 10000
    assert {
        "timestamp",
        "underlying_trade_price",
        "underlying_trade_size",
        "bid",
        "ask",
        "bid_size",
        "ask_size",
    }.issubset(set(probe["equity"]["required_fields"]))

    assert probe["option"]["date"] == "2012-01-03"
    assert probe["option"]["symbol"] == "AF"
    assert probe["option"]["endpoint"] == "time-and-sales/option-trades"
    assert probe["option"]["limit"] == 10000
    assert {
        "timestamp",
        "security",
        "root",
        "expiry",
        "strike",
        "option_type",
        "option_trade_price",
        "option_trade_size",
    }.issubset(set(probe["option"]["required_fields"]))

    assert "must not be purchased" in payload["warning"]


def test_cboe_all_access_capacity_keeps_validation_gates_explicit():
    payload = capacity.build_capacity(capacity.load_requirements(REQ))
    assert len(payload["gates_before_purchase"]) == 4
    assert any("pagination" in gate.lower() for gate in payload["gates_before_purchase"])
    assert any("production" in gate.lower() for gate in payload["gates_before_purchase"])
    assert any("license" in gate.lower() for gate in payload["gates_before_purchase"])


def test_cboe_capacity_marks_2011_option_trades_out_of_scope():
    payload = capacity.build_capacity(capacity.load_requirements(REQ))
    assert payload["out_of_scope"] == {
        "option_trade_source_date_rows": 105,
        "option_symbol_date_pairs": 464,
        "historical_range": ["2011-03-21", "2011-12-30"],
        "reason": "Cboe Data Vantage confirmed OPRA-related datasets begin in 2012.",
    }
    assert payload["documented_vendor_facts"]["vendor_confirmed_opra_earliest_year"] == 2012
