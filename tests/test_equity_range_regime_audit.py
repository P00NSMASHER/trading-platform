"""Source-pinned, no-network adversarial tests of historical range selection."""
from dataclasses import replace
from datetime import date

import pytest

from equity_reversal_audit import InvalidPriceEvidence, git_blob_sha
from equity_range_regime_audit import (
    RangeBar, compute_trials, evaluate, read_range_bars, select,
)


def bars():
    dates = [date(2020, 1, d) for d in (2, 3, 6, 7, 8, 9, 10)]
    return [RangeBar(day, 100, 103, 99, 100) for day in dates]


def test_frozen_prior_five_ranges_selects_next_day_only():
    b = bars()
    b[5] = replace(b[5], close=102)
    t = select(compute_trials(b), "prior_high_range_long")
    assert [x.day for x in t] == [date(2020, 1, 9), date(2020, 1, 10)]
    assert t[0].intraday_return == pytest.approx(0.02)


def test_target_high_low_does_not_leak_into_its_own_signal():
    b = bars()
    before = compute_trials(b)
    b[5] = replace(b[5], high=125, low=80)
    after = compute_trials(b)
    assert before[0].prior_mean_range == after[0].prior_mean_range
    assert before[1].prior_mean_range != after[1].prior_mean_range


def test_quiet_control_kept_separate_and_unknown_arm_rejected():
    b = [replace(x, high=100.2, low=99.8) for x in bars()]
    assert select(compute_trials(b), "prior_high_range_long") == []
    assert len(select(compute_trials(b), "prior_quiet_range_long_control")) == 2
    with pytest.raises(ValueError, match="Unregistered"):
        select(compute_trials(b), "post_hoc_best_range_threshold")


def test_costs_and_phase_denominator_reproducible():
    b = bars()
    b[5] = replace(b[5], close=102)
    output = evaluate(b)
    assert output["phases"]["holdout"]["eligible_sessions"] == 2
    arm = output["phases"]["holdout"]["prior_high_range_long"]
    assert arm["cost_20bps"]["trades"] == 2
    assert arm["cost_20bps"]["mean_net_bps"] == pytest.approx(80)
    assert arm["cost_40bps"]["mean_net_bps"] == pytest.approx(60)
    assert arm["cost_20bps"]["ci95_month_cluster_bps"] is None


def test_complete_history_must_precede_target():
    with pytest.raises(InvalidPriceEvidence, match="six"):
        compute_trials(bars()[:5])


def test_stale_middle_window_excluded_without_peeking():
    b = bars()
    b[2] = replace(b[2], day=date(2020, 2, 3))
    b[3] = replace(b[3], day=date(2020, 2, 4))
    b[4] = replace(b[4], day=date(2020, 2, 5))
    b[5] = replace(b[5], day=date(2020, 2, 6))
    b[6] = replace(b[6], day=date(2020, 2, 7))
    assert compute_trials(b) == []


def test_seven_day_calendar_gap_allowed():
    days = [date(2020, 1, 2), date(2020, 1, 9), date(2020, 1, 16),
            date(2020, 1, 23), date(2020, 1, 30), date(2020, 2, 6)]
    assert len(compute_trials([RangeBar(d, 100, 102, 99, 100) for d in days])) == 1


@pytest.mark.parametrize("case", ["duplicate", "reverse", "weekend"])
def test_bad_calendar_rejected(case):
    b = bars()
    b[1] = replace(b[1], day={"duplicate": b[0].day,
                              "reverse": date(2019, 12, 31),
                              "weekend": date(2020, 1, 4)}[case])
    with pytest.raises(InvalidPriceEvidence):
        compute_trials(b)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_ohlc_rejected(value):
    b = bars()
    b[1] = replace(b[1], high=value)
    with pytest.raises(InvalidPriceEvidence):
        compute_trials(b)


def test_impossible_bounds_rejected():
    b = bars()
    b[1] = replace(b[1], low=101)
    with pytest.raises(InvalidPriceEvidence, match="OHLC"):
        compute_trials(b)


def test_extreme_range_rejected():
    b = bars()
    b[1] = replace(b[1], high=180)
    with pytest.raises(InvalidPriceEvidence, match="Extreme"):
        compute_trials(b)


def test_exact_source_blob_and_tamper_rejection(tmp_path):
    payload = (b"Date,Open,High,Low,Close,Volume\n"
               b"2020-01-02,100,103,99,100,1000\n"
               b"2020-01-03,100,103,99,100,1000\n"
               b"2020-01-06,100,103,99,100,1000\n"
               b"2020-01-07,100,103,99,100,1000\n"
               b"2020-01-08,100,103,99,100,1000\n"
               b"2020-01-09,100,103,99,102,1000\n")
    path = tmp_path / "spy.csv"
    path.write_bytes(payload)
    assert len(compute_trials(read_range_bars(path, git_blob_sha(payload)))) == 1
    path.write_bytes(payload + b"2020-01-10,100,103,99,100,1000\n")
    with pytest.raises(InvalidPriceEvidence, match="hash mismatch"):
        read_range_bars(path, git_blob_sha(payload))


def test_duplicate_headers_rejected_under_valid_blob(tmp_path):
    payload = b"Date,Open,High,High,Low,Close\n2020-01-02,100,101,101,99,100\n"
    path = tmp_path / "bad.csv"
    path.write_bytes(payload)
    with pytest.raises(InvalidPriceEvidence, match="Duplicate source column"):
        read_range_bars(path, git_blob_sha(payload))


def test_oversized_file_rejected_before_reading(tmp_path):
    from equity_range_regime_audit import MAX_CSV_BYTES
    path = tmp_path / "huge.csv"
    with path.open("wb") as f:
        f.truncate(MAX_CSV_BYTES + 1)
    with pytest.raises(InvalidPriceEvidence, match="bounded"):
        read_range_bars(path, "a" * 40)
