import g2_lseg_option_contract_validator as validator


def _plan():
    return {
        "option_underlying_dates": [
            {
                "trade_date": "2015-02-12",
                "historical_symbol": "ACHC",
                "candidate_rics": ["ACHC.O", "ACHC.OQ"],
                "mapping_class": "secondary_repository_candidate",
                "record_kinds": ["option_quote", "option_trade"],
                "statuses": ["historical_date_validation_required"],
                "historical_validation_required": True,
            }
        ]
    }


def test_extract_identifier_strings_walks_search_and_chain_shapes():
    payload = {
        "value": [
            {
                "Identifier": "0#ACHC*.U",
                "Constituents": [
                    {"Identifier": "ACHCC201505000.U"},
                    {"Identifier": "ACHCO201505000.U"},
                ],
            }
        ]
    }
    found = validator.extract_identifier_strings(payload)
    assert "0#ACHC*.U" in found
    assert "ACHCC201505000.U" in found
    assert "ACHCO201505000.U" in found


def test_historical_chain_candidates_are_date_specific_and_deduplicated():
    search = {
        "value": [
            {"Identifier": "ACHCC201505000.U"},
            {"Identifier": "ACHC.O"},
        ]
    }
    chain = {
        "value": [
            {
                "Identifier": "0#ACHC*.U",
                "Constituents": [
                    {"Identifier": "ACHCC201505000.U"},
                    {"Identifier": "ACHCO201505000.U"},
                ],
            }
        ]
    }

    out = validator.validate_discovery(
        plan=_plan(),
        historical_symbol="ACHC",
        trade_date="2015-02-12",
        search_payload=search,
        historical_chain_payload=chain,
    )

    assert out["summary"]["parsed_contracts"] == 2
    assert out["summary"]["historical_chain_candidates"] == 2
    assert out["summary"]["search_only_candidates"] == 0
    assert out["summary"]["historical_contract_set_ready_for_time_and_sales"] is True

    by_ric = {row["source_ric"]: row for row in out["contracts"]}
    call = by_ric["ACHCC201505000.U"]
    put = by_ric["ACHCO201505000.U"]

    assert call["option_type"] == "call"
    assert put["option_type"] == "put"
    assert call["underlying_symbol"] == "ACHC"
    assert call["expiration"] == "2015-03-20"
    assert call["strike"] == 50.0
    assert call["also_seen_in_search"] is True
    assert call["historical_date_evidence"] is True


def test_search_only_contract_stays_fail_closed_for_historical_use():
    out = validator.validate_discovery(
        plan=_plan(),
        historical_symbol="ACHC",
        trade_date="2015-02-12",
        search_payload={"value": [{"Identifier": "ACHCC201505000.U"}]},
    )
    assert out["summary"]["historical_chain_candidates"] == 0
    assert out["summary"]["search_only_candidates"] == 1
    assert out["summary"]["historical_contract_set_ready_for_time_and_sales"] is False
    assert out["contracts"][0]["validation_status"] == (
        "search_candidate_requires_historical_confirmation"
    )


def test_expired_and_wrong_root_contracts_are_rejected():
    chain = {
        "value": [
            {
                "Constituents": [
                    {"Identifier": "ACHCA151505000.U"},
                    {"Identifier": "ALNYC201505000.U"},
                ]
            }
        ]
    }
    out = validator.validate_discovery(
        plan=_plan(),
        historical_symbol="ACHC",
        trade_date="2015-02-12",
        historical_chain_payload=chain,
    )

    assert out["summary"]["parsed_contracts"] == 0
    reasons = {row["source_ric"]: row["reason"] for row in out["rejected"]}
    assert "expired_before_trade_date" in reasons["ACHCA151505000.U"]
    assert "underlying_root_mismatch" in reasons["ALNYC201505000.U"]


def test_unparseable_option_ric_is_rejected_without_crashing():
    out = validator.validate_discovery(
        plan=_plan(),
        historical_symbol="ACHC",
        trade_date="2015-02-12",
        historical_chain_payload={
            "value": [{"Constituents": [{"Identifier": "ACHC_BAD.U"}]}]
        },
    )
    assert out["summary"]["parsed_contracts"] == 0
    assert out["summary"]["rejected_identifiers"] == 1
    assert "unparseable_option_ric" in out["rejected"][0]["reason"]


def test_symbol_date_must_exist_in_frozen_plan():
    try:
        validator.validate_discovery(
            plan=_plan(),
            historical_symbol="ACHC",
            trade_date="2015-02-13",
            historical_chain_payload={},
        )
    except ValueError as exc:
        assert "expected exactly one frozen option-underlying task" in str(exc)
    else:
        raise AssertionError("expected fail-closed frozen-scope validation")
