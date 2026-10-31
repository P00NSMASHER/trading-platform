"""Adversarial paper-only previous-session SPY intraday signal tests."""
from dataclasses import replace
from datetime import date, timedelta

import pytest

from equity_reversal_audit import Bar, InvalidPriceEvidence, git_blob_sha, read_bars, summary
from equity_intraday_lag_audit import compute_trials, select, evaluate


def fixture_bars():
    first = date(2020, 1, 1)
    return [
        Bar(first, 100, 98, 98),
        Bar(first + timedelta(days=1), 100, 101, 101),
        Bar(first + timedelta(days=2), 100, 99.5, 99.5),
        Bar(first + timedelta(days=3), 100, 100, 100),
    ]


def test_prior_close_known_before_entry_and_cost_on_gross_notional():
    paper = select(compute_trials(fixture_bars()), "prior_intraday_down_1pct")
    assert len(paper) == 1
    assert paper[0].day == date(2020, 1, 2)
    assert paper[0].intraday_return == pytest.approx(0.01)
    assert summary(paper, 20)["mean_net_bps"] == pytest.approx(80)


def test_target_close_changes_return_not_its_own_predeclared_signal():
    bars = fixture_bars()
    first = select(compute_trials(bars), "prior_intraday_down_1pct")
    bars[1] = replace(bars[1], close=95, adjusted_close=95)
    later = select(compute_trials(bars), "prior_intraday_down_1pct")
    assert first[0].day == later[0].day == date(2020, 1, 2)
    assert first[0].intraday_return > 0 > later[0].intraday_return


def test_reverse_sign_short_is_negative_control_not_alpha():
    paper = select(compute_trials(fixture_bars()),
                   "prior_intraday_up_1pct_short_control")
    assert len(paper) == 1
    assert paper[0].day == date(2020, 1, 3)
    assert paper[0].intraday_return == pytest.approx(0.005)


def test_unknown_signal_or_tuned_condition_is_rejected():
    with pytest.raises(ValueError, match="Unregistered"):
        select([], "best_after_backtest")


def test_mirrored_duplicate_session_fails_closed():
    bars = fixture_bars()
    bars.insert(1, bars[0])
    with pytest.raises(InvalidPriceEvidence, match="unordered"):
        compute_trials(bars)


def test_unsorted_session_fails_closed():
    bars = fixture_bars()
    bars[1], bars[2] = bars[2], bars[1]
    with pytest.raises(InvalidPriceEvidence, match="unordered"):
        compute_trials(bars)


def test_stale_previous_session_is_not_actionable():
    start = date(2020, 1, 1)
    bars = [Bar(start, 100, 98, 98),
            Bar(date(2020, 2, 1), 100, 101, 101)]
    assert compute_trials(bars) == []


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_nonpositive_or_nonfinite_prices_rejected(value):
    bars = fixture_bars()
    bars[1] = replace(bars[1], open=value)
    with pytest.raises(InvalidPriceEvidence):
        compute_trials(bars)


def test_unusual_unadjusted_intraday_price_rejected():
    bars = fixture_bars()
    bars[1] = replace(bars[1], close=150, adjusted_close=150)
    with pytest.raises(InvalidPriceEvidence, match="Unusually large"):
        compute_trials(bars)


def test_empty_source_cannot_produce_fabricated_return():
    with pytest.raises(InvalidPriceEvidence, match="two ordered"):
        compute_trials([])


def test_fixed_phase_and_missing_cohort_reports_no_wins():
    out = evaluate(fixture_bars())
    assert out["phases"]["train"]["eligible_sessions"] == 0
    assert out["phases"]["validation"]["prior_intraday_down_1pct"]["cost_20bps"]["mean_net_bps"] is None
    assert out["phases"]["holdout"]["prior_intraday_down_1pct"]["cost_20bps"]["trades"] == 1


def test_source_bytes_tamper_refused_before_any_research(tmp_path):
    raw = (b"Date,Open,High,Low,Close,Adj Close\n"
           b"2020-01-01,100,100,98,98,98\n"
           b"2020-01-02,100,101,99,101,101\n"
           b"2020-01-03,100,101,99,99.5,99.5\n")
    p = tmp_path / "SPY.csv"
    p.write_bytes(raw)
    assert len(read_bars(p, git_blob_sha(raw))) == 3
    p.write_bytes(raw + b"2020-01-04,100,100,99,100,100\n")
    with pytest.raises(InvalidPriceEvidence, match="hash mismatch"):
        read_bars(p, git_blob_sha(raw))
