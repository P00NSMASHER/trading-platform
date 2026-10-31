"""No-lookahead, immutable-source, cost, and resampling gates for ETF audit."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import pytest

from equity_reversal_audit import (
    Bar, InvalidPriceEvidence, Trial, block_confidence_interval,
    compute_trials, evaluate, git_blob_sha, phase, read_bars, select, summary,
)


def _csv(rows, header="Date,Open,High,Low,Close,Adj Close,Volume"):
    return (header + "\n" + "\n".join(rows) + "\n").encode()


def _read(tmp_path, payload):
    file = tmp_path / "bars.csv"
    file.write_bytes(payload)
    return read_bars(file, git_blob_sha(payload))


def test_git_blob_matches_git_sha1_convention():
    assert git_blob_sha(b"test\n") == "9daeafb9864cf43055ae93beb0afd6c7d144bfa4"


def test_valid_realistic_fixture_and_adjusted_close(tmp_path):
    data = _csv([
        "2020-01-02,100,105,95,100,100,1000",
        "2020-01-03,100,105,89,90,90,1000",
        "2020-01-06,90,100,88,99,99,1000",
    ])
    bars = _read(tmp_path, data)
    assert len(bars) == 3
    trials = compute_trials(bars)
    assert len(trials) == 1
    assert trials[0].previous_daily_return == pytest.approx(-0.1)
    assert trials[0].intraday_return == pytest.approx(0.1)
    assert len(select(trials, "prior_down_1pct")) == 1


def test_next_session_signal_not_based_on_own_close():
    bars = [
        Bar(date(2020, 1, 2), 100, 100, 100),
        Bar(date(2020, 1, 3), 100, 100, 100),
        Bar(date(2020, 1, 6), 100, 70, 70),  # crash occurs AFTER entry
        Bar(date(2020, 1, 7), 70, 77, 77),
    ]
    t = compute_trials(bars)
    assert len(select(t, "prior_down_1pct")) == 1
    assert select(t, "prior_down_1pct")[0].day == date(2020, 1, 7)


def test_adjusted_previous_close_used_for_signal():
    bars = [
        Bar(date(2020, 1, 2), 100, 100, 100),
        Bar(date(2020, 1, 3), 90, 90, 101),
        Bar(date(2020, 1, 6), 95, 96, 107),
    ]
    assert not select(compute_trials(bars), "prior_down_1pct")


def test_costs_are_charged_per_completed_round_trip():
    t = [Trial(date(2020, 1, 7), -0.02, 0.01)]
    assert summary(t, 10)["mean_net_bps"] == pytest.approx(90)
    assert summary(t, 30)["mean_net_bps"] == pytest.approx(70)
    assert summary(t, 50)["mean_net_bps"] == pytest.approx(50)


def test_phase_split_is_date_strict_and_never_optimizes_holdout():
    assert phase(date(2012, 12, 31)) == "train"
    assert phase(date(2013, 1, 1)) == "validation"
    assert phase(date(2018, 12, 31)) == "validation"
    assert phase(date(2019, 1, 1)) == "holdout"


def test_month_bootstrap_reproducible_and_clusters_retained():
    trials = [
        Trial(date(2020, month, min(day, 27)), -0.02, (month - 6) * 0.003)
        for month in range(1, 8) for day in range(1, 5)
    ]
    a = block_confidence_interval(trials, 10, seed=41, replicates=120)
    b = block_confidence_interval(trials, 10, seed=41, replicates=120)
    assert a == b
    assert a[0] <= a[1]


def test_small_month_count_ci_unknown():
    assert block_confidence_interval([Trial(date(2020, 1, 7), -0.02, 0.1)], 10) is None


def test_empty_cohort_refuses_imaginary_profit():
    assert summary([], 10) == {
        "trades": 0, "mean_net_bps": None, "ci95_month_cluster_bps": None
    }


def test_rejects_mutable_blob(tmp_path):
    payload = _csv([
        "2020-01-02,100,105,95,100,100,1000",
        "2020-01-03,100,105,89,90,90,1000",
        "2020-01-06,90,100,88,99,99,1000",
    ])
    file = tmp_path / "mutable.csv"
    file.write_bytes(payload)
    with pytest.raises(InvalidPriceEvidence, match="hash mismatch"):
        read_bars(file, "a" * 40)


@pytest.mark.parametrize("rows", [
    ["2020-01-02,100,105,95,100,100,1000",
     "2020-01-02,100,105,95,100,100,1000",
     "2020-01-06,90,100,88,99,99,1000"],
    ["2020-01-03,100,105,95,100,100,1000",
     "2020-01-02,100,105,95,100,100,1000",
     "2020-01-06,90,100,88,99,99,1000"],
    ["2020-01-02,100,105,95,100,100,1000",
     "2020-01-03,100,105,89,90,90,1000",
     "2020-01-06,90,92,91,99,99,1000"],
    ["2020-01-02,100,105,95,100,100,1000",
     "2020-01-03,100,105,89,90,90,1000",
     "2020-01-06,90,nan,88,99,99,1000"],
])
def test_rejects_duplicate_unsorted_impossible_and_nonfinite(tmp_path, rows):
    with pytest.raises(InvalidPriceEvidence):
        _read(tmp_path, _csv(rows))


def test_invalid_blob_sha_rejected_before_parse(tmp_path):
    p = tmp_path / "file.csv"
    p.write_text("private non-market data")
    with pytest.raises(InvalidPriceEvidence, match="40-character"):
        read_bars(p, "short")


def test_no_adjusted_close_csv_supported(tmp_path):
    payload = _csv([
        "2020-01-02,100,105,95,100,1000",
        "2020-01-03,100,105,89,90,1000",
        "2020-01-06,90,100,88,99,1000",
    ], header="Date,Open,High,Low,Close,Volume")
    assert len(compute_trials(_read(tmp_path, payload))) == 1


def test_rejects_extreme_unexplained_intraday_return():
    bars = [
        Bar(date(2020, 1, 2), 100, 100, 100),
        Bar(date(2020, 1, 3), 100, 90, 90),
        Bar(date(2020, 1, 6), 100, 150, 150),
    ]
    with pytest.raises(InvalidPriceEvidence, match="Unusually large"):
        compute_trials(bars)


def test_evaluate_disjoint_phase_counts():
    bars = [
        Bar(date(2012, 12, 27), 100, 100, 100),
        Bar(date(2012, 12, 28), 100, 98, 98),
        Bar(date(2012, 12, 31), 98, 99, 99),
        Bar(date(2013, 1, 2), 99, 98, 98),
        Bar(date(2019, 1, 2), 98, 99, 99),
    ]
    result = evaluate(bars)
    assert result["phases"]["train"]["prior_down_1pct"]["cost_10bps"]["trades"] == 1
    assert result["phases"]["validation"]["prior_down_1pct"]["cost_10bps"]["trades"] == 0
    assert result["phases"]["holdout"]["prior_down_1pct"]["cost_10bps"]["trades"] == 1
