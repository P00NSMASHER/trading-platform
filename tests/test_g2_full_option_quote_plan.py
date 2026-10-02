import json
from pathlib import Path

import g2_full_option_quote_plan as plan


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"
BLUEPRINT = ROOT / "data/processed/real_data_release_sprint/production_source_contract_blueprint.json"
COMMITTED = ROOT / "data/processed/g2_vendor_requests/full_replication_option_quote_plan.json"


def test_full_option_quote_plan_matches_frozen_full_replication_scope():
    payload = plan.build_plan(REQ, BLUEPRINT)

    assert payload["champion_minimum_source_date_rows"] == 1242
    assert payload["full_replication_source_date_rows"] == 1656
    assert payload["additional_option_quote_source_date_rows"] == 414
    assert payload["additional_option_quote_symbol_date_pairs"] == 3828
    assert payload["packet_count"] == 3

    by_route = {packet["route"]: packet for packet in payload["packets"]}

    lseg = by_route["candidate_lseg_opra_tick_quotes_2011"]
    assert lseg["source_date_rows"] == 105
    assert lseg["symbol_date_pair_count"] == 464
    assert lseg["unique_historical_symbols"] == 35
    assert lseg["first_trade_date"] == "2011-03-21"
    assert lseg["last_trade_date"] == "2011-12-30"

    cboe = by_route["candidate_cboe_custom_tick_quotes_2012_2013"]
    assert cboe["source_date_rows"] == 178
    assert cboe["symbol_date_pair_count"] == 1186
    assert cboe["unique_historical_symbols"] == 53
    assert cboe["first_trade_date"] == "2012-01-03"
    assert cboe["last_trade_date"] == "2013-10-22"

    algoseek = by_route["candidate_algoseek_opra_tick_quotes_2014_2015"]
    assert algoseek["source_date_rows"] == 131
    assert algoseek["symbol_date_pair_count"] == 2178
    assert algoseek["unique_historical_symbols"] == 86
    assert algoseek["first_trade_date"] == "2014-11-07"
    assert algoseek["last_trade_date"] == "2015-05-20"

    expected_fields = {
        "timestamp_or_date+time",
        "underlying_symbol",
        "option_symbol",
        "expiration",
        "strike",
        "option_type",
        "bid",
        "ask",
        "bid_size",
        "ask_size",
    }
    for packet in payload["packets"]:
        assert set(packet["required_canonical_fields"]) == expected_fields
        assert "no minute-bar or interval-snapshot substitution" in packet[
            "fidelity_requirements"
        ]
        assert packet["request_policy"]["quote_or_availability_request_only"] is True
        assert packet["request_policy"]["do_not_purchase_automatically"] is True
        assert packet["request_policy"]["delivery_does_not_count_as_g2_until_validated"] is True


def test_committed_full_option_quote_plan_matches_generator():
    generated = plan.build_plan(REQ, BLUEPRINT)
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert generated == committed
