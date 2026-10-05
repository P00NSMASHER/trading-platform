import urllib.parse

import g2_cboe_2011_option_diagnostic as diag


def test_dry_run_is_diagnostic_only_and_never_changes_coverage():
    manifest = diag.dry_run_manifest()
    assert manifest["sample_date"] == "2011-03-21"
    assert manifest["sample_underlying"] == "JNPR"
    assert manifest["diagnostic_only"] is True
    assert manifest["changes_vendor_confirmed_floor"] is False
    assert manifest["coverage_claimed"] is False
    assert manifest["g2_coverage_change"] == 0
    assert "--ack-trial-active" in manifest["execute_requires"]

    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(manifest["option_trade_request"]).query,
        keep_blank_values=True,
    )
    assert query["date"] == ["2011-03-21"]
    assert query["symbol"] == ["JNPR"]
    assert query["limit"] == ["100"]


def test_quote_url_uses_returned_osi_security():
    url = diag.option_quote_url("JNPR110416C00020000")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["date"] == ["2011-03-21"]
    assert query["symbol"] == ["JNPR110416C00020000"]
    assert query["limit"] == ["100"]


def test_execute_passes_only_when_trade_and_quote_fields_exist(monkeypatch):
    monkeypatch.setattr(diag.base, "_token", lambda *_: "token")
    calls = []

    def fake_get(url, token):
        assert token == "token"
        calls.append(url)
        if "/option-trades?" in url:
            return [{
                "timestamp": "10:00:00.001",
                "security": "JNPR110416C00020000",
                "root": "JNPR",
                "expiry": "2011-04-16",
                "strike": 20.0,
                "option_type": "C",
                "option_trade_price": 1.2,
                "option_trade_size": 2,
            }]
        return [{
            "timestamp": "10:00:00.002",
            "nbbo_bid": 1.1,
            "nbbo_ask": 1.3,
            "nbbo_bid_size": 4,
            "nbbo_ask_size": 5,
        }]

    monkeypatch.setattr(diag.base, "_get_json", fake_get)
    result = diag.execute_diagnostic("id", "secret")
    assert result["diagnostic_passed"] is True
    assert result["requests_executed"] == 2
    assert result["coverage_claimed"] is False
    assert result["g2_coverage_change"] == 0
    assert len(calls) == 2


def test_execute_fails_closed_when_2011_trade_rows_absent(monkeypatch):
    monkeypatch.setattr(diag.base, "_token", lambda *_: "token")
    monkeypatch.setattr(diag.base, "_get_json", lambda *_: [])
    result = diag.execute_diagnostic("id", "secret")
    assert result["diagnostic_passed"] is False
    assert result["requests_executed"] == 1
    assert result["quote_assessment"]["accepted"] is False
    assert result["g2_coverage_change"] == 0
