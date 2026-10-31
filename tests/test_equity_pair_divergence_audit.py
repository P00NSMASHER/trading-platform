"""Source immutability, synchronization, cost and no-lookahead pair audit tests."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from equity_reversal_audit import Bar, InvalidPriceEvidence, git_blob_sha, read_bars, summary
from equity_pair_divergence_audit import (
    PairObservation, PaperReturn, compute_pairs, evaluate, select,
)


def _dates(n: int = 8):
    return [date(2020, 1, 1) + timedelta(days=i) for i in range(n)]


def _bars(n: int = 8):
    days = _dates(n)
    spy = [Bar(day, 100, 100, 100) for day in days]
    qqq = [Bar(day, 100, 100, 96 if i == 5 else 100) for i, day in enumerate(days)]
    qqq[6] = Bar(days[6], 100, 102, 102)
    return spy, qqq


def test_fixed_relative_lag_and_pair_gross_notional():
    spy, qqq = _bars()
    obs = compute_pairs(spy, qqq)
    assert len(obs) == 2
    assert obs[0].day == _dates()[6]
    assert obs[0].prior_5session_qqq_minus_spy == pytest.approx(-.04)
    selected = select(obs, "qqq_lag_2pct")
    assert len(selected) == 1
    assert selected[0].intraday_return == pytest.approx(.01)


def test_target_close_does_not_determine_own_signal():
    spy, qqq = _bars()
    baseline = select(compute_pairs(spy, qqq), "qqq_lag_2pct")
    qqq[6] = Bar(_dates()[6], 100, 90, 90)
    changed = select(compute_pairs(spy, qqq), "qqq_lag_2pct")
    assert [x.day for x in baseline] == [x.day for x in changed]
    assert baseline[0].intraday_return > 0
    assert changed[0].intraday_return < 0


def test_missing_calendar_date_never_mixes_legs():
    spy, qqq = _bars()
    missing = _dates()[6]
    qqq = [bar for bar in qqq if bar.day != missing]
    observations = compute_pairs(spy, qqq)
    assert all(t.day != missing for t in observations)
    assert len(observations) == 1


def test_short_side_control_reverses_direction():
    trials = [PairObservation(_dates()[6], .03, .02)]
    assert not select(trials, "qqq_lag_2pct")
    paper = select(trials, "qqq_lead_2pct_control")
    assert paper == [PaperReturn(_dates()[6], -.01)]


def test_roundtrip_costs_applied_once_per_gross_notional():
    trials = [PaperReturn(_dates()[6], .01)]
    assert summary(trials, 10)["mean_net_bps"] == pytest.approx(90)
    assert summary(trials, 20)["mean_net_bps"] == pytest.approx(80)
    assert summary(trials, 80)["mean_net_bps"] == pytest.approx(20)


def test_source_hash_rejects_in_place_mutation(tmp_path):
    payload = (
        b"Date,Open,High,Low,Close,Adj Close,Volume\n"
        b"2020-01-01,100,101,99,100,100,1\n"
        b"2020-01-02,100,101,99,100,100,1\n"
        b"2020-01-03,100,101,99,100,100,1\n"
    )
    p = tmp_path / "SPY.csv"
    p.write_bytes(payload)
    assert len(read_bars(p, git_blob_sha(payload))) == 3
    p.write_bytes(payload + b"2020-01-04,100,101,99,100,100,1\n")
    with pytest.raises(InvalidPriceEvidence, match="hash mismatch"):
        read_bars(p, git_blob_sha(payload))


def test_no_lookahead_phase_split_and_denominators():
    spy, qqq = _bars()
    result = evaluate(spy, qqq)
    assert result["aligned_sessions"] == 8
    assert result["eligible_days"] == 2
    assert result["phases"]["holdout"]["eligible_days"] == 2
    assert result["phases"]["holdout"]["qqq_lag_2pct"]["cost_20bps"]["trades"] == 1
    assert result["phases"]["validation"]["qqq_lag_2pct"]["cost_20bps"]["trades"] == 0


def test_sparse_pair_rejected():
    spy, qqq = _bars(6)
    with pytest.raises(InvalidPriceEvidence, match="at least 7"):
        compute_pairs(spy, qqq)


def test_unregistered_condition_refused():
    with pytest.raises(ValueError, match="Unknown"):
        select([], "tuned_to_best_result")


def test_stale_calendar_gap_skipped():
    spy, qqq = _bars()
    shifted = _dates()
    spy[-1] = Bar(date(2020, 2, 1), 100, 100, 100)
    qqq[-1] = Bar(date(2020, 2, 1), 100, 100, 100)
    assert len(compute_pairs(spy, qqq)) == 1


def test_extreme_inconsistent_intraday_value_rejected():
    spy, qqq = _bars()
    qqq[6] = Bar(_dates()[6], 100, 150, 150)
    with pytest.raises(InvalidPriceEvidence, match="Unusual intraday"):
        compute_pairs(spy, qqq)


def test_empty_cost_summary_not_profitable():
    assert summary(select([], "qqq_lag_2pct"), 20)["mean_net_bps"] is None
