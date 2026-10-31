"""Offline, source-verified SPY/QQQ five-session divergence falsification.

No network access, brokerage credentials, order placement, or live execution.
Inputs are caller-provided immutable Git-blob-pinned CSVs.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date

from equity_reversal_audit import (
    Bar, InvalidPriceEvidence, phase, read_bars, summary,
)

LOOKBACK_SESSIONS = 5
MIN_ALIGNED_SESSIONS = LOOKBACK_SESSIONS + 2
RELATIVE_LAG_THRESHOLD = 0.02
MAX_CALENDAR_GAP_DAYS = 7


@dataclass(frozen=True)
class PairObservation:
    day: date
    prior_5session_qqq_minus_spy: float
    intraday_qqq_minus_spy: float


@dataclass(frozen=True)
class PaperReturn:
    day: date
    intraday_return: float


def compute_pairs(spy_bars: list[Bar], qqq_bars: list[Bar]) -> list[PairObservation]:
    """At T, use T-1 versus T-6 closes; trade T open-to-close only.

    Match EXACT dates, never forward-fill missing prices. Both legs use
    50% of gross notional. A 5-session signal is known before entry day T.
    """
    first_common = max(spy_bars[0].day, qqq_bars[0].day)
    last_common = min(spy_bars[-1].day, qqq_bars[-1].day)
    spy_common = [b for b in spy_bars if first_common <= b.day <= last_common]
    qqq_common = [b for b in qqq_bars if first_common <= b.day <= last_common]
    if [b.day for b in spy_common] != [b.day for b in qqq_common]:
        raise InvalidPriceEvidence("Unsynchronized session calendar: missing one-leg bars.")
    aligned = list(zip(spy_common, qqq_common))
    if len(aligned) < MIN_ALIGNED_SESSIONS:
        raise InvalidPriceEvidence("Need at least 7 common, ordered price sessions.")
    trials: list[PairObservation] = []
    for i in range(MIN_ALIGNED_SESSIONS - 1, len(aligned)):
        s_today, q_today = aligned[i]
        s_prior, q_prior = aligned[i - 1]
        s_old, q_old = aligned[i - LOOKBACK_SESSIONS - 1]
        if (s_today.day - s_prior.day).days > MAX_CALENDAR_GAP_DAYS:
            # Do not treat a stale last quote as an ordinary next session.
            continue
        vals = (
            s_today.open, s_today.close, q_today.open, q_today.close,
            s_prior.adjusted_close, s_old.adjusted_close,
            q_prior.adjusted_close, q_old.adjusted_close,
        )
        if not all(math.isfinite(v) and v > 0 for v in vals):
            raise InvalidPriceEvidence("Nonfinite/nonpositive pair price.")
        lag = (q_prior.adjusted_close / q_old.adjusted_close
               - s_prior.adjusted_close / s_old.adjusted_close)
        spread = (q_today.close / q_today.open
                  - s_today.close / s_today.open)
        if not math.isfinite(lag) or not math.isfinite(spread):
            raise InvalidPriceEvidence("Nonfinite pair return.")
        if (abs(q_today.close / q_today.open - 1) > .35
                or abs(s_today.close / s_today.open - 1) > .35):
            raise InvalidPriceEvidence("Unusual intraday gap: verify OHLC adjustments.")
        trials.append(PairObservation(s_today.day, lag, spread))
    return trials


def select(trials: list[PairObservation], condition: str) -> list[PaperReturn]:
    """Paper-only, 50% long/50% short on GROSS notional.

    The reversed signal is a CONTROL, not a researched trading candidate.
    """
    if condition == "qqq_lag_2pct":
        return [PaperReturn(t.day, .5 * t.intraday_qqq_minus_spy)
                for t in trials if t.prior_5session_qqq_minus_spy <= -RELATIVE_LAG_THRESHOLD]
    if condition == "qqq_lead_2pct_control":
        return [PaperReturn(t.day, -.5 * t.intraday_qqq_minus_spy)
                for t in trials if t.prior_5session_qqq_minus_spy >= RELATIVE_LAG_THRESHOLD]
    if condition == "all_days_control":
        return [PaperReturn(t.day, .5 * t.intraday_qqq_minus_spy)
                for t in trials]
    raise ValueError("Unknown predeclared pair condition.")


def evaluate(spy_bars: list[Bar], qqq_bars: list[Bar]) -> dict:
    trials = compute_pairs(spy_bars, qqq_bars)
    result = {
        "protocol": "FIXED_5SESSION_QQQ_UNDERPERFORMANCE_REVERSAL",
        "entry": "IDEALIZED_SAME_DAY_OPEN_PRINT",
        "exit": "IDEALIZED_SAME_DAY_CLOSE_PRINT",
        "gross_notional": "0.5_QQQ_LONG_0.5_SPY_SHORT",
        "status": "RESEARCH_ONLY_NO_EXECUTABLE_FILLS",
        "aligned_sessions": len(set(x.day for x in spy_bars) & set(x.day for x in qqq_bars)),
        "eligible_days": len(trials),
        "phases": {},
    }
    for label in ("train", "validation", "holdout"):
        cohort = [x for x in trials if phase(x.day) == label]
        result["phases"][label] = {"eligible_days": len(cohort)}
        for condition in ("qqq_lag_2pct", "qqq_lead_2pct_control", "all_days_control"):
            paper = select(cohort, condition)
            result["phases"][label][condition] = {
                "months": len({x.day.strftime("%Y-%m") for x in paper}),
                "cost_10bps": summary(paper, 10),
                "cost_20bps": summary(paper, 20, ci=(label == "holdout")),
                "cost_40bps": summary(paper, 40),
                "cost_80bps": summary(paper, 80),
            }
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--spy-file", required=True)
    p.add_argument("--qqq-file", required=True)
    p.add_argument("--spy-git-blob-sha", required=True)
    p.add_argument("--qqq-git-blob-sha", required=True)
    args = p.parse_args()
    result = evaluate(
        read_bars(__import__("pathlib").Path(args.spy_file), args.spy_git_blob_sha),
        read_bars(__import__("pathlib").Path(args.qqq_file), args.qqq_git_blob_sha),
    )
    result["input_blob_shas"] = {"SPY": args.spy_git_blob_sha, "QQQ": args.qqq_git_blob_sha}
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
