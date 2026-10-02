import json
import urllib.parse

import g2_cboe_acceptance_probe as probe


def test_dry_run_is_two_requests_and_thirty_points():
    manifest = probe.dry_run_manifest()

    assert manifest["sample_date"] == "2012-01-03"
    assert manifest["sample_symbol"] == "AF"
    assert manifest["historical_points_per_request"] == 15
    assert manifest["total_probe_points"] == 30
    assert manifest["execute_requires"] == ["CBOE_CLIENT_ID", "CBOE_CLIENT_SECRET"]
    assert [r["name"] for r in manifest["requests"]] == [
        "equity_trades_and_quotes",
        "option_trades",
    ]

    equity_url = manifest["requests"][0]["url"]
    option_url = manifest["requests"][1]["url"]
    assert "/time-and-sales/trades-and-quotes?" in equity_url
    assert "/time-and-sales/option-trades?" in option_url

    equity_qs = urllib.parse.parse_qs(urllib.parse.urlparse(equity_url).query, keep_blank_values=True)
    option_qs = urllib.parse.parse_qs(urllib.parse.urlparse(option_url).query, keep_blank_values=True)
    assert equity_qs["date"] == ["2012-01-03"]
    assert equity_qs["symbol"] == ["AF"]
    assert equity_qs["mode"] == ["ALL_QUOTES"]
    assert equity_qs["limit"] == ["100"]
    assert option_qs["date"] == ["2012-01-03"]
    assert option_qs["symbol"] == ["AF"]
    assert option_qs["seq_no"] == ["0"]
    assert option_qs["limit"] == ["100"]


def test_assessment_requires_every_field_to_be_present_and_populated():
    good = {
        "timestamp": "09:30:00.001",
        "security": "AF120121C00010000",
        "root": "AF",
        "expiry": "2012-01-21",
        "strike": 30.0,
        "option_type": "C",
        "option_trade_price": 1.25,
        "option_trade_size": 3,
    }
    result = probe.assess_probe_response("option_trades", [good], probe.OPTION_REQUIRED_FIELDS)
    assert result["accepted"] is True
    assert result["missing_required_fields"] == []
    assert result["unpopulated_required_fields"] == []

    null_price = dict(good)
    null_price["option_trade_price"] = None
    failed = probe.assess_probe_response(
        "option_trades", [null_price], probe.OPTION_REQUIRED_FIELDS
    )
    assert failed["accepted"] is False
    assert failed["missing_required_fields"] == []
    assert failed["unpopulated_required_fields"] == ["option_trade_price"]


def test_execute_probe_uses_only_two_historical_requests(monkeypatch):
    calls = []

    def fake_token(client_id, client_secret):
        assert client_id == "client"
        assert client_secret == "secret"
        return "token"

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
    option_payload = [
        {
            "timestamp": "09:30:00.002",
            "security": "AF120121C00010000",
            "root": "AF",
            "expiry": "2012-01-21",
            "strike": 30.0,
            "option_type": "C",
            "option_trade_price": 1.25,
            "option_trade_size": 3,
        }
    ]

    def fake_get(url, token):
        assert token == "token"
        calls.append(url)
        if "trades-and-quotes" in url:
            return equity_payload
        if "option-trades" in url:
            return option_payload
        raise AssertionError(url)

    monkeypatch.setattr(probe, "_token", fake_token)
    monkeypatch.setattr(probe, "_get_json", fake_get)

    result = probe.execute_probe("client", "secret")
    assert result["accepted"] is True
    assert result["total_probe_points"] == 30
    assert len(calls) == 2
    assert all("2012-01-03" in url and "AF" in url for url in calls)


def test_token_and_secret_never_appear_in_outputs(monkeypatch):
    monkeypatch.setattr(probe, "_token", lambda *_: "very-secret-access-token")
    monkeypatch.setattr(
        probe,
        "_get_json",
        lambda url, token: [
            {
                "timestamp": "09:30:00.001",
                **(
                    {
                        "underlying_trade_price": 45.10,
                        "underlying_trade_size": 100,
                        "bid": 45.09,
                        "ask": 45.11,
                        "bid_size": 500,
                        "ask_size": 600,
                    }
                    if "trades-and-quotes" in url
                    else {
                        "security": "AF120121C00010000",
                        "root": "AF",
                        "expiry": "2012-01-21",
                        "strike": 30.0,
                        "option_type": "C",
                        "option_trade_price": 1.25,
                        "option_trade_size": 3,
                    }
                ),
            }
        ],
    )
    output = json.dumps(probe.execute_probe("client-id", "client-secret"))
    assert "very-secret-access-token" not in output
    assert "client-secret" not in output
    assert "client-id" not in output
