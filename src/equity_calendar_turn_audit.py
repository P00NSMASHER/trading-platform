"""Offline, SHA-pinned first-session-of-month SPY intraday falsification.

No market-data fetching, broker access, trading routes, future-data signals,
or claim that opening/closing prints were executable.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from datetime import date
from pathlib import Path

from equity_reversal_audit import Bar, InvalidPriceEvidence, read_bars

MAX_BYTES = 10_000_000
FIXED_COSTS_BPS = (10, 20, 30)
MIN_CI_MONTHS = 10


def _phase(d: date) -> str:
    if d < date(2013, 1, 1):
        return "train_2011_2012"
    if d < date(2019, 1, 1):
        return "validation_2013_2018"
    return "holdout_2019_2022"


def shared_calendar(first: list[Bar], second: list[Bar]) -> tuple[list[Bar], list[Bar]]:
    """Fail closed on different/missing trading sessions in the shared range."""
    if not first or not second:
        raise InvalidPriceEvidence("No source records to reconcile.")
    start, end = max(first[0].day, second[0].day), min(first[-1].day, second[-1].day)
    if start >= end:
        raise InvalidPriceEvidence("No meaningful common historical period.")
    a = [bar for bar in first if start <= bar.day <= end]
    b = [bar for bar in second if start <= bar.day <= end]
    if [bar.day for bar in a] != [bar.day for bar in b]:
        raise InvalidPriceEvidence("Source calendars disagree; no silent forward filling.")
    if len(a) < 3:
        raise InvalidPriceEvidence("Insufficient matching calendar sessions.")
    for series in (a, b):
        for bar in series:
            move = bar.close / bar.open - 1
            if not math.isfinite(move) or abs(move) > 0.35:
                raise InvalidPriceEvidence("Implausible intraday price move.")
    return a, b


def month_open_indices(bars: list[Bar]) -> set[int]:
    """Select month crossing by today's public date and previous session.

    The date is known at entry, unlike the close or future returns.
    A >7-day gap cannot be treated as a trustworthy first trading day.
    """
    indices: set[int] = set()
    for i in range(1, len(bars)):
        day, previous = bars[i].day, bars[i - 1].day
        if day <= previous:
            raise InvalidPriceEvidence("Unsorted or duplicate calendar sessions.")
        if (day - previous).days > 7:
            raise InvalidPriceEvidence("Calendar gap too large to infer month first.")
        if day.year != previous.year or day.month != previous.month:
            indices.add(i)
    return indices


def _summary(values_bps: list[float], cost: float) -> dict:
    if not values_bps:
        return {"n": 0, "mean_gross_bps": None, "mean_net_bps": None}
    mean_gross = sum(values_bps) / len(values_bps)
    return {"n": len(values_bps), "mean_gross_bps": round(mean_gross, 3),
            "mean_net_bps": round(mean_gross - cost, 3)}


def bootstrap_ci(values_bps: list[float], cost_bps: float,
                 seed: int = 41031, draws: int = 2000) -> list[float] | None:
    """One signal per month: resample whole signal months, not daily bars."""
    if len(values_bps) < MIN_CI_MONTHS:
        return None
    if draws < 100:
        raise ValueError("At least 100 bootstrap draws required.")
    rng = random.Random(seed)
    means = []
    n = len(values_bps)
    for _ in range(draws):
        means.append(sum(values_bps[rng.randrange(n)] for __ in range(n)) / n - cost_bps)
    means.sort()
    return [round(means[int((draws - 1) * .025)], 3),
            round(means[int((draws - 1) * .975)], 3)]


def evaluate(first: list[Bar], second: list[Bar]) -> dict:
    a, b = shared_calendar(first, second)
    selected = month_open_indices(a)
    result: dict = {
        "status": "FALSIFICATION_ONLY_NOT_EXECUTABLE_ALPHA",
        "shared_sessions": len(a), "first_session": a[0].day.isoformat(),
        "last_session": a[-1].day.isoformat(), "sources_economically_overlapping": True,
        "pre_registered_signal": "first observed trading session of new calendar month",
        "hypothetical_entry_exit": "regular-session open to close",
        "fixed_roundtrip_cost_bps": list(FIXED_COSTS_BPS), "periods": {},
    }
    for phase in ("train_2011_2012", "validation_2013_2018", "holdout_2019_2022"):
        entries = [i for i in range(1, len(a)) if _phase(a[i].day) == phase]
        picks = [i for i in entries if i in selected]
        nonpicks = [i for i in entries if i not in selected]
        period = {"eligible_sessions": len(entries), "first_month_days": len(picks),
                  "other_days": len(nonpicks), "source_results": {}}
        for label, series in (("xjcarter", a), ("revred", b)):
            pick_returns = [10000 * (series[i].close / series[i].open - 1) for i in picks]
            other_returns = [10000 * (series[i].close / series[i].open - 1) for i in nonpicks]
            period["source_results"][label] = {
                "signal": {str(cost): _summary(pick_returns, cost) for cost in FIXED_COSTS_BPS},
                "non_signal_control": _summary(other_returns, 0),
                "ci95_month_bootstrap_net_20bps": bootstrap_ci(pick_returns, 20)
                if phase == "holdout_2019_2022" else None,
            }
        result["periods"][phase] = period
    return result


def _safe_load(path: Path, sha: str) -> list[Bar]:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise InvalidPriceEvidence("Missing or oversized source evidence.")
    return read_bars(path, sha)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-file", type=Path, required=True)
    parser.add_argument("--first-blob", required=True, help="Full immutable upstream Git SHA-1 blob")
    parser.add_argument("--second-file", type=Path, required=True)
    parser.add_argument("--second-blob", required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(_safe_load(args.first_file, args.first_blob),
                              _safe_load(args.second_file, args.second_blob)),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
