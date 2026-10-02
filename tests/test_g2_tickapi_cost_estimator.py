from pathlib import Path

import g2_tickapi_cost_estimator as estimator


ROOT = Path(__file__).resolve().parents[1]
TRADES = ROOT / "data/processed/g2_vendor_requests/tickdata_equity_trades.csv"
QUOTES = ROOT / "data/processed/g2_vendor_requests/tickdata_equity_nbbo_quotes.csv"


def test_published_tickapi_progressive_example_matches_vendor_documentation():
    # Tick Data's published example: 720 symbol-months =
    # 600 * $2.33 + 120 * $2.00 = $1,638.
    assert estimator.progressive_data_cost(720) == 1638.00


def test_tickapi_cost_estimate_matches_frozen_equity_scope():
    result = estimator.estimate(
        estimator._read(TRADES),
        estimator._read(QUOTES),
    )

    assert result["unique_symbol_months"] == 352
    assert result["unique_calendar_months"] == 28
    assert result["published_data_usage_cost_usd"] == 820.16

    assert result["combined_request_count"] == 28
    assert result["combined_request_fees_usd"] == 0.84
    assert result["separate_trade_quote_request_count"] == 56
    assert result["separate_trade_quote_request_fees_usd"] == 1.68

    assert result["monthly_minimum_usd"] == 250.0
    assert result["minimum_term_months"] == 12
    assert result["annual_support_fee_usd"] == 250.0
    assert result["estimated_first_year_minimum_combined_requests_usd"] == 3821.00
    assert result["estimated_first_year_minimum_separate_requests_usd"] == 3821.84


def test_trade_and_quote_manifests_must_have_identical_coverage():
    trades = estimator._read(TRADES)
    quotes = estimator._read(QUOTES)
    quotes[0] = dict(quotes[0])
    quotes[0]["historical_symbols"] = "MISMATCH"

    try:
        estimator.estimate(trades, quotes)
    except ValueError as exc:
        assert "identical date/symbol coverage" in str(exc)
    else:
        raise AssertionError("expected mismatched trade/quote coverage to fail closed")
