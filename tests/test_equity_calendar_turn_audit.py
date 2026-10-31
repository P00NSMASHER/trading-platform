"""Synthetic/adversarial checks, never represented as actual prices or fills."""
from datetime import date
import pytest

from equity_reversal_audit import Bar, InvalidPriceEvidence, git_blob_sha
from equity_calendar_turn_audit import (
    _safe_load, _phase, _summary, bootstrap_ci, evaluate, leave_one_month_out,
    month_open_indices, paired_second_session_control, _moving_block_ci, shared_calendar,
)


def bar(s, open=100, close=100):
    return Bar(date.fromisoformat(s), open, close, close)


def test_cross_month_selection_and_no_lookahead():
    a = [bar("2018-12-31"), bar("2019-01-02", close=90), bar("2019-01-03")]
    assert month_open_indices(a) == {1}
    a[1] = bar("2019-01-02", close=111)
    assert month_open_indices(a) == {1}


def test_year_aware_month_selection_even_on_year_rollover():
    bars = [bar(d) for d in ("2019-12-31", "2020-01-02", "2020-01-09",
                              "2020-01-16", "2020-01-23", "2020-01-30",
                              "2020-01-31", "2020-02-03")]
    assert month_open_indices(bars) == {1, 7}


def test_month_gap_cannot_fabricate_first_day():
    with pytest.raises(InvalidPriceEvidence, match="gap"):
        month_open_indices([bar("2020-01-15"), bar("2020-02-03")])


def test_bad_order_rejected():
    with pytest.raises(InvalidPriceEvidence, match="Unsorted"):
        month_open_indices([bar("2020-01-02"), bar("2020-01-02")])


def test_missing_source_session_fails_closed():
    left = [bar("2020-01-30"), bar("2020-01-31"), bar("2020-02-03"), bar("2020-02-04")]
    right = [left[0], left[2], left[3]]
    with pytest.raises(InvalidPriceEvidence, match="calendars disagree"):
        shared_calendar(left, right)


def test_no_shared_period_fails_closed():
    with pytest.raises(InvalidPriceEvidence, match="No meaningful"):
        shared_calendar([bar("2019-01-02")], [bar("2020-01-02")])


def test_gross_vs_net_roundtrip_costs():
    assert _summary([25., -5.], 20.) == {
        "n": 2, "mean_gross_bps": 10., "mean_net_bps": -10.
    }
    assert _summary([], 20.)["mean_net_bps"] is None


def test_bootstrap_seed_is_deterministic_and_month_minimum():
    assert bootstrap_ci([25] * 9, 20) is None
    assert bootstrap_ci([10, 20, 40] * 10, 20, seed=88, draws=100) == bootstrap_ci(
        [10, 20, 40] * 10, 20, seed=88, draws=100)


def test_bootstrap_rejects_tiny_draw_count():
    with pytest.raises(ValueError, match="100"):
        bootstrap_ci([10] * 10, 20, draws=99)


def test_split_boundaries():
    assert _phase(date(2012, 12, 31)) == "train_2011_2012"
    assert _phase(date(2013, 1, 1)) == "validation_2013_2018"
    assert _phase(date(2019, 1, 1)) == "holdout_2019_2022"


def test_missing_data_not_interpolated_and_exact_selection():
    a = [bar("2018-12-28"), bar("2018-12-31"), bar("2019-01-02", close=101),
         bar("2019-01-03", close=80), bar("2019-01-04", close=90),
         bar("2019-02-01", close=105)]
    with pytest.raises(InvalidPriceEvidence, match="gap"):
        evaluate(a, a)


def test_rejects_anomalous_intraday_adjustments():
    a = [bar("2020-01-30"), bar("2020-01-31"), bar("2020-02-03", close=160)]
    with pytest.raises(InvalidPriceEvidence, match="Implausible"):
        shared_calendar(a, a)


def test_safe_load_rejects_mutated_source(tmp_path):
    rows = ("Date,Open,High,Low,Close,Adj Close\n"
            "2020-01-30,100,100,100,100,100\n"
            "2020-01-31,100,100,100,100,100\n"
            "2020-02-03,100,100,100,100,100\n").encode()
    path = tmp_path / "bars.csv"
    path.write_bytes(rows)
    assert len(_safe_load(path, git_blob_sha(rows))) == 3
    path.write_bytes(rows + b"\n")
    with pytest.raises(InvalidPriceEvidence, match="hash mismatch"):
        _safe_load(path, git_blob_sha(rows))


def test_synthetic_positive_gross_can_be_negative_after_costs():
    a = [bar("2018-12-28"), bar("2018-12-31"),
         bar("2019-01-02", close=100.1), bar("2019-01-03", close=101),
         bar("2019-01-04", close=90)]
    r = evaluate(a, a)
    x = r["periods"]["holdout_2019_2022"]["source_results"]["xjcarter"]
    assert x["signal"]["20"]["n"] == 1
    assert x["signal"]["20"]["mean_gross_bps"] == pytest.approx(10.)
    assert x["signal"]["20"]["mean_net_bps"] == pytest.approx(-10.)
    assert r["periods"]["holdout_2019_2022"]["other_days"] == 2


@pytest.mark.parametrize("day", ["2010-12-31", "2023-01-03", "2025-10-01"])
def test_phase_rejects_new_or_pre_cohort_years(day):
    with pytest.raises(InvalidPriceEvidence, match="outside preregistered"):
        _phase(date.fromisoformat(day))


@pytest.mark.parametrize("dates", [
    ("2010-12-30", "2010-12-31", "2011-01-03"),
    ("2022-12-29", "2022-12-30", "2023-01-03"),
])
def test_evaluation_cannot_extend_frozen_cohorts(dates):
    a = [bar(day) for day in dates]
    with pytest.raises(InvalidPriceEvidence, match="outside preregistered"):
        evaluate(a, a)


def test_leave_one_month_out_is_deterministic_and_costed():
    result = leave_one_month_out([0] * 9 + [100], 20)
    assert result == {
        "n": 10, "min_net_mean_bps": -20.0,
        "max_net_mean_bps": -8.889, "all_leave_one_out_positive": False,
    }
    assert leave_one_month_out([30] * 10, 20)["all_leave_one_out_positive"]
    assert leave_one_month_out([0] * 9, 20) is None


def test_leave_one_month_out_rejects_nonfinite_evidence():
    with pytest.raises(InvalidPriceEvidence, match="Nonfinite"):
        leave_one_month_out([float("nan")] + [10] * 9, 20)
    with pytest.raises(InvalidPriceEvidence, match="Nonfinite"):
        leave_one_month_out([10] * 10, float("inf"))


def test_paired_second_session_control_preserves_costs_and_frozen_year():
    rows = [bar("2018-12-31"), bar("2019-01-02", close=102),
            bar("2019-01-03", close=101), bar("2019-01-04")]
    out = paired_second_session_control(rows, rows)
    cohort = out["periods"]["holdout_2019_2022"]["xjcarter"]
    assert cohort["paired_months"] == 1
    assert cohort["first_session"]["mean_net_bps"] == 180.
    assert cohort["second_session"]["mean_net_bps"] == 80.
    assert cohort["first_minus_second_mean_bps"] == 100.
    assert cohort["first_minus_second_ci95_three_month_block_bps"] is None
    assert cohort["yearly_paired_counts"] == {"2019": 1}


def test_paired_control_requires_observed_second_session():
    rows = [bar("2018-12-28"), bar("2018-12-31"), bar("2019-01-02")]
    with pytest.raises(InvalidPriceEvidence, match="Second trading session missing"):
        paired_second_session_control(rows, rows)


def test_paired_control_does_not_select_on_same_day_return():
    rows = [bar("2019-01-31"), bar("2019-02-01", close=105),
            bar("2019-02-04", close=98), bar("2019-02-05")]
    changed = [rows[0], bar("2019-02-01", close=70), rows[2], rows[3]]
    a = paired_second_session_control(rows, rows)
    b = paired_second_session_control(changed, changed)
    x = a["periods"]["holdout_2019_2022"]["xjcarter"]
    y = b["periods"]["holdout_2019_2022"]["xjcarter"]
    assert x["paired_months"] == y["paired_months"] == 1
    assert x["first_minus_second_mean_bps"] != y["first_minus_second_mean_bps"]


def test_paired_control_reports_economically_overlap_without_false_replication():
    rows = [bar("2019-01-31"), bar("2019-02-01", close=101),
            bar("2019-02-04", close=99), bar("2019-02-05")]
    alt = [rows[0], bar("2019-02-01", close=101.001), rows[2], rows[3]]
    out = paired_second_session_control(rows, alt)
    assert out["sources_economically_overlapping"] is True
    cohort = out["periods"]["holdout_2019_2022"]
    assert cohort["xjcarter"]["paired_months"] == 1
    assert cohort["revred"]["paired_months"] == 1
    assert (cohort["xjcarter"]["first_minus_second_mean_bps"]
            != cohort["revred"]["first_minus_second_mean_bps"])


def test_moving_block_bootstrap_deterministic_and_not_an_alpha_claim():
    values = [10., -10., -20.] * 8
    a = _moving_block_ci(values, seed=772, draws=100, block=3)
    assert a == _moving_block_ci(values, seed=772, draws=100, block=3)
    assert len(a) == 2 and a[0] <= a[1]
    assert _moving_block_ci([1.] * 11) is None


@pytest.mark.parametrize("invalid,kwargs,error", [
    ([float("nan")] + [0.] * 11, {}, InvalidPriceEvidence),
    ([float("inf")] + [0.] * 11, {}, InvalidPriceEvidence),
    ([0.] * 12, {"draws": 10}, ValueError),
    ([0.] * 12, {"draws": 10001}, ValueError),
    ([0.] * 12, {"block": 0}, ValueError),
    ([0.] * 12, {"block": 13}, ValueError),
])
def test_moving_block_bootstrap_rejects_bad_evidence(invalid, kwargs, error):
    with pytest.raises(error):
        _moving_block_ci(invalid, **kwargs)


def test_paired_control_rejects_future_cohort_and_calendar_mismatch():
    outside = [bar("2022-12-30"), bar("2023-01-03"),
               bar("2023-01-04"), bar("2023-01-05")]
    with pytest.raises(InvalidPriceEvidence, match="outside preregistered"):
        paired_second_session_control(outside, outside)
    a = [bar("2019-01-31"), bar("2019-02-01"), bar("2019-02-04"), bar("2019-02-05")]
    b = [a[0], a[1], a[3]]
    with pytest.raises(InvalidPriceEvidence, match="calendars disagree"):
        paired_second_session_control(a, b)
