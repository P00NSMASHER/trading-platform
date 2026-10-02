import json
import urllib.parse

import g2_cboe_acceptance_probe as probe


def test_dry_run_is_three_request_maximum_and_fail_closed():
    manifest = probe.dry_run_manifest()

    assert manifest["equity_sample"] == {
        "date": "2011-03-21",
        "symbol": "JNPR",
    }
    assert manifest["option_sample"] == {
        "date": "2012-01-03",
        "underlying_symbol": "AF",
    }
    assert manifest["historical_points_per_request"] == 15
    assert manifest["max_probe_requests"] == 3
    assert manifest["max_probe_points"] == 45
    assert manifest["execute_requires"] == ["CBOE_CLIENT_ID", "CBOE_CLIENT_SECRET"]
    assert [r["name"] for r in manifest["requests"]] == [
        "equity_trades_and_quotes",
        "option_trades",
    ]
    assert manifest["derived_quote_request"]["name"] == "option_quotes"
    assert manifest["derived_quote_request"]["symbol_source"].startswith(
        "first nonblank security"
    )

    equity_url = manifest["requests"][0]["url"]
    option_url = manifest["requests"][1]["url"]

    equity_qs = urllib.parse.parse_qs(
        urllib.parse.urlparse(equity_url).query,
        keep_blank_values=True,
    )
    option_qs = urllib.parse.parse_qs(
        urllib.parse.urlparse(option_url).query,
        keep_blank_values=True,
    )
    assert equity_qs["date"] == ["2011-03-21"]
    assert equity_qs["symbol"] == ["JNPR"]
    assert equity_qs["mode"] == ["ALL_QUOTES"]
    assert equity_qs["limit"] == ["100"]

    assert option_qs["date"] == ["2012-01-03"]
    assert option_qs["symbol"] == ["AF"]
    assert option_qs["seq_no"] == ["0"]
    assert option_qs["limit"] == ["100"]


def test_derived_option_quote_request_uses_returned_osi_security():
    request = probe.build_option_quote_request("AF120121C00010000")
    assert request.name == "option_quotes"
    assert "/time-and-sales/quotes?" in request.url

    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(request.url).query,
        keep_blank_values=True,
    )
    assert query["date"] == ["2012-01-03"]
    assert query["symbol"] == ["AF120121C00010000"]
    assert query["start_sequence_number"] == ["0"]
    assert query["limit"] == ["100"]
    assert request.required_fields == frozenset(
        {"timestamp", "bid", "ask", "bid_size", "ask_size"}
    )


def test_assessment_requires_every_field_to_be_present_and_populated():
    good = {
        "timestamp": "09:30:00.001",
        "security": "AF120121C00010000",
        "root": "AF",
        "expiry": "2012-01-21",
        "strike": 10.0,
        "option_type": "C",
        "option_trade_price": 1.25,
        "option_trade_size": 3,
    }
    result = probe.assess_probe_response(
        "option_trades",
        [good],
        probe.OPTION_TRADE_REQUIRED_FIELDS,
    )
    assert result["accepted"] is True
    assert result["missing_required_fields"] == []
    assert result["unpopulated_required_fields"] == []

    null_price = dict(good)
    null_price["option_trade_price"] = None
    failed = probe.assess_probe_response(
        "option_trades",
        [null_price],
        probe.OPTION_TRADE_REQUIRED_FIELDS,
    )
    assert failed["accepted"] is False
    assert failed["missing_required_fields"] == []
    assert failed["unpopulated_required_fields"] == ["option_trade_price"]


def test_execute_probe_uses_only_three_historical_requests(monkeypatch):
    calls = []

    monkeypatch.setattr(probe, "_token", lambda client_id, client_secret: "token")

    equity_payload = [
        {
            "timestamp": "09:30:00.001",
            "underlying_trade_price": 45.10,
            "underlying_trade_size": 100,
            "bid": 45.09,
            "ask": 45.11,
            "bid_size": 500,
            "ask_size": 600,
        }
    ]
    option_trade_payload = [
        {
            "timestamp": "09:30:00.002",
            "security": "AF120121C00010000",
            "root": "AF",
            "expiry": "2012-01-21",
            "strike": 10.0,
            "option_type": "C",
            "option_trade_price": 1.25,
            "option_trade_size": 3,
        }
    ]
    option_quote_payload = [
        {
            "timestamp": "09:30:00.003",
            "bid": 1.20,
            "ask": 1.30,
            "bid_size": 12,
            "ask_size": 15,
            "nbbo_bid": 1.20,
            "nbbo_ask": 1.30,
        }
    ]

    def fake_get(url, token):
        assert token == "token"
        calls.append(url)
        if "/trades-and-quotes?" in url:
            return equity_payload
        if "/option-trades?" in url:
            return option_trade_payload
        if "/quotes?" in url:
            return option_quote_payload
        raise AssertionError(url)

    monkeypatch.setattr(probe, "_get_json", fake_get)

    result = probe.execute_probe("client", "secret")
    assert result["accepted"] is True
    assert result["requests_executed"] == 3
    assert result["points_consumed"] == 45
    assert result["max_probe_points"] == 45
    assert len(calls) == 3

    assert "date=2011-03-21" in calls[0]
    assert "symbol=JNPR" in calls[0]
    assert "date=2012-01-03" in calls[1]
    assert "symbol=AF" in calls[1]
    assert "date=2012-01-03" in calls[2]
    assert "symbol=AF120121C00010000" in calls[2]


def test_option_quote_request_stays_blocked_without_osi_security(monkeypatch):
    calls = []

    monkeypatch.setattr(probe, "_token", lambda *_: "token")

    def fake_get(url, token):
        calls.append(url)
        if "/trades-and-quotes?" in url:
            return [
                {
                    "timestamp": "09:30:00.001",
                    "underlying_trade_price": 45.10,
                    "underlying_trade_size": 100,
                    "bid": 45.09,
                    "ask": 45.11,
                    "bid_size": 500,
                    "ask_size": 600,
                }
            ]
        if "/option-trades?" in url:
            return [
                {
                    "timestamp": "09:30:00.002",
                    "security": "",
                    "root": "AF",
                    "expiry": "2012-01-21",
                    "strike": 10.0,
                    "option_type": "C",
                    "option_trade_price": 1.25,
                    "option_trade_size": 3,
                }
            ]
        raise AssertionError("quote request must not execute without an OSI security")

    monkeypatch.setattr(probe, "_get_json", fake_get)

    result = probe.execute_probe("client", "secret")
    assert result["accepted"] is False
    assert result["requests_executed"] == 2
    assert result["points_consumed"] == 30
    assert len(calls) == 2
    assert result["assessments"][-1]["name"] == "option_quotes"
    assert result["assessments"][-1]["accepted"] is False
    assert "not executed" in result["assessments"][-1]["reason"]


def test_token_and_secret_never_appear_in_outputs(monkeypatch):
    monkeypatch.setattr(probe, "_token", lambda *_: "very-secret-access-token")

    def fake_get(url, token):
        if "/trades-and-quotes?" in url:
            return [
                {
                    "timestamp": "09:30:00.001",
                    "underlying_trade_price": 45.10,
                    "underlying_trade_size": 100,
                    "bid": 45.09,
                    "ask": 45.11,
                    "bid_size": 500,
                    "ask_size": 600,
                }
            ]
        if "/option-trades?" in url:
            return [
                {
                    "timestamp": "09:30:00.002",
                    "security": "AF120121C00010000",
                    "root": "AF",
                    "expiry": "2012-01-21",
                    "strike": 10.0,
                    "option_type": "C",
                    "option_trade_price": 1.25,
                    "option_trade_size": 3,
                }
            ]
        if "/quotes?" in url:
            return [
                {
                    "timestamp": "09:30:00.003",
                    "bid": 1.20,
                    "ask": 1.30,
                    "bid_size": 12,
                    "ask_size": 15,
                }
            ]
        raise AssertionError(url)

    monkeypatch.setattr(probe, "_get_json", fake_get)

    output = json.dumps(probe.execute_probe("client-id", "client-secret"))
    assert "very-secret-access-token" not in output
    assert "client-secret" not in output
    assert "client-id" not in output
