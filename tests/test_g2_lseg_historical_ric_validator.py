from datetime import date

import g2_lseg_historical_ric_validator as validator


def _plan():
    return {
        "equity_symbol_dates": [
            {
                "trade_date": "2015-02-12",
                "historical_symbol": "ACHC",
                "candidate_rics": ["ACHC.O", "ACHC.OQ"],
                "mapping_class": "secondary_repository_candidate",
                "record_kinds": ["equity_quote", "equity_trade"],
                "statuses": ["historical_date_validation_required"],
                "historical_validation_required": True,
            },
            {
                "trade_date": "2015-02-12",
                "historical_symbol": "ALSN",
                "candidate_rics": ["ALSN.N"],
                "mapping_class": "secondary_repository_candidate",
                "record_kinds": ["equity_quote", "equity_trade"],
                "statuses": ["historical_date_validation_required"],
                "historical_validation_required": True,
            },
        ]
    }


def test_single_observed_candidate_resolves_symbol_and_counts_lanes():
    rows = [
        {
            "#RIC": "ACHC.O",
            "Date-Time": "2015-02-12T10:00:00-05:00",
            "Type": "Trade",
            "Price": "50.10",
            "Volume": "100",
        },
        {
            "#RIC": "ACHC.O",
            "Date-Time": "2015-02-12T10:00:01-05:00",
            "Type": "Quote",
            "Bid Price": "50.00",
            "Ask Price": "50.20",
        },
    ]
    out = validator.validate_rows(rows, plan=_plan(), trade_date="2015-02-12")
    achc = next(x for x in out["results"] if x["historical_symbol"] == "ACHC")

    assert achc["validation_status"] == "validated_single_candidate"
    assert achc["selected_ric"] == "ACHC.O"
    assert achc["selected_trade_rows"] == 1
    assert achc["selected_quote_rows"] == 1
    assert achc["trade_lane_observed"] is True
    assert achc["quote_lane_observed"] is True
    assert out["summary"]["g2_coverage_change"] is False


def test_multiple_observed_candidates_stay_ambiguous():
    rows = [
        {
            "#RIC": "ACHC.O",
            "Date-Time": "2015-02-12T10:00:00-05:00",
            "Type": "Trade",
        },
        {
            "#RIC": "ACHC.OQ",
            "Date-Time": "2015-02-12T11:00:00-05:00",
            "Type": "Quote",
        },
    ]
    out = validator.validate_rows(rows, plan=_plan(), trade_date="2015-02-12")
    achc = next(x for x in out["results"] if x["historical_symbol"] == "ACHC")

    assert achc["validation_status"] == "ambiguous_multiple_candidates_observed"
    assert achc["selected_ric"] == ""
    assert achc["observed_candidate_rics"] == ["ACHC.O", "ACHC.OQ"]


def test_wrong_date_and_unknown_ric_are_not_used_for_validation():
    rows = [
        {
            "#RIC": "ALSN.N",
            "Date-Time": "2015-02-11T10:00:00-05:00",
            "Type": "Trade",
        },
        {
            "#RIC": "OTHER.N",
            "Date-Time": "2015-02-12T10:00:00-05:00",
            "Type": "Trade",
        },
    ]
    out = validator.validate_rows(rows, plan=_plan(), trade_date="2015-02-12")
    alsn = next(x for x in out["results"] if x["historical_symbol"] == "ALSN")

    assert alsn["validation_status"] == "no_candidate_observed"
    assert out["summary"]["ignored_wrong_date_rows"] == 1
    assert out["summary"]["ignored_unknown_ric_rows"] == 1


def test_utc_timestamp_is_classified_by_new_york_trade_date():
    rows = [
        {
            "#RIC": "ALSN.N",
            "Date-Time": "2015-02-13T01:00:00+00:00",
            "Type": "Trade",
        }
    ]
    out = validator.validate_rows(rows, plan=_plan(), trade_date="2015-02-12")
    alsn = next(x for x in out["results"] if x["historical_symbol"] == "ALSN")

    assert alsn["validation_status"] == "validated_single_candidate"
    assert alsn["selected_ric"] == "ALSN.N"


def test_row_kind_falls_back_to_field_presence():
    assert validator.row_kind({"Price": "10", "Volume": "100"}) == "trade"
    assert validator.row_kind({"Bid Price": "9.9", "Ask Price": "10.1"}) == "quote"
    assert validator.row_kind({}) == "other"


def test_requested_date_must_exist_in_frozen_plan():
    try:
        validator.validate_rows([], plan=_plan(), trade_date="2015-02-13")
    except ValueError as exc:
        assert "not in frozen G2 equity scope" in str(exc)
    else:
        raise AssertionError("expected fail-closed date validation")
