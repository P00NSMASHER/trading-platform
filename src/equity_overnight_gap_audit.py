"""Offline, source-pinned prior-overnight-gap continuation falsification.

At T open, only T-2 raw close and T-1 raw open determine the signal.
T's own open/close are hypothetical outcome prices, not proven executions.
No brokerage API, network requests, secrets, orders or vendor-data upload.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from equity_reversal_audit import (
    Bar, InvalidPriceEvidence, phase, read_bars, summary,
)

GAP_THRESHOLD = 0.01
MAX_CALENDAR_GAP_DAYS = 7
MAX_ABS_DAILY_MOVE = 0.35
COSTS_BPS = (10, 20, 40)


@dataclass(frozen=True)
class OvernightTrial:
    day: date
    prior_overnight_return: float
    intraday_return: float


@dataclass(frozen=True)
class PaperReturn:
    day: date
    intraday_return: float


def compute_trials(bars: list[Bar]) -> list[OvernightTrial]:
    """Require T-2, T-1 and T ordered; do not use today's outcome in signal."""
    if len(bars) < 3:
        raise InvalidPriceEvidence("Need three ordered price sessions.")
    for i, bar in enumerate(bars):
        if i and bar.day <= bars[i - 1].day:
            raise InvalidPriceEvidence("Duplicate or unordered price sessions.")
        if not all(math.isfinite(v) and v > 0
                   for v in (bar.open, bar.close, bar.adjusted_close)):
            raise InvalidPriceEvidence("Nonfinite or nonpositive price.")
        move = bar.close / bar.open - 1
        if not math.isfinite(move) or abs(move) > MAX_ABS_DAILY_MOVE:
            raise InvalidPriceEvidence("Invalid or unusually large intraday move.")

    trials = []
    for i in range(2, len(bars)):
        old, prior, today = bars[i - 2], bars[i - 1], bars[i]
        if ((prior.day - old.day).days > MAX_CALENDAR_GAP_DAYS
                or (today.day - prior.day).days > MAX_CALENDAR_GAP_DAYS):
            continue
        prior_gap = prior.open / old.close - 1
        if not math.isfinite(prior_gap) or abs(prior_gap) > MAX_ABS_DAILY_MOVE:
            raise InvalidPriceEvidence("Invalid or unusually large overnight gap.")
        trials.append(OvernightTrial(
            today.day, prior_gap, today.close / today.open - 1,
        ))
    return trials


def select(trials: list[OvernightTrial], arm: str) -> list[PaperReturn]:
    """Freeze one long hypothesis and one SHORT negative control only."""
    if arm == "prior_overnight_up_1pct_long":
        return [PaperReturn(t.day, t.intraday_return) for t in trials
                if t.prior_overnight_return >= GAP_THRESHOLD]
    if arm == "prior_overnight_down_1pct_short_control":
        return [PaperReturn(t.day, -t.intraday_return) for t in trials
                if t.prior_overnight_return <= -GAP_THRESHOLD]
    raise ValueError("Unknown or unregistered overnight-gap arm.")


def evaluate(bars: list[Bar]) -> dict:
    trials = compute_trials(bars)
    result = {
        "protocol": "SPY_PRIOR_OVERNIGHT_GAP_UP_1PCT_NEXT_INTRADAY_LONG",
        "status": "EXPLORATORY_REJECT_NO_EXECUTABLE_EDGE",
        "entry": "IDEALIZED_NEXT_SESSION_OFFICIAL_OPEN_PRINT",
        "exit": "IDEALIZED_SAME_SESSION_OFFICIAL_CLOSE_PRINT",
        "cost_units": "bps_of_gross_single_leg_notional_roundtrip",
        "input_bars": len(bars),
        "phases": {},
    }
    for label in ("train", "validation", "holdout"):
        cohort = [x for x in trials if phase(x.day) == label]
        section = {"eligible_sessions": len(cohort)}
        for arm in (
            "prior_overnight_up_1pct_long",
            "prior_overnight_down_1pct_short_control",
        ):
            selected = select(cohort, arm)
            section[arm] = {
                "trigger_months": len({x.day.strftime("%Y-%m") for x in selected}),
                **{
                    f"cost_{cost}bps": summary(
                        selected, cost,
                        ci=(cost == 20 and label in ("validation", "holdout")),
                    )
                    for cost in COSTS_BPS
                },
            }
        result["phases"][label] = section
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--git-blob-sha", required=True)
    args = parser.parse_args()
    result = evaluate(read_bars(args.file, args.git_blob_sha))
    result["symbol"] = "SPY"
    result["immutable_input_blob_sha1"] = args.git_blob_sha
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
