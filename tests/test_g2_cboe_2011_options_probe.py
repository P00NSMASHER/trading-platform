import json
import urllib.parse

import g2_cboe_2011_options_probe as probe


def test_dry_run_targets_exact_frozen_2011_sample_and_never_promotes_coverage():
    manifest = probe.dry_run_manifest()

    assert manifest["probe"] == {
        "date": "2011-03-21",
        "underlying_symbol": "JNPR",
    }
    assert manifest["max_probe_requests"] == 3
    assert manifest["max_probe_points"] == 31
    assert manifest["execute_requires"] == [
        "CBOE_CLIENT_ID",
        "CBOE_CLIENT_SECRET",
        "--ack-trial-active",
    ]
    assert manifest["g2_coverage_change"] == 0
    assert manifest["fail_closed"]["does_not_change_vendor_confirmed_2012_floor"] is True
    assert manifest["fail_closed"]["does_not_promote_g2_coverage"] is True

    reference_qs = urllib.parse.parse_qs(
        urllib.parse.urlparse(manifest["requests"][0]["url"]).query
    )
    trade_qs = urllib.parse.parse_qs(
        urllib.parse.urlparse(manifest["requests"][1]["url"]).query,
        keep_blank_values=True,
    )
    assert reference_qs == {"date": ["2011-03-21"], "symbol": ["JNPR"]}
    assert trade_qs["date"] == ["2011-03-21"]
    assert trade_qs["symbol"] == ["JNPR"]
    assert trade_qs["min_time"] == ["00:00:00.000"]
    assert trade_qs["max_time"] == ["23:59:59.999"]


def test_osi_symbol_is_derived_from_historical_reference_row():
    security = probe._osi_symbol(
        {
            "root": "JNPR",
            "expiry": "2011-04-16",
            "strike": 40.0,
            "type": "C",
        }
    )
    assert security == "JNPR110416C00040000"


def test_execute_probe_uses_three_bounded_requests_and_validates_2011_fields(monkeypatch):
    calls = []
    monkeypatch.setattr(probe, "_token", lambda *_: "token")

    reference_payload = [
        {
            "root": "JNPR",
            "expiry": "2011-04-16",
            "strike": 40.0,
            "type": "C",
        }
    ]
    trade_payload = [
        {
            "timestamp": "09:30:00.001",
            "security": "JNPR110416C00040000",
            "root": "JNPR",
            "expiry": "2011-04-16",
            "strike": 40.0,
            "option_type": "C",
            "option_trade_price": 1.25,
            "option_trade_size": 3,
            "exchange_id": 3,
            "condition_id": 0,
            "seq_no": 101,
        }
    ]
    quote_payload = [
        {
            "timestamp": "09:30:00.002",
            "exchange_id": 3,
            "condition_id": 0,
            "seq_no": 102,
            "nbbo_bid": 1.20,
            "nbbo_ask": 1.30,
            "nbbo_bid_size": 12,
            "nbbo_ask_size": 15,
        }
    ]

    def fake_get(url, token):
        assert token == "token"
        calls.append(url)
        if "/reference/options?" in url:
            return reference_payload
        if "/option-trades?" in url:
            return trade_payload
        if "/quotes?" in url:
            return quote_payload
        raise AssertionError(url)

    monkeypatch.setattr(probe, "_get_json", fake_get)

    result = probe.execute_probe("client", "secret")
    assert result["accepted"] is True
    assert result["requests_executed"] == 3
    assert result["points_consumed"] == 31
    assert result["g2_coverage_change"] == 0
    assert result["probe"]["derived_option_security_present"] is True
    assert "derived_option_security" not in result["probe"]
    assert result["raw_market_rows_persisted"] is False
    assert result["market_values_persisted_in_receipt"] is False
    assert all("date=2011-03-21" in url for url in calls)
    assert "symbol=JNPR110416C00040000" in calls[-1]


def test_quote_probe_fails_closed_when_historical_reference_is_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(probe, "_token", lambda *_: "token")

    trade_payload = [
        {
            "timestamp": "09:30:00.001",
            "security": "JNPR110416C00040000",
            "root": "JNPR",
            "expiry": "2011-04-16",
            "strike": 40.0,
            "option_type": "C",
            "option_trade_price": 1.25,
            "option_trade_size": 3,
            "exchange_id": 3,
            "condition_id": 0,
            "seq_no": 101,
        }
    ]

    def fake_get(url, token):
        calls.append(url)
        if "/reference/options?" in url:
            return []
        if "/option-trades?" in url:
            return trade_payload
        raise AssertionError("quote request must not run without reference contract")

    monkeypatch.setattr(probe, "_get_json", fake_get)

    result = probe.execute_probe("client", "secret")
    assert result["accepted"] is False
    assert result["requests_executed"] == 2
    assert result["points_consumed"] == 16
    assert len(calls) == 2
    assert result["assessments"][-1]["name"] == "historical_option_quotes"
    assert result["assessments"][-1]["accepted"] is False
    assert "not executed" in result["assessments"][-1]["reason"]


def test_secret_material_never_appears_in_probe_output(monkeypatch):
    monkeypatch.setattr(probe, "_token", lambda *_: "super-secret-token")

    def fake_get(url, token):
        if "/reference/options?" in url:
            return [
                {
                    "root": "JNPR",
                    "expiry": "2011-04-16",
                    "strike": 40.0,
                    "type": "C",
                }
            ]
        if "/option-trades?" in url:
            return [
                {
                    "timestamp": "09:30:00.001",
                    "security": "JNPR110416C00040000",
                    "root": "JNPR",
                    "expiry": "2011-04-16",
                    "strike": 40.0,
                    "option_type": "C",
                    "option_trade_price": 1.25,
                    "option_trade_size": 3,
                    "exchange_id": 3,
                    "condition_id": 0,
                    "seq_no": 101,
                }
            ]
        if "/quotes?" in url:
            return [
                {
                    "timestamp": "09:30:00.002",
                    "exchange_id": 3,
                    "condition_id": 0,
                    "seq_no": 102,
                    "nbbo_bid": 1.20,
                    "nbbo_ask": 1.30,
                    "nbbo_bid_size": 12,
                    "nbbo_ask_size": 15,
                }
            ]
        raise AssertionError(url)

    monkeypatch.setattr(probe, "_get_json", fake_get)

    rendered = json.dumps(probe.execute_probe("client-id", "client-secret"))
    assert "super-secret-token" not in rendered
    assert "client-secret" not in rendered
    assert "client-id" not in rendered


def test_single_object_quote_response_is_treated_as_one_row():
    payload = {
        "timestamp": "09:30:00.002",
        "exchange_id": 3,
        "condition_id": 0,
        "seq_no": 102,
        "nbbo_bid": 1.20,
        "nbbo_ask": 1.30,
        "nbbo_bid_size": 12,
        "nbbo_ask_size": 15,
    }
    result = probe._assess_rows(
        "historical_option_quotes",
        payload,
        probe.QUOTE_REQUIRED_FIELDS,
    )
    assert result["row_count"] == 1
    assert result["accepted"] is True


def test_wrapped_single_object_response_is_treated_as_one_row():
    payload = {
        "data": {
            "timestamp": "09:30:00.002",
            "exchange_id": 3,
            "condition_id": 0,
            "seq_no": 102,
            "nbbo_bid": 1.20,
            "nbbo_ask": 1.30,
            "nbbo_bid_size": 12,
            "nbbo_ask_size": 15,
        }
    }
    result = probe._assess_rows(
        "historical_option_quotes",
        payload,
        probe.QUOTE_REQUIRED_FIELDS,
    )
    assert result["row_count"] == 1
    assert result["accepted"] is True
