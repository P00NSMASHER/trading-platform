from pathlib import Path

import g2_vendor_acquisition_handoff as handoff


ROOT = Path(__file__).resolve().parents[1]
REQUEST_DIR = ROOT / "data/processed/real_data_release_sprint/vendor_requests"
BLUEPRINT = ROOT / "data/processed/real_data_release_sprint/production_source_contract_blueprint.json"
COMMITTED = REQUEST_DIR / "vendor_acquisition_handoff.json"


def test_vendor_acquisition_handoff_matches_frozen_scope():
    payload = handoff.build_handoff(REQUEST_DIR, BLUEPRINT)

    assert payload["champion_minimum_source_date_rows"] == 1242
    assert payload["total_record_kind_symbol_date_pairs"] == 11484
    assert payload["credential_policy"].startswith("Credentials must never")
    assert [step["module"] for step in payload["operator_sequence"]] == [
        "licensed_data_intake",
        "g2_vendor_delivery_preflight",
        "licensed_data_drop_processor",
        "g2_vendor_content_preflight",
        "historical_market_backfill / real_data_replay",
    ]
    assert payload["operator_sequence"][3]["required_result"].startswith(
        "ready_for_coverage_audit=true"
    )

    routes = payload["handoffs"]
    assert routes["candidate_tickdata_equity_trades"]["source_date_rows"] == 414
    assert routes["candidate_tickdata_equity_trades"]["symbol_date_pair_count"] == 3828
    assert routes["candidate_tickdata_equity_trades"]["first_trade_date"] == "2011-03-21"
    assert routes["candidate_tickdata_equity_trades"]["last_trade_date"] == "2015-05-20"

    assert routes["candidate_tickdata_equity_nbbo_quotes"]["source_date_rows"] == 414
    assert routes["candidate_tickdata_equity_nbbo_quotes"]["symbol_date_pair_count"] == 3828
    assert "interval snapshots do not satisfy" in routes[
        "candidate_tickdata_equity_nbbo_quotes"
    ]["fidelity_requirement"]

    assert routes["candidate_databento_opra_trades"]["source_date_rows"] == 226
    assert routes["candidate_databento_opra_trades"]["symbol_date_pair_count"] == 2875
    assert routes["candidate_databento_opra_trades"]["first_trade_date"] == "2013-04-01"

    assert routes["candidate_cboe_option_trades"]["source_date_rows"] == 83
    assert routes["candidate_cboe_option_trades"]["symbol_date_pair_count"] == 489
    assert routes["candidate_cboe_option_trades"]["first_trade_date"] == "2012-01-03"
    assert routes["candidate_cboe_option_trades"]["last_trade_date"] == "2013-03-28"

    assert routes["candidate_lseg_opra_tick_history"]["source_date_rows"] == 105
    assert routes["candidate_lseg_opra_tick_history"]["symbol_date_pair_count"] == 464
    assert routes["candidate_lseg_opra_tick_history"]["first_trade_date"] == "2011-03-21"
    assert routes["candidate_lseg_opra_tick_history"]["last_trade_date"] == "2011-12-30"

    for route in routes.values():
        assert route["status"] == "CANDIDATE_SOURCE_AVAILABLE_NOT_ACQUIRED"
        assert route["delivery_contract"]["authorized"] is True
        assert route["delivery_contract"]["license_reference"] == "REQUIRED_NONEMPTY"
        assert route["delivery_contract"]["credentials_in_contract"] == "PROHIBITED"
        assert route["acceptance_checks"]["file_existence_is_not_coverage"] is True
        assert route["acceptance_checks"]["all_required_symbols_must_be_observed"] is True
        assert route["post_activation_content_preflight"] == {
            "module": "g2_vendor_content_preflight",
            "request_manifest": route["request_manifest"],
            "required_result": "ready_for_coverage_audit=true",
            "g2_coverage_counted": False,
        }


def test_committed_vendor_handoff_is_reproducible():
    payload = handoff.build_handoff(REQUEST_DIR, BLUEPRINT)
    import json

    expected = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    assert COMMITTED.read_text(encoding="utf-8") == expected
