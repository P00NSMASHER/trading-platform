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
