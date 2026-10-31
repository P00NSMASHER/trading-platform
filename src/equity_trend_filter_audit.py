"""Offline, immutable-source 20-session ETF trend hypothesis audit.

Research only: no networking, orders, broker access, credentials, or price downloads.
A fixed previous-session 20-day trend condition precedes the simulated entry.
Reuses source authentication and cost/bootstrap machinery from the existing,
independently reviewed equity_reversal_audit rather than adding dependencies.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from equity_reversal_audit import (
    Bar,
    InvalidPriceEvidence,
    phase,
    read_bars,
    summary,
)

LOOKBACK_SESSIONS = 20
THRESHOLD = 0.05


@dataclass(frozen=True)
class TrendTrial:
    day: date
    trailing_20session_return: float
    intraday_return: float


def compute_trials(bars: list[Bar]) -> list[TrendTrial]:
    """Use T-1 vs T-21 adjusted closes, enter T open, exit T close.

    T-1 is the most recent available close before T's hypothetical opening
    entry. No T open/close or T+1 prices are used to select T.
    """
    if len(bars) < LOOKBACK_SESSIONS + 2:
        raise InvalidPriceEvidence("Need at least 22 ordered price sessions.")
    trials: list[TrendTrial] = []
    for i in range(LOOKBACK_SESSIONS + 1, len(bars)):
        earlier = bars[i - LOOKBACK_SESSIONS - 1].adjusted_close
        previous = bars[i - 1].adjusted_close
        entry = bars[i].open
        exit_price = bars[i].close
        if not all(math.isfinite(v) and v > 0 for v in (earlier, previous, entry, exit_price)):
            raise InvalidPriceEvidence("Invalid price in trend audit.")
        prior_trend = previous / earlier - 1
        intraday_return = exit_price / entry - 1
        if not math.isfinite(prior_trend) or abs(intraday_return) > 0.35:
            raise InvalidPriceEvidence("Unusual trend or intraday return: verify source adjustments.")
        trials.append(TrendTrial(bars[i].day, prior_trend, intraday_return))
    return trials


def select(trials: list[TrendTrial], condition: str) -> list[TrendTrial]:
    """The NEGATIVE trend signal is a negative control, not a trading pick."""
    if condition == "prior_20session_up_5pct":
        return [t for t in trials if t.trailing_20session_return >= THRESHOLD]
    if condition == "prior_20session_down_5pct_control":
        return [t for t in trials if t.trailing_20session_return <= -THRESHOLD]
    if condition == "every_session_control":
        return list(trials)
    raise ValueError("Unregistered trend condition.")


def evaluate(bars: list[Bar]) -> dict:
    trials = compute_trials(bars)
    outcome = {
        "protocol": "FIXED_20_SESSION_POSITIVE_TREND_HYPOTHESIS",
        "entry": "HYPOTHETICAL_NEXT_REGULAR_SESSION_OPEN",
        "exit": "SAME_SESSION_CLOSE",
        "research_status": "HYPOTHESIS_ONLY_NO_FILL_OR_TRADING_AUTHORIZATION",
        "bars": len(bars),
        "first": bars[0].day.isoformat(),
        "last": bars[-1].day.isoformat(),
        "phases": {},
    }
    conditions = (
        "prior_20session_up_5pct",
        "prior_20session_down_5pct_control",
        "every_session_control",
    )
    for name in ("train", "validation", "holdout"):
        cohort = [t for t in trials if phase(t.day) == name]
        outcome["phases"][name] = {}
        for condition in conditions:
            selected = select(cohort, condition)
            outcome["phases"][name][condition] = {
                "cost_10bps": summary(selected, 10, ci=(name == "holdout")),
                "cost_30bps": summary(selected, 30),
                "cost_50bps": summary(selected, 50),
            }
    return outcome


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--git-blob-sha", required=True, help="Exact SHA-1 Git BLOB, not branch HEAD")
    p.add_argument("--symbol", required=True)
    args = p.parse_args()
    result = evaluate(read_bars(args.file, args.git_blob_sha))
    result["symbol"] = args.symbol
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
