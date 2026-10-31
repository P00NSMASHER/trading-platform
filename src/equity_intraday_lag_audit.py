"""Paper-only SPY previous-session intraday-loss reversal falsification.

Frozen signal: if T-1 close/open - 1 <= -1%, hypothetical long SPY from
T official opening print to its closing print. Reverse-sign up-day short
control is diagnostic only, not a recommendation. No network, credentials,
orders or executable fill claims; immutable Git-blob-pinned local CSV only.
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

MAX_CALENDAR_GAP_DAYS = 7
PRIOR_INTRADAY_THRESHOLD = 0.01
COST_BPS = (10, 20, 40)


@dataclass(frozen=True)
class LagTrial:
    day: date
    prior_intraday_return: float
    intraday_return: float


@dataclass(frozen=True)
class PaperReturn:
    day: date
    intraday_return: float


def compute_trials(bars: list[Bar]) -> list[LagTrial]:
    """Use T-1 open and close only; reject malformed calendar/price inputs."""
    if len(bars) < 2:
        raise InvalidPriceEvidence("Need two ordered historical sessions.")
    for i, bar in enumerate(bars):
        if i and bar.day <= bars[i - 1].day:
            raise InvalidPriceEvidence("Duplicated or unordered sessions.")
        if not all(
            math.isfinite(x) and x > 0
            for x in (bar.open, bar.close, bar.adjusted_close)
        ):
            raise InvalidPriceEvidence("Invalid session price.")
        if not math.isfinite(bar.close / bar.open):
            raise InvalidPriceEvidence("Nonfinite intraday return.")
        if abs(bar.close / bar.open - 1) > 0.35:
            raise InvalidPriceEvidence("Unusually large intraday bar.")
    trials = []
    for i in range(1, len(bars)):
        prior, today = bars[i - 1], bars[i]
        if (today.day - prior.day).days > MAX_CALENDAR_GAP_DAYS:
            continue
        trials.append(LagTrial(
            today.day,
            prior.close / prior.open - 1,
            today.close / today.open - 1,
        ))
    return trials


def select(trials: list[LagTrial], condition: str) -> list[PaperReturn]:
    """Exactly two frozen arms; never optimize a threshold on holdout."""
    if condition == "prior_intraday_down_1pct":
        return [
            PaperReturn(x.day, x.intraday_return) for x in trials
            if x.prior_intraday_return <= -PRIOR_INTRADAY_THRESHOLD
        ]
    if condition == "prior_intraday_up_1pct_short_control":
        return [
            PaperReturn(x.day, -x.intraday_return) for x in trials
            if x.prior_intraday_return >= PRIOR_INTRADAY_THRESHOLD
        ]
    raise ValueError("Unregistered intraday-lag condition.")


def evaluate(bars: list[Bar]) -> dict:
    trials = compute_trials(bars)
    result = {
        "protocol": "SPY_T_MINUS_1_INTRADAY_DOWN_1PCT_NEXT_OPEN_CLOSE",
        "status": "EXPLORATORY_REJECT_NOT_EXECUTABLE_PROFIT_EVIDENCE",
        "execution": "IDEALIZED_OFFICIAL_OPEN_AND_CLOSE_PRINTS",
        "currency": "basis_points_of_gross_SPY_notional",
        "input_bars": len(bars),
        "phases": {},
    }
    for label in ("train", "validation", "holdout"):
        cohort = [x for x in trials if phase(x.day) == label]
        section = {"eligible_sessions": len(cohort)}
        for condition in (
            "prior_intraday_down_1pct",
            "prior_intraday_up_1pct_short_control",
        ):
            paper = select(cohort, condition)
            section[condition] = {
                "trigger_months": len({x.day.strftime("%Y-%m") for x in paper}),
                **{
                    "cost_%dbps" % cost: summary(
                        paper, cost,
                        ci=(cost == 20 and label in ("validation", "holdout")),
                    )
                    for cost in COST_BPS
                },
            }
        result["phases"][label] = section
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--git-blob-sha", required=True)
    args = parser.parse_args()
    out = evaluate(read_bars(args.file, args.git_blob_sha))
    out["symbol"] = "SPY"
    out["immutable_input_blob_sha1"] = args.git_blob_sha
    print(json.dumps(out, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
