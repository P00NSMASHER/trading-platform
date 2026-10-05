import urllib.parse

import g2_cboe_2011_option_diagnostic as diag


def test_dry_run_is_diagnostic_only_and_never_changes_coverage():
    manifest = diag.dry_run_manifest()
    assert manifest["sample_date"] == "2011-03-21"
    assert manifest["sample_underlying"] == "JNPR"
    assert manifest["max_requests"] == 3
    assert manifest["diagnostic_only"] is True
    assert manifest["changes_vendor_confirmed_floor"] is False
    assert manifest["coverage_claimed"] is False
    assert manifest["g2_coverage_change"] == 0
    assert "--ack-trial-active" in manifest["execute_requires"]

    reference_query = urllib.parse.parse_qs(
        urllib.parse.urlparse(manifest["reference_options_request"]).query
    )
    assert reference_query == {"date": ["2011-03-21"], "symbol": ["JNPR"]}

    trade_query = urllib.parse.parse_qs(
        urllib.parse.urlparse(manifest["option_trade_request"]).query,
        keep_blank_values=True,
    )
    assert trade_query["date"] == ["2011-03-21"]
    assert trade_query["symbol"] == ["JNPR"]
    assert trade_query["limit"] == ["100"]


def test_quote_url_uses_osi_security():
    url = diag.option_quote_url("JNPR110416C00020000")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["date"] == ["2011-03-21"]
    assert query["symbol"] == ["JNPR110416C00020000"]
    assert query["limit"] == ["100"]


def test_reference_row_builds_deterministic_osi_security():
    assert diag._osi_from_reference_row({
        "root": "jnpr",
        "expiry": "2011-04-16",
        "strike": "20",
        "type": "c",
    }) == "JNPR110416C00020000"
    assert diag._osi_from_reference_row({
        "root": "JNPR",
        "expiry": "bad-date",
        "strike": 20,
        "type": "C",
    }) is None


def test_execute_passes_only_when_reference_trade_and_quote_fields_exist(monkeypatch):
    monkeypatch.setattr(diag.base, "_token", lambda *_: "token")
    calls = []

    def fake_get(url, token):
        assert token == "token"
        calls.append(url)
        if "/reference/options?" in url:
            return [{
                "root": "JNPR",
                "expiry": "2011-04-16",
                "strike": 20.0,
                "type": "C",
            }]
        if "/option-trades?" in url:
            return [{
                "timestamp": "10:00:00.001",
                "security": "JNPR110416P00025000",
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
    assert result["requests_executed"] == 3
    assert result["derived_option_security"] == "JNPR110416C00020000"
    assert result["derived_option_security_source"] == "reference/options"
    assert result["coverage_claimed"] is False
    assert result["g2_coverage_change"] == 0
    assert len(calls) == 3
    assert "JNPR110416C00020000" in calls[-1]


def test_quote_is_still_probed_when_trade_rows_are_empty(monkeypatch):
    monkeypatch.setattr(diag.base, "_token", lambda *_: "token")

    def fake_get(url, _token):
        if "/reference/options?" in url:
            return [{
                "root": "JNPR",
                "expiry": "2011-04-16",
                "strike": 20.0,
                "type": "C",
            }]
        if "/option-trades?" in url:
            return []
        return [{
            "timestamp": "10:00:00.002",
            "nbbo_bid": 1.1,
            "nbbo_ask": 1.3,
            "nbbo_bid_size": 4,
            "nbbo_ask_size": 5,
        }]

    monkeypatch.setattr(diag.base, "_get_json", fake_get)
    result = diag.execute_diagnostic("id", "secret")
    assert result["diagnostic_passed"] is False
    assert result["requests_executed"] == 3
    assert result["reference_assessment"]["accepted"] is True
    assert result["trade_assessment"]["accepted"] is False
    assert result["quote_assessment"]["accepted"] is True
    assert result["g2_coverage_change"] == 0


def test_execute_fails_closed_when_no_2011_contract_or_trade_rows_exist(monkeypatch):
    monkeypatch.setattr(diag.base, "_token", lambda *_: "token")
    monkeypatch.setattr(diag.base, "_get_json", lambda *_: [])
    result = diag.execute_diagnostic("id", "secret")
    assert result["diagnostic_passed"] is False
    assert result["requests_executed"] == 2
    assert result["reference_assessment"]["accepted"] is False
    assert result["trade_assessment"]["accepted"] is False
    assert result["quote_assessment"]["accepted"] is False
    assert result["derived_option_security"] is None
    assert result["g2_coverage_change"] == 0
