from pathlib import Path

import g2_vendor_quote_packets as packets


ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "data/processed/g2_vendor_requests"
SOURCE_BLUEPRINT = ROOT / "data/processed/real_data_release_sprint/production_source_contract_blueprint.json"


def test_vendor_quote_packets_match_frozen_scope():
    payload = packets.build_packets(VENDOR_DIR, SOURCE_BLUEPRINT)

    assert payload["packet_count"] == 5
    assert payload["champion_minimum_source_date_rows"] == 1242
    assert payload["total_record_kind_symbol_date_pairs"] == 11484

    by_route = {packet["route"]: packet for packet in payload["packets"]}

    assert by_route["candidate_tickdata_equity_trades"]["source_date_rows"] == 414
    assert by_route["candidate_tickdata_equity_trades"]["symbol_date_pair_count"] == 3828
    assert by_route["candidate_tickdata_equity_trades"]["first_trade_date"] == "2011-03-21"
    assert by_route["candidate_tickdata_equity_trades"]["last_trade_date"] == "2015-05-20"

    assert by_route["candidate_tickdata_equity_nbbo_quotes"]["source_date_rows"] == 414
    assert by_route["candidate_tickdata_equity_nbbo_quotes"]["symbol_date_pair_count"] == 3828
    assert "no interval-snapshot substitution" in by_route[
        "candidate_tickdata_equity_nbbo_quotes"
    ]["fidelity_requirements"]

    assert by_route["candidate_databento_opra_trades"]["source_date_rows"] == 226
    assert by_route["candidate_databento_opra_trades"]["symbol_date_pair_count"] == 2875
    assert by_route["candidate_databento_opra_trades"]["first_trade_date"] == "2013-04-01"

    assert by_route["candidate_cboe_option_trades"]["source_date_rows"] == 83
    assert by_route["candidate_cboe_option_trades"]["symbol_date_pair_count"] == 489
    assert by_route["candidate_cboe_option_trades"]["first_trade_date"] == "2012-01-03"
    assert by_route["candidate_cboe_option_trades"]["last_trade_date"] == "2013-03-28"

    assert by_route["candidate_lseg_opra_tick_history"]["source_date_rows"] == 105
    assert by_route["candidate_lseg_opra_tick_history"]["symbol_date_pair_count"] == 464
    assert by_route["candidate_lseg_opra_tick_history"]["first_trade_date"] == "2011-03-21"
    assert by_route["candidate_lseg_opra_tick_history"]["last_trade_date"] == "2011-12-30"

    for packet in payload["packets"]:
        assert packet["required_canonical_fields"]
        assert packet["request_policy"]["quote_or_availability_request_only"] is True
        assert packet["request_policy"]["do_not_purchase_automatically"] is True
        assert packet["request_policy"]["delivery_does_not_count_as_g2_until_validated"] is True


def test_committed_vendor_quote_packets_match_generator():
    import json

    generated = packets.build_packets(VENDOR_DIR, SOURCE_BLUEPRINT)
    committed = json.loads(
        (VENDOR_DIR / "vendor_quote_packets.json").read_text(encoding="utf-8")
    )
    assert generated == committed
