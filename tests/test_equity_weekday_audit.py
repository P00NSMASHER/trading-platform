"""Synthetic adversarial tests for paper-only SPY calendar hypothesis."""
from dataclasses import replace
from datetime import date

import pytest

from equity_reversal_audit import Bar, InvalidPriceEvidence, git_blob_sha, read_bars
from equity_weekday_audit import compute_trials, evaluate, select


def bars():
    return [
        Bar(date(2020, 1, 3), 100, 98, 98),   # Friday: -2%, short gains
        Bar(date(2020, 1, 6), 100, 101, 101), # Monday: +1%, long gains
        Bar(date(2020, 1, 7), 100, 96, 96),  # Tuesday: no signal
        Bar(date(2020, 1, 10), 100, 102, 102), # Friday: +2%, short loses
        Bar(date(2020, 1, 13), 100, 95, 95), # Monday: -5%, long loses
    ]


def test_monday_selection_count_and_no_cherry_picking_losers():
    selected = select(compute_trials(bars()), "monday_long")
    assert [x.day for x in selected] == [date(2020, 1, 6), date(2020, 1, 13)]
    assert [x.intraday_return for x in selected] == pytest.approx([0.01, -0.05])


def test_friday_short_control_is_separate_and_captures_losses():
    selected = select(compute_trials(bars()), "friday_short_control")
    assert [x.day for x in selected] == [date(2020, 1, 3), date(2020, 1, 10)]
    assert [x.intraday_return for x in selected] == pytest.approx([0.02, -0.02])


def test_t_close_affects_payoff_but_not_preknown_calendar_trigger():
    before = select(compute_trials(bars()), "monday_long")
    changed = bars()
    changed[1] = replace(changed[1], close=90, adjusted_close=90)
    after = select(compute_trials(changed), "monday_long")
    assert [x.day for x in before] == [x.day for x in after]
    assert before[0].intraday_return > 0 > after[0].intraday_return


def test_cost_applied_each_trigger_with_fixed_phases():
    out = evaluate(bars())
    assert out["phases"]["train"]["eligible_sessions"] == 0
    assert out["phases"]["validation"]["eligible_sessions"] == 0
    monday = out["phases"]["holdout"]["monday_long"]
    assert monday["cost_20bps"]["trades"] == 2
    assert monday["cost_20bps"]["mean_gross_bps"] == pytest.approx(-200)
    assert monday["cost_20bps"]["mean_net_bps"] == pytest.approx(-220)
    assert monday["cost_40bps"]["mean_net_bps"] == pytest.approx(-240)
    assert monday["cost_20bps"]["ci95_month_cluster_bps"] is None


def test_unregistered_hindsight_arm_denied():
    with pytest.raises(ValueError, match="unregistered"):
        select([], "best_performing_weekday")


@pytest.mark.parametrize("case", ["duplicate", "reverse"])
def test_duplicate_or_unsorted_calendar_fails(case):
    b = bars()
    b[1] = replace(b[1], day=b[0].day if case == "duplicate" else date(2019, 1, 1))
    with pytest.raises(InvalidPriceEvidence, match="unordered"):
        compute_trials(b)


def test_weekend_evidence_rejected_instead_of_hidden_omission():
    b = bars()
    b[1] = replace(b[1], day=date(2020, 1, 4))
    with pytest.raises(InvalidPriceEvidence, match="weekend"):
        compute_trials(b)


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_nonfinite_or_nonpositive_prices_fail(value):
    b = bars()
    b[1] = replace(b[1], open=value)
    with pytest.raises(InvalidPriceEvidence):
        compute_trials(b)


def test_unusual_intraday_move_does_not_masquerade_as_alpha():
    b = bars()
    b[1] = replace(b[1], close=151, adjusted_close=151)
    with pytest.raises(InvalidPriceEvidence, match="unusually large"):
        compute_trials(b)


@pytest.mark.parametrize("num", [0, 1, 2])
def test_inadequate_source_does_not_look_like_a_zero_return(num):
    with pytest.raises(InvalidPriceEvidence, match="three"):
        compute_trials(bars()[:num])


def test_exact_git_blob_mandatory_and_mutated_bytes_refused(tmp_path):
    raw = (b"Date,Open,High,Low,Close,Adj Close\n"
           b"2020-01-03,100,100,98,98,98\n"
           b"2020-01-06,100,102,99,101,101\n"
           b"2020-01-07,100,100,96,96,96\n")
    file = tmp_path / "spy.csv"
    file.write_bytes(raw)
    assert len(compute_trials(read_bars(file, git_blob_sha(raw)))) == 3
    file.write_bytes(raw + b"2020-01-08,100,101,99,100,100\n")
    with pytest.raises(InvalidPriceEvidence, match="hash mismatch"):
        read_bars(file, git_blob_sha(raw))
