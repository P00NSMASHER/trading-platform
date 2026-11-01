"""Synthetic/adversarial regression tests for source-pinned long-weekend study."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from equity_reversal_audit import Bar, InvalidPriceEvidence, git_blob_sha
from equity_long_weekend_audit import (
    GapObservation, build_observations, describe, evaluate, load_source,
    paired_observations, year_cluster_ci,
)


def b(day, op=100, close=100):
    return Bar(date.fromisoformat(day), op, close, close)


def sample():
    return [b("2020-01-17"), b("2020-01-21", 100, 101),
            b("2020-01-22", 100, 90), b("2020-01-27")]


def test_signal_uses_previous_market_calendar_not_future_close():
    first = build_observations(sample())
    edited = sample()
    edited[-1] = b("2020-01-27", 100, 125)
    later = build_observations(edited)
    assert first[0].previous_session_gap_days == 4
    assert first[0] == later[0]
    assert first[1].previous_session_gap_days == 1
    assert first[-1].previous_session_gap_days == 5


def test_research_net_costs_and_negative_controls():
    output = evaluate(sample(), sample())
    h = output["cohorts"]["retrospective_holdout_2019_2022"]
    long = h["post_long_weekend_gap_ge4_long_only"]
    assert long["events"] == 2
    assert long["gross_mean_bps"] == pytest.approx(50)
    assert long["net_mean_bps"]["20"] == pytest.approx(30)
    assert h["weekday_gap_eq1_control"]["events"] == 1
    assert output["two_archives_are_independent_vendors"] is False


def test_archive_calendar_mismatch_refused():
    right = [b("2020-01-17"), b("2020-01-21"), b("2020-01-23"),
             b("2020-01-27")]
    with pytest.raises(InvalidPriceEvidence, match="disagree"):
        paired_observations(sample(), right)


def test_archive_price_disagreement_refused():
    right = sample()
    right[1] = b("2020-01-21", 100, 101.1)
    with pytest.raises(InvalidPriceEvidence, match="returns disagree"):
        paired_observations(sample(), right)


def test_paired_scales_do_not_create_false_disagreement():
    right = [b(x.day.isoformat(), x.open * 0.5, x.close * 0.5) for x in sample()]
    rows, max_diff = paired_observations(sample(), right)
    assert len(rows) == 3 and max_diff < 1e-7


@pytest.mark.parametrize("bars", [
    [b("2020-01-17"), b("2020-01-18"), b("2020-01-21")],
    [b("2020-01-17"), b("2020-01-27"), b("2020-01-28")],
    [b("2020-01-21"), b("2020-01-17"), b("2020-01-22")],
    [b("2020-01-17"), b("2020-01-21", 100, 200), b("2020-01-22")],
])
def test_invalid_calendar_or_market_jump_refused(bars):
    with pytest.raises(InvalidPriceEvidence):
        build_observations(bars)


def test_no_false_confidence_for_two_years():
    obs = build_observations(sample())
    assert year_cluster_ci(obs) is None
    assert describe([])["gross_mean_bps"] is None


def test_year_cluster_resampling_fixed_and_stress_costs():
    long = [
        GapObservation(date(2019, 1, 22), 4, 100),
        GapObservation(date(2020, 1, 21), 4, -10),
        GapObservation(date(2021, 1, 19), 4, 25),
        GapObservation(date(2022, 1, 18), 4, -30),
    ]
    assert len(long) == 4
    assert year_cluster_ci(long, seed=45, replicates=120) == year_cluster_ci(
        long, seed=45, replicates=120)
    v = describe(long)
    assert v["net_mean_bps"]["10"] > v["net_mean_bps"]["30"]
    assert v["year_cluster_ci95_net20_bps"] is not None


def test_optional_extension_is_explicitly_single_vendor():
    left = [b("2022-12-29"), b("2022-12-30"), b("2023-01-03")]
    right = left + [b(day) for day in (
        "2023-01-04", "2023-01-05", "2023-01-06", "2023-01-09",
        "2023-01-10", "2023-01-11", "2023-01-12", "2023-01-13",
        "2023-01-17")]
    baseline = evaluate(left, right)
    extension = evaluate(left, right, include_single_vendor=True)
    label = "single_vendor_2023_2025"
    key = "post_long_weekend_gap_ge4_long_only"
    assert baseline["cohorts"][label][key]["events"] == 0
    assert extension["cohorts"][label][key]["events"] == 2


def test_immutable_source_hash_and_size_guards(tmp_path):
    payload = ("Date,Open,High,Low,Close\n"
               "2020-01-17,100,101,99,100\n"
               "2020-01-21,100,102,99,101\n"
               "2020-01-22,100,101,89,90\n").encode()
    path = tmp_path / "bars.csv"
    path.write_bytes(payload)
    assert len(load_source(path, git_blob_sha(payload))) == 3
    with pytest.raises(InvalidPriceEvidence, match="hash mismatch"):
        load_source(path, "0" * 40)
    with pytest.raises(InvalidPriceEvidence, match="Source absent"):
        load_source(tmp_path / "absent.csv", "0" * 40)


from equity_long_weekend_audit import gap_control_diagnostics


def test_matched_control_exploratory_negative_control_and_leave_one_year_out():
    # Preset outcomes, three distinct calendar years. No prices or live fills.
    rows = [
        GapObservation(date(2019, 1, 22), 4, 100),
        GapObservation(date(2019, 1, 28), 3, 0),
        GapObservation(date(2020, 1, 21), 4, -20),
        GapObservation(date(2020, 1, 27), 3, 10),
        GapObservation(date(2021, 1, 19), 4, -40),
        GapObservation(date(2021, 1, 25), 3, -20),
    ]
    report = gap_control_diagnostics(rows)
    assert report["exploratory_not_a_trading_signal"] is True
    assert report["same_roundtrip_cost_cancels_in_difference"] is True
    assert report["matched_years"] == [2019, 2020, 2021]
    assert report["long_events"] == 3
    assert report["three_day_weekend_controls"] == 3
    assert report["pooled_long_minus_control_gross_bps"] == 16.667
    assert report["equal_year_long_minus_control_gross_bps"] == 16.667
    assert report["leave_one_year_out_equal_year_range_bps"] == [-25, 40]
    assert report["gap_ge5_review_dates"] == []


def test_exploratory_control_flags_unusual_exchange_closure_not_silent_exclusion():
    # Oct 29-30 2012 NYSE closure by Sandy: Fri Oct 26 -> Wed Oct 31.
    rows = [
        GapObservation(date(2012, 10, 31), 5, -35.248499),
        GapObservation(date(2012, 11, 5), 3, 5),
        GapObservation(date(2012, 12, 26), 4, 10),
    ]
    report = gap_control_diagnostics(rows)
    assert report["long_events"] == 2
    assert report["gap_ge5_review_dates"] == ["2012-10-31"]
    assert report["long_mean_excluding_ge5_gaps_bps"] == 10
    # Preserve original hypothesis and label this exclusion post-hoc.
    assert report["pooled_long_minus_control_gross_bps"] == -17.624
    assert report["leave_one_year_out_equal_year_range_bps"] is None


def test_exploratory_control_refuses_unmatched_cohort_claim():
    rows = [GapObservation(date(2022, 1, 18), 4, 30)]
    report = gap_control_diagnostics(rows)
    assert report["matched_years"] == []
    assert report["pooled_long_minus_control_gross_bps"] is None
    assert report["equal_year_long_minus_control_gross_bps"] is None
    assert report["leave_one_year_out_equal_year_range_bps"] is None
    assert gap_control_diagnostics([])["long_events"] == 0


def test_evaluate_existing_primary_result_unmodified_by_negative_control():
    output = evaluate(sample(), sample())
    cohort = output["cohorts"]["retrospective_holdout_2019_2022"]
    assert cohort["post_long_weekend_gap_ge4_long_only"]["events"] == 2
    assert cohort["post_long_weekend_gap_ge4_long_only"]["net_mean_bps"]["20"] == 30
    assert cohort["exploratory_gap_control"]["long_events"] == 2
    assert cohort["exploratory_gap_control"]["gap_ge5_review_dates"] == ["2020-01-27"]


# Golden Goose checkpoint 3: prospective-signal-safe, post-hoc-only
# same-year and weekday negative control. No actual prices or fills.
from equity_long_weekend_audit import same_year_weekday_diagnostics


def test_same_year_weekday_control_is_event_weighted_and_respects_years():
    rows = [
        GapObservation(date(2019, 1, 22), 4, 100),  # Tuesday event
        GapObservation(date(2019, 1, 29), 1, 10),   # Tuesday control
        GapObservation(date(2019, 2, 5), 1, -10),   # Tuesday control
        GapObservation(date(2020, 1, 21), 4, -20),
        GapObservation(date(2020, 1, 28), 1, 10),
        GapObservation(date(2021, 1, 19), 4, 50),
        GapObservation(date(2021, 1, 26), 1, -10),
        GapObservation(date(2021, 1, 27), 1, 250),  # Wrong weekday: ignore
    ]
    v = same_year_weekday_diagnostics(rows)
    assert v["exploratory_post_hoc_uses_full_year_controls"] is True
    assert v["same_year_and_weekday"] is True
    assert v["total_long_events"] == v["matched_long_events"] == 3
    assert v["unmatched_event_dates"] == []
    assert v["non_long_gap_control_sessions"] == 5
    # Tuesday baselines: 2019=0, 2020=10, 2021=-10.
    assert v["event_weighted_difference_bps"] == 43.333
    assert v["equal_year_difference_bps"] == 43.333
    assert v["annual_difference_bps"] == {
        "2019": 100, "2020": -30, "2021": 60,
    }
    assert v["leave_one_year_out_equal_year_range_bps"] == [15, 80]


def test_same_year_weekday_control_preserves_event_counts_with_unequal_years():
    rows = [
        GapObservation(date(2019, 1, 22), 4, 60),
        GapObservation(date(2019, 2, 19), 4, 20),
        GapObservation(date(2019, 1, 29), 1, 0),
        GapObservation(date(2020, 1, 21), 4, 20),
        GapObservation(date(2020, 1, 28), 1, 10),
    ]
    v = same_year_weekday_diagnostics(rows)
    assert v["matched_long_events"] == 3
    assert v["event_weighted_difference_bps"] == 30
    assert v["equal_year_difference_bps"] == 25
    assert v["leave_one_year_out_equal_year_range_bps"] is None


def test_same_year_weekday_control_fails_closed_on_unmatched_event():
    rows = [
        GapObservation(date(2019, 1, 22), 4, -80),
        GapObservation(date(2019, 1, 28), 3, 20),  # Monday only
        GapObservation(date(2018, 1, 23), 1, 10),  # Tuesday, wrong year
    ]
    v = same_year_weekday_diagnostics(rows)
    assert v["total_long_events"] == 1
    assert v["matched_long_events"] == 0
    assert v["unmatched_event_dates"] == ["2019-01-22"]
    assert v["event_weighted_difference_bps"] is None
    assert v["equal_year_difference_bps"] is None
    assert v["annual_difference_bps"] == {}


def test_same_year_weekday_control_does_not_promote_event_as_control():
    rows = [
        GapObservation(date(2019, 1, 22), 4, 100),
        GapObservation(date(2019, 2, 19), 4, -50),
        GapObservation(date(2019, 1, 29), 1, 10),
    ]
    v = same_year_weekday_diagnostics(rows)
    assert v["non_long_gap_control_sessions"] == 1
    assert v["event_weighted_difference_bps"] == 15
    assert v["matched_long_events"] == 2


def test_same_year_weekday_control_zero_event_is_explicit():
    v = same_year_weekday_diagnostics([
        GapObservation(date(2021, 1, 26), 1, 50),
    ])
    assert v["total_long_events"] == 0
    assert v["event_weighted_difference_bps"] is None
    assert v["leave_one_year_out_equal_year_range_bps"] is None


def test_new_control_does_not_change_predeclared_evaluation_counts_or_returns():
    out = evaluate(sample(), sample())
    c = out["cohorts"]["retrospective_holdout_2019_2022"]
    assert c["post_long_weekend_gap_ge4_long_only"]["events"] == 2
    assert c["post_long_weekend_gap_ge4_long_only"]["net_mean_bps"]["20"] == 30
    diag = c["exploratory_same_year_weekday_control"]
    assert diag["total_long_events"] == 2
    assert diag["matched_long_events"] == 0
    assert diag["unmatched_event_dates"] == ["2020-01-21", "2020-01-27"]
    assert diag["event_weighted_difference_bps"] is None


# Run 2: prior-only rolling weekday controls, synthetic adverse tests.
from equity_long_weekend_audit import trailing_weekday_control


def _prior_rows():
    return [
        GapObservation(date(2020, 12, 22), 1, 0),
        GapObservation(date(2020, 12, 29), 1, 20),
        GapObservation(date(2021, 1, 5), 1, 40),
        GapObservation(date(2021, 1, 19), 4, 100),
    ]


def test_trailing_control_uses_prior_year_only_for_entry_baseline():
    v = trailing_weekday_control(_prior_rows(), date(2021, 1, 1),
                                 date(2021, 12, 31), 3, 3)
    assert v["total_long_events"] == v["matched_long_events"] == 1
    assert v["minimum_available_peer_count"] == 3
    assert v["event_weighted_difference_bps"] == 80
    assert v["annual_difference_bps"] == {"2021": 80}


def test_trailing_control_cannot_leak_future_price_outcome():
    a = trailing_weekday_control(_prior_rows(), date(2021, 1, 19),
                                 date(2021, 1, 19), 252, 2)
    future = _prior_rows() + [
        GapObservation(date(2021, 1, 26), 1, -10000),
        GapObservation(date(2021, 2, 2), 1, 10000),
    ]
    b = trailing_weekday_control(future, date(2021, 1, 19),
                                 date(2021, 1, 19), 252, 2)
    assert a == b


def test_trailing_control_ignores_old_holidays_and_wrong_weekdays():
    rows = [
        GapObservation(date(2020, 12, 21), 1, -800),
        GapObservation(date(2020, 12, 22), 1, 0),
        GapObservation(date(2020, 12, 29), 1, 20),
        GapObservation(date(2021, 1, 5), 4, 9000),
        GapObservation(date(2021, 1, 19), 4, 100),
    ]
    v = trailing_weekday_control(rows, date(2021, 1, 19),
                                 date(2021, 1, 19), 252, 2)
    assert v["event_weighted_difference_bps"] == 90
    assert v["minimum_available_peer_count"] == 2


def test_trailing_control_must_refuse_incomplete_cohort():
    v = trailing_weekday_control(_prior_rows(), date(2021, 1, 19),
                                 date(2021, 1, 19), 2, 3)
    assert v["total_long_events"] == 1 and v["matched_long_events"] == 0
    assert v["unmatched_event_dates"] == ["2021-01-19"]
    assert v["complete_cohort"] is False
    assert v["event_weighted_difference_bps"] is None


def test_trailing_control_rejects_bad_configuration_and_bad_calendar():
    for n, m in [(0, 1), (2, 0), (True, 1), (2, False)]:
        with pytest.raises(ValueError, match="Invalid predeclared"):
            trailing_weekday_control(_prior_rows(), date(2021, 1, 1),
                                     date(2021, 12, 31), n, m)
    with pytest.raises(ValueError, match="Invalid predeclared"):
        trailing_weekday_control(_prior_rows(), date(2022, 1, 1),
                                 date(2021, 1, 1))
    for invalid in (_prior_rows()[::-1], _prior_rows() + [_prior_rows()[-1]]):
        with pytest.raises(InvalidPriceEvidence, match="sorted unique"):
            trailing_weekday_control(invalid, date(2021, 1, 1),
                                     date(2021, 12, 31))


def test_trailing_control_preserves_predeclared_falsification():
    report = evaluate(sample(), sample())
    c = report["cohorts"]["retrospective_holdout_2019_2022"]
    assert c["post_long_weekend_gap_ge4_long_only"]["events"] == 2
    assert c["post_long_weekend_gap_ge4_long_only"]["net_mean_bps"]["20"] == 30
    assert c["exploratory_prior_only_weekday_control"]["complete_cohort"] is False
    assert c["exploratory_prior_only_weekday_control"]["total_long_events"] == 2


def test_trailing_control_zero_events_has_no_result():
    v = trailing_weekday_control(
        [GapObservation(date(2021, 1, 19), 1, 1)],
        date(2021, 1, 1), date(2021, 12, 31))
    assert v["total_long_events"] == 0
    assert v["event_weighted_difference_bps"] is None
