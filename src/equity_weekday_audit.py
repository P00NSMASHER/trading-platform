"""Source-pinned, paper-only SPY weekday intraday-effect falsification.

The weekday is known before the entry decision. The hypothetical outcome
is the SAME session's official open-to-close return, not an executable fill.
No network, brokerage, credentials, orders, or raw-price redistribution.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from equity_reversal_audit import Bar, InvalidPriceEvidence, phase, read_bars, summary

COSTS_BPS = (10, 20, 40)
MAX_ABS_INTRADAY_MOVE = 0.35


@dataclass(frozen=True)
class WeekdayTrial:
    day: date
    intraday_return: float


def compute_trials(bars: list[Bar]) -> list[WeekdayTrial]:
    """One valid weekday bar -> one trial, with no hidden dropped losses."""
    if len(bars) < 3:
        raise InvalidPriceEvidence("Need at least three historical sessions.")
    trials: list[WeekdayTrial] = []
    previous_day = None
    for bar in bars:
        if previous_day is not None and bar.day <= previous_day:
            raise InvalidPriceEvidence("Duplicate or unordered price sessions.")
        if bar.day.weekday() >= 5:
            raise InvalidPriceEvidence("Non-trading weekend price session.")
        if not all(math.isfinite(v) and v > 0
                   for v in (bar.open, bar.close, bar.adjusted_close)):
            raise InvalidPriceEvidence("Nonfinite or nonpositive price.")
        change = bar.close / bar.open - 1
        if not math.isfinite(change) or abs(change) > MAX_ABS_INTRADAY_MOVE:
            raise InvalidPriceEvidence("Invalid or unusually large intraday change.")
        trials.append(WeekdayTrial(bar.day, change))
        previous_day = bar.day
    return trials


def select(trials: list[WeekdayTrial], arm: str) -> list[WeekdayTrial]:
    """Frozen Monday-long candidate and Friday-short diagnostic, no tuning."""
    if arm == "monday_long":
        return [t for t in trials if t.day.weekday() == 0]
    if arm == "friday_short_control":
        return [WeekdayTrial(t.day, -t.intraday_return)
                for t in trials if t.day.weekday() == 4]
    raise ValueError("Unknown or unregistered weekday arm.")


def evaluate(bars: list[Bar]) -> dict:
    trials = compute_trials(bars)
    out = {
        "protocol": "SPY_MONDAY_INTRADAY_LONG_FRIDAY_SHORT_CONTROL",
        "status": "EXPLORATORY_REJECT_AS_VERIFIED_EXECUTABLE_EDGE",
        "entry": "IDEALIZED_SAME_SESSION_OFFICIAL_OPEN",
        "exit": "IDEALIZED_SAME_SESSION_OFFICIAL_CLOSE",
        "cost_units": "gross_SPY_notional_roundtrip_bps",
        "input_bars": len(bars),
        "phases": {},
    }
    for name in ("train", "validation", "holdout"):
        cohort = [t for t in trials if phase(t.day) == name]
        section = {"eligible_sessions": len(cohort)}
        for arm in ("monday_long", "friday_short_control"):
            selected = select(cohort, arm)
            section[arm] = {
                "trigger_months": len({t.day.strftime("%Y-%m") for t in selected}),
                **{f"cost_{cost}bps": summary(selected, cost, ci=(
                    cost == 20 and name in ("validation", "holdout")))
                   for cost in COSTS_BPS},
            }
        out["phases"][name] = section
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--git-blob-sha", required=True)
    args = parser.parse_args()
    result = evaluate(read_bars(args.file, args.git_blob_sha))
    result["symbol"] = "SPY"
    result["immutable_input_blob_sha1"] = args.git_blob_sha
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
