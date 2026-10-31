"""Synthetic no-lookahead and adversarial gates for 20-session trend research."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from equity_reversal_audit import Bar, InvalidPriceEvidence, git_blob_sha, read_bars
from equity_trend_filter_audit import (
    LOOKBACK_SESSIONS, THRESHOLD, compute_trials, evaluate, select,
)


def _bars(old_adjusted=100.0, previous_adjusted=106.0, final_close=101.0):
    start = date(2020, 1, 2)
    days = [start + timedelta(days=i) for i in range(22)]
    bars = [Bar(d, 100.0, 100.0, 100.0) for d in days]
    bars[0] = replace(bars[0], adjusted_close=old_adjusted)
    bars[20] = replace(bars[20], adjusted_close=previous_adjusted)
    bars[21] = replace(bars[21], close=final_close)
    return bars


def test_fixed_protocol_parameters_are_not_optimized_on_holdout():
    assert LOOKBACK_SESSIONS == 20
    assert THRESHOLD == pytest.approx(0.05)


def test_exact_twenty_session_lag_and_no_entry_day_signal():
    trials = compute_trials(_bars())
    assert len(trials) == 1
    assert trials[0].trailing_20session_return == pytest.approx(0.06)
    assert trials[0].intraday_return == pytest.approx(0.01)
    assert len(select(trials, "prior_20session_up_5pct")) == 1


def test_today_close_can_change_outcome_but_not_prior_signal():
    initial = compute_trials(_bars(final_close=101))[0]
    changed = compute_trials(_bars(final_close=99))[0]
    assert changed.trailing_20session_return == initial.trailing_20session_return
    assert changed.intraday_return < initial.intraday_return


def test_today_adjusted_close_cannot_trigger_today_signal():
    a = _bars(previous_adjusted=100)
    b = [replace(x) for x in a]
    b[-1] = replace(b[-1], adjusted_close=999)
    assert compute_trials(a)[0].trailing_20session_return == pytest.approx(0)
    assert compute_trials(b)[0].trailing_20session_return == pytest.approx(0)
    assert not select(compute_trials(b), "prior_20session_up_5pct")


def test_fixed_negative_control_is_not_positive_trend_signal():
    trials = compute_trials(_bars(previous_adjusted=94))
    assert select(trials, "prior_20session_down_5pct_control") == trials
    assert select(trials, "prior_20session_up_5pct") == []
    assert select(trials, "every_session_control") == trials


def test_no_result_with_too_few_source_sessions():
    with pytest.raises(InvalidPriceEvidence, match="at least 22"):
        compute_trials(_bars()[:-1])


def test_invalid_current_session_price_rejected():
    with pytest.raises(InvalidPriceEvidence, match="Unusual"):
        compute_trials(_bars(final_close=150))
    with pytest.raises(InvalidPriceEvidence, match="Invalid price"):
        compute_trials(_bars(final_close=0))


def test_unregistered_strategy_refused():
    with pytest.raises(ValueError, match="Unregistered"):
        select(compute_trials(_bars()), "pick_most_profitable_after_testing")


def test_costs_charge_roundtrip_and_keep_controls_labeled():
    report = evaluate(_bars())
    assert report["research_status"] == "HYPOTHESIS_ONLY_NO_FILL_OR_TRADING_AUTHORIZATION"
    holdout = report["phases"]["holdout"]
    up = holdout["prior_20session_up_5pct"]
    assert up["cost_10bps"]["trades"] == 1
    assert up["cost_10bps"]["mean_net_bps"] == pytest.approx(90)
    assert up["cost_30bps"]["mean_net_bps"] == pytest.approx(70)
    assert up["cost_50bps"]["mean_net_bps"] == pytest.approx(50)
    assert holdout["prior_20session_down_5pct_control"]["cost_10bps"]["trades"] == 0
    assert up["cost_10bps"]["ci95_month_cluster_bps"] is None


def test_read_bars_source_blob_authenticity_is_reused(tmp_path):
    header = "Date,Open,High,Low,Close,Adj Close,Volume\n"
    lines = []
    for index, bar in enumerate(_bars()):
        lines.append(f"{bar.day},100,102,98,{bar.close},{bar.adjusted_close},1000")
    raw = (header + "\n".join(lines) + "\n").encode()
    path = tmp_path / "pinned.csv"
    path.write_bytes(raw)
    assert evaluate(read_bars(path, git_blob_sha(raw)))["bars"] == 22
    with pytest.raises(InvalidPriceEvidence, match="hash mismatch"):
        read_bars(path, "0" * 40)


def test_empty_holdout_does_not_invent_outcomes():
    old = _bars()
    old = [replace(x, day=x.day - timedelta(days=4000)) for x in old]
    report = evaluate(old)
    assert report["phases"]["holdout"]["prior_20session_up_5pct"]["cost_10bps"] == {
        "trades": 0, "mean_net_bps": None, "ci95_month_cluster_bps": None
    }
