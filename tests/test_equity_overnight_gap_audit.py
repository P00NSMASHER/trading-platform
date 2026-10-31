"""Adversarial synthetic-only tests of previous-session overnight-gap signal."""
from dataclasses import replace
from datetime import date
import pytest

from equity_reversal_audit import Bar, InvalidPriceEvidence, git_blob_sha, read_bars
from equity_overnight_gap_audit import compute_trials, select, evaluate


def bars():
    return [
        Bar(date(2020, 1, 2), 100, 100, 100),
        Bar(date(2020, 1, 3), 102, 101, 101),
        Bar(date(2020, 1, 6), 100, 101, 101),
        Bar(date(2020, 1, 7), 98, 99, 99),
        Bar(date(2020, 1, 8), 100, 101, 101),
    ]


def test_prior_session_overnight_signal_has_next_day_long_payoff():
    trial = select(compute_trials(bars()), "prior_overnight_up_1pct_long")
    assert [x.day for x in trial] == [date(2020, 1, 6)]
    assert trial[0].intraday_return == pytest.approx(0.01)


def test_down_gap_short_arm_is_negative_control_not_promoted():
    trial = select(compute_trials(bars()),
                   "prior_overnight_down_1pct_short_control")
    assert [x.day for x in trial] == [date(2020, 1, 8)]
    assert trial[0].intraday_return == pytest.approx(-0.01)


def test_t_close_is_outcome_not_its_own_signal():
    before = select(compute_trials(bars()), "prior_overnight_up_1pct_long")
    modified = bars()
    modified[2] = replace(modified[2], close=95, adjusted_close=95)
    after = select(compute_trials(modified), "prior_overnight_up_1pct_long")
    assert before[0].day == after[0].day == date(2020, 1, 6)
    assert before[0].intraday_return > 0 > after[0].intraday_return


def test_adjusted_close_backfill_does_not_leak_into_raw_gap():
    changed = bars()
    changed[0] = replace(changed[0], adjusted_close=1)
    changed[1] = replace(changed[1], adjusted_close=10000)
    assert select(compute_trials(changed), "prior_overnight_up_1pct_long") == (
        select(compute_trials(bars()), "prior_overnight_up_1pct_long")
    )


def test_costs_and_frozen_phase_disclosure():
    result = evaluate(bars())
    assert result["phases"]["train"]["eligible_sessions"] == 0
    assert result["phases"]["validation"]["eligible_sessions"] == 0
    arm = result["phases"]["holdout"]["prior_overnight_up_1pct_long"]
    assert arm["cost_10bps"]["mean_net_bps"] == pytest.approx(90)
    assert arm["cost_20bps"]["mean_net_bps"] == pytest.approx(80)
    assert arm["cost_40bps"]["mean_net_bps"] == pytest.approx(60)
    assert arm["cost_20bps"]["ci95_month_cluster_bps"] is None


def test_unknown_or_tuned_arm_disallowed():
    with pytest.raises(ValueError, match="unregistered"):
        select([], "choose_best_hindsight")


def test_empty_and_short_history_fail_closed():
    for case in ([], bars()[:1], bars()[:2]):
        with pytest.raises(InvalidPriceEvidence, match="three"):
            compute_trials(case)


@pytest.mark.parametrize("order", ["duplicate", "reverse"])
def test_calendar_duplicate_or_unsorted_rejected(order):
    changed = bars()
    changed[1] = changed[0] if order == "duplicate" else replace(
        changed[1], day=date(2019, 12, 31))
    with pytest.raises(InvalidPriceEvidence, match="unordered"):
        compute_trials(changed)


def test_stale_middle_gap_skipped_then_resume_with_fresh_history():
    b = [
        Bar(date(2020, 1, 2), 100, 100, 100),
        Bar(date(2020, 1, 3), 100, 100, 100),
        Bar(date(2020, 2, 1), 100, 100, 100),
        Bar(date(2020, 2, 3), 102, 101, 101),
        Bar(date(2020, 2, 4), 100, 101, 101),
    ]
    assert [x.day for x in compute_trials(b)] == [date(2020, 2, 4)]


def test_exact_seven_day_calendar_spacing_is_eligible():
    b = [
        Bar(date(2020, 1, 2), 100, 100, 100),
        Bar(date(2020, 1, 9), 102, 101, 101),
        Bar(date(2020, 1, 16), 100, 101, 101),
    ]
    assert len(compute_trials(b)) == 1


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_bad_prices_cannot_create_paper_returns(value):
    b = bars()
    b[1] = replace(b[1], open=value)
    with pytest.raises(InvalidPriceEvidence):
        compute_trials(b)


def test_oversized_prior_gap_is_not_spurious_alpha():
    b = bars()
    b[1] = replace(b[1], open=190, close=190, adjusted_close=190)
    with pytest.raises(InvalidPriceEvidence, match="overnight gap"):
        compute_trials(b)


def test_oversized_target_intraday_move_rejected():
    b = bars()
    b[2] = replace(b[2], close=150, adjusted_close=150)
    with pytest.raises(InvalidPriceEvidence, match="intraday move"):
        compute_trials(b)


def test_source_blob_change_is_rejected_before_research(tmp_path):
    raw = (
        b"Date,Open,High,Low,Close,Adj Close\n"
        b"2020-01-02,100,100,100,100,100\n"
        b"2020-01-03,102,103,100,101,101\n"
        b"2020-01-06,100,102,99,101,101\n"
    )
    file = tmp_path / "source.csv"
    file.write_bytes(raw)
    assert len(compute_trials(read_bars(file, git_blob_sha(raw)))) == 1
    file.write_bytes(raw + b"2020-01-07,100,101,99,100,100\n")
    with pytest.raises(InvalidPriceEvidence, match="hash mismatch"):
        read_bars(file, git_blob_sha(raw))
