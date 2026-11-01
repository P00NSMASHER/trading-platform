"""Source-pinned SPY post-long-weekend intraday hypothesis falsification.

Offline research only: no broker, market fetch, orders, or executable fills.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from equity_reversal_audit import Bar, InvalidPriceEvidence, read_bars

MAX_SOURCE_BYTES = 10_000_000
COST_GRID_BPS = (10, 20, 30)
COHORTS = (
    ("train_2011_2012", date(2011, 1, 1), date(2012, 12, 31)),
    ("validation_2013_2018", date(2013, 1, 1), date(2018, 12, 31)),
    ("retrospective_holdout_2019_2022", date(2019, 1, 1), date(2022, 12, 31)),
    ("single_vendor_2023_2025", date(2023, 1, 1), date(2025, 12, 31)),
)


@dataclass(frozen=True)
class GapObservation:
    day: date
    previous_session_gap_days: int
    intraday_bps: float


def load_source(path: Path, blob_sha: str) -> list[Bar]:
    """No network requests, mutable source acceptance or oversized input."""
    if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        raise InvalidPriceEvidence("Source absent or above 10 MB limit.")
    return read_bars(path, blob_sha)


def build_observations(bars: list[Bar]) -> list[GapObservation]:
    if len(bars) < 3:
        raise InvalidPriceEvidence("Too few sessions for gap research.")
    out: list[GapObservation] = []
    for previous, current in zip(bars, bars[1:]):
        days = (current.day - previous.day).days
        if days < 1 or days > 7:
            raise InvalidPriceEvidence("Unsorted or unexplained missing-session gap.")
        if current.day.weekday() > 4 or previous.day.weekday() > 4:
            raise InvalidPriceEvidence("Weekend trading bar in NYSE daily archive.")
        ret = 10_000 * (current.close / current.open - 1)
        if not math.isfinite(ret) or abs(ret) > 3_500:
            raise InvalidPriceEvidence("Unexplained intraday outlier.")
        out.append(GapObservation(current.day, days, ret))
    return out


def paired_observations(left: list[Bar], right: list[Bar]) -> tuple[list[GapObservation], float]:
    """Fail closed on asymmetric history rather than silently intersect calendars."""
    begin, end = max(left[0].day, right[0].day), min(left[-1].day, right[-1].day)
    a = [bar for bar in left if begin <= bar.day <= end]
    b = [bar for bar in right if begin <= bar.day <= end]
    if len(a) < 3 or [x.day for x in a] != [x.day for x in b]:
        raise InvalidPriceEvidence("Independent archives disagree on overlapping sessions.")
    ta, tb = build_observations(a), build_observations(b)
    disagreement = max(abs(x.intraday_bps - y.intraday_bps) for x, y in zip(ta, tb))
    if disagreement > 0.05:
        raise InvalidPriceEvidence("Intraday returns disagree across source archives.")
    return ta, disagreement


def year_cluster_ci(selected: list[GapObservation], cost_bps: float = 20,
                    seed: int = 20261031, replicates: int = 2048) -> list[float] | None:
    """Year-level resampling. Too few years -> no asserted confidence interval."""
    by_year: dict[int, list[float]] = defaultdict(list)
    for row in selected:
        by_year[row.day.year].append(row.intraday_bps - cost_bps)
    groups = list(by_year.values())
    if len(groups) < 3 or replicates < 40:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(replicates):
        picks = [groups[rng.randrange(len(groups))] for _ in groups]
        means.append(sum(sum(x) for x in picks) / sum(len(x) for x in picks))
    means.sort()
    return [round(means[int(0.025 * (len(means) - 1))], 3),
            round(means[int(0.975 * (len(means) - 1))], 3)]


def describe(selected: list[GapObservation]) -> dict:
    if not selected:
        return {"events": 0, "gross_mean_bps": None, "net_mean_bps": None,
                "year_cluster_ci95_net20_bps": None}
    mean = sum(x.intraday_bps for x in selected) / len(selected)
    return {
        "events": len(selected),
        "gross_mean_bps": round(mean, 3),
        "net_mean_bps": {str(cost): round(mean - cost, 3) for cost in COST_GRID_BPS},
        "net20_positive_event_pct": round(
            100 * sum(x.intraday_bps > 20 for x in selected) / len(selected), 2),
        "year_cluster_ci95_net20_bps": year_cluster_ci(selected),
        "worst_net20_session_bps": round(min(x.intraday_bps - 20 for x in selected), 3),
        "year_counts": {str(year): sum(x.day.year == year for x in selected)
                        for year in sorted({x.day.year for x in selected})},
    }



def gap_control_diagnostics(rows: list[GapObservation]) -> dict:
    """Exploratory negative control, not a new strategy or independent test.

    A same-cost comparison against regular three-day weekends removes the
    constant assumed transaction cost. It does NOT remove weekday/calendar
    confounding, execution uncertainty, or post-selection bias.
    """
    long = [x for x in rows if x.previous_session_gap_days >= 4]
    ordinary = [x for x in rows if x.previous_session_gap_days == 3]
    suspect = [x for x in long if x.previous_session_gap_days >= 5]
    sensitivity = [x.intraday_bps for x in long
                   if x.previous_session_gap_days == 4]
    result = {
        "exploratory_not_a_trading_signal": True,
        "same_roundtrip_cost_cancels_in_difference": True,
        "long_events": len(long),
        "three_day_weekend_controls": len(ordinary),
        "pooled_long_minus_control_gross_bps": None,
        "equal_year_long_minus_control_gross_bps": None,
        "matched_years": [],
        "annual_difference_bps": {},
        "leave_one_year_out_equal_year_range_bps": None,
        "gap_ge5_review_dates": [x.day.isoformat() for x in suspect],
        "long_mean_excluding_ge5_gaps_bps": (
            round(sum(sensitivity) / len(sensitivity), 3)
            if suspect and sensitivity else None
        ),
    }
    if not long or not ordinary:
        return result
    years: dict[int, dict[str, list[float]]] = defaultdict(
        lambda: {"long": [], "ordinary": []}
    )
    for row in rows:
        if row.previous_session_gap_days >= 4:
            years[row.day.year]["long"].append(row.intraday_bps)
        elif row.previous_session_gap_days == 3:
            years[row.day.year]["ordinary"].append(row.intraday_bps)
    annual = []
    for year in sorted(years):
        buckets = years[year]
        if not buckets["long"] or not buckets["ordinary"]:
            continue
        value = (sum(buckets["long"]) / len(buckets["long"])
                 - sum(buckets["ordinary"]) / len(buckets["ordinary"]))
        annual.append(value)
        result["matched_years"].append(year)
        result["annual_difference_bps"][str(year)] = round(value, 3)
    if not annual:
        return result
    result["pooled_long_minus_control_gross_bps"] = round(
        sum(x.intraday_bps for x in long) / len(long)
        - sum(x.intraday_bps for x in ordinary) / len(ordinary), 3)
    result["equal_year_long_minus_control_gross_bps"] = round(
        sum(annual) / len(annual), 3)
    if len(annual) >= 3:
        leave_one_out = [
            (sum(annual) - value) / (len(annual) - 1)
            for value in annual
        ]
        result["leave_one_year_out_equal_year_range_bps"] = [
            round(min(leave_one_out), 3),
            round(max(leave_one_out), 3),
        ]
    return result



def same_year_weekday_diagnostics(rows: list[GapObservation]) -> dict:
    """Post-hoc matched negative control; full-year data are NOT an entry signal.

    For each long-gap day compare its observed open-to-close return with the
    average of all *non-long-gap* sessions in the SAME year and weekday.
    This removes a simple weekday/year composition difference, but does not
    remove holidays, intraday entry-price uncertainty, survivorship or
    other selection bias. If any event cannot be matched, refuse an
    incomplete comparison rather than silently dropping a losing event.
    """
    events = [r for r in rows if r.previous_session_gap_days >= 4]
    pool: dict[tuple[int, int], list[float]] = defaultdict(list)
    for row in rows:
        if row.previous_session_gap_days < 4:
            pool[(row.day.year, row.day.weekday())].append(row.intraday_bps)
    differences: dict[int, list[float]] = defaultdict(list)
    unmatched: list[str] = []
    for event in events:
        peers = pool.get((event.day.year, event.day.weekday()), [])
        if not peers:
            unmatched.append(event.day.isoformat())
            continue
        differences[event.day.year].append(
            event.intraday_bps - sum(peers) / len(peers))
    result = {
        "exploratory_post_hoc_uses_full_year_controls": True,
        "same_year_and_weekday": True,
        "controls_exclude_long_gaps": True,
        "total_long_events": len(events),
        "matched_long_events": sum(map(len, differences.values())),
        "unmatched_event_dates": unmatched,
        "non_long_gap_control_sessions": sum(map(len, pool.values())),
        "event_weighted_difference_bps": None,
        "equal_year_difference_bps": None,
        "annual_difference_bps": {},
        "leave_one_year_out_equal_year_range_bps": None,
    }
    if not events or unmatched:
        return result
    annual = {
        year: sum(values) / len(values)
        for year, values in sorted(differences.items())
    }
    result["event_weighted_difference_bps"] = round(
        sum(sum(v) for v in differences.values()) / len(events), 3)
    result["equal_year_difference_bps"] = round(
        sum(annual.values()) / len(annual), 3)
    result["annual_difference_bps"] = {
        str(year): round(value, 3) for year, value in annual.items()
    }
    if len(annual) >= 3:
        annual_values = list(annual.values())
        leave_one_out = [
            (sum(annual_values) - value) / (len(annual_values) - 1)
            for value in annual_values
        ]
        result["leave_one_year_out_equal_year_range_bps"] = [
            round(min(leave_one_out), 3),
            round(max(leave_one_out), 3),
        ]
    return result



def trailing_weekday_control(rows: list[GapObservation], cohort_start: date,
                             cohort_stop: date, lookback_sessions: int = 252,
                             min_controls: int = 10) -> dict:
    """EXPLORATORY prior-only negative control, not a live trading signal.

    Compare each long-gap event to its weekday's non-long-gap observations
    in the previous `lookback_sessions` market sessions. Prior years may
    provide history, but future and same-day returns cannot enter a baseline.
    If an event lacks peers, withhold the whole cohort's estimated mean.
    """
    if (type(lookback_sessions) is not int or lookback_sessions < 1
            or type(min_controls) is not int or min_controls < 1
            or cohort_start > cohort_stop):
        raise ValueError("Invalid predeclared trailing control settings.")
    if any(a.day >= b.day for a, b in zip(rows, rows[1:])):
        raise InvalidPriceEvidence("Trailing controls require sorted unique sessions.")
    n, matched, missing = 0, [], []
    minimum_peer_count = None
    for index, row in enumerate(rows):
        if not (cohort_start <= row.day <= cohort_stop
                and row.previous_session_gap_days >= 4):
            continue
        n += 1
        peers = [r.intraday_bps for r in
                 rows[max(0, index - lookback_sessions):index]
                 if r.day.weekday() == row.day.weekday()
                 and r.previous_session_gap_days < 4]
        minimum_peer_count = (len(peers) if minimum_peer_count is None
                              else min(minimum_peer_count, len(peers)))
        if len(peers) < min_controls:
            missing.append(row.day.isoformat())
        else:
            matched.append((row.day.year,
                            row.intraday_bps - sum(peers) / len(peers)))
    result = {
        "exploratory_prior_only_not_a_trading_signal": True,
        "same_weekday_non_long_gap_peers_only": True,
        "lookback_prior_sessions": lookback_sessions,
        "min_controls_required": min_controls,
        "total_long_events": n,
        "matched_long_events": len(matched),
        "minimum_available_peer_count": minimum_peer_count,
        "unmatched_event_dates": missing,
        "complete_cohort": n > 0 and not missing,
        "event_weighted_difference_bps": None,
        "annual_difference_bps": {},
    }
    if not result["complete_cohort"]:
        return result
    result["event_weighted_difference_bps"] = round(
        sum(value for _, value in matched) / len(matched), 3)
    per_year: dict[int, list[float]] = defaultdict(list)
    for year, value in matched:
        per_year[year].append(value)
    result["annual_difference_bps"] = {
        str(year): round(sum(values) / len(values), 3)
        for year, values in sorted(per_year.items())
    }
    return result


def evaluate(first: list[Bar], second: list[Bar], include_single_vendor: bool = False) -> dict:
    paired, max_diff = paired_observations(first, second)
    extension = build_observations(second) if include_single_vendor else []
    result = {"research_only": True, "two_archives_are_independent_vendors": False,
              "matching_sessions": len(paired) + 1,
              "maximum_cross_archive_intraday_difference_bps": round(max_diff, 6),
              "cohorts": {}}
    for label, start, stop in COHORTS:
        source = extension if label.startswith("single_vendor") else paired
        # Only the calendar-gap signal is predeclared, not a return threshold.
        window = [x for x in source if start <= x.day <= stop]
        result["cohorts"][label] = {
            "post_long_weekend_gap_ge4_long_only": describe(
                [x for x in window if x.previous_session_gap_days >= 4]),
            "ordinary_weekend_gap_eq3_control": describe(
                [x for x in window if x.previous_session_gap_days == 3]),
            "weekday_gap_eq1_control": describe(
                [x for x in window if x.previous_session_gap_days == 1]),
            "exploratory_gap_control": gap_control_diagnostics(window),
            "exploratory_same_year_weekday_control": same_year_weekday_diagnostics(window),
            "exploratory_prior_only_weekday_control": trailing_weekday_control(
                source, start, stop),
        }
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--first-file", type=Path, required=True)
    p.add_argument("--first-blob", required=True)
    p.add_argument("--second-file", type=Path, required=True)
    p.add_argument("--second-blob", required=True)
    p.add_argument("--include-second-source-2023-2025", action="store_true")
    args = p.parse_args()
    result = evaluate(load_source(args.first_file, args.first_blob),
                      load_source(args.second_file, args.second_blob),
                      args.include_second_source_2023_2025)
    result["status"] = "RESEARCH_FALSIFICATION_ONLY_NO_EXECUTABLE_EDGE"
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
