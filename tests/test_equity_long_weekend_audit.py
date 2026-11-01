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
