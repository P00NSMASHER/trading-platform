"""Offline SPY trailing-range regime falsification using immutable CSV bytes.

Research only: no network, brokerage access, execution or fill claims.
The five completed sessions preceding T determine whether hypothetical
T open-to-close SPY exposure is included. All raw data stays local.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from equity_reversal_audit import InvalidPriceEvidence, git_blob_sha, phase, summary

LOOKBACK = 5
MAX_GAP_DAYS = 7
HIGH_RANGE_THRESHOLD = 0.02
QUIET_RANGE_THRESHOLD = 0.005
MAX_INTRADAY_ABS = 0.35
MAX_RANGE = 0.60
MAX_CSV_BYTES = 10_000_000
COSTS_BPS = (10, 20, 40)


@dataclass(frozen=True)
class RangeBar:
    day: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class RangeTrial:
    day: date
    prior_mean_range: float
    intraday_return: float


@dataclass(frozen=True)
class PaperReturn:
    day: date
    intraday_return: float


def read_range_bars(path: Path, expected_blob_sha: str) -> list[RangeBar]:
    """Retain high/low (unlike the close-based adapter) with byte pinning."""
    if not re.fullmatch(r"[a-f0-9]{40}", expected_blob_sha):
        raise InvalidPriceEvidence("Expected full lower-case Git blob SHA-1.")
    if path.stat().st_size > MAX_CSV_BYTES:
        raise InvalidPriceEvidence("Historical CSV exceeds bounded input size.")
    payload = path.read_bytes()
    if len(payload) > MAX_CSV_BYTES or git_blob_sha(payload) != expected_blob_sha:
        raise InvalidPriceEvidence("Git blob hash mismatch or oversized input.")
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
        required = {"Date", "Open", "High", "Low", "Close"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise InvalidPriceEvidence("Missing source OHLC fields.")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise InvalidPriceEvidence("Duplicate source column.")
        bars: list[RangeBar] = []
        for row in reader:
            if None in row or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["Date"] or ""):
                raise InvalidPriceEvidence("Malformed source CSV date or row.")
            bars.append(RangeBar(date.fromisoformat(row["Date"]),
                                 float(row["Open"]), float(row["High"]),
                                 float(row["Low"]), float(row["Close"])))
    except (csv.Error, UnicodeError, ValueError, TypeError, OverflowError) as exc:
        if isinstance(exc, InvalidPriceEvidence):
            raise
        raise InvalidPriceEvidence("Unparseable source CSV.") from exc
    return bars


def compute_trials(bars: list[RangeBar]) -> list[RangeTrial]:
    """Reject inconsistent bars and never use today's range in its signal."""
    if len(bars) <= LOOKBACK:
        raise InvalidPriceEvidence("Need at least six ordered sessions.")
    for i, bar in enumerate(bars):
        if i and bar.day <= bars[i - 1].day:
            raise InvalidPriceEvidence("Duplicate or unordered session.")
        if bar.day.weekday() >= 5:
            raise InvalidPriceEvidence("Weekend equity session is invalid.")
        if not all(math.isfinite(v) and v > 0 for v in
                   (bar.open, bar.high, bar.low, bar.close)):
            raise InvalidPriceEvidence("Nonfinite or nonpositive OHLC.")
        if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
            raise InvalidPriceEvidence("Impossible OHLC bounds.")
        if ((bar.high - bar.low) / bar.open > MAX_RANGE or
                abs(bar.close / bar.open - 1) > MAX_INTRADAY_ABS):
            raise InvalidPriceEvidence("Extreme range or intraday move requires review.")
    out = []
    for i in range(LOOKBACK, len(bars)):
        window = bars[i - LOOKBACK:i + 1]
        if any((right.day - left.day).days > MAX_GAP_DAYS
               for left, right in zip(window, window[1:])):
            continue
        previous_range = sum((x.high - x.low) / x.open for x in window[:-1]) / LOOKBACK
        out.append(RangeTrial(bars[i].day, previous_range,
                              bars[i].close / bars[i].open - 1))
    return out


def select(trials: list[RangeTrial], arm: str) -> list[PaperReturn]:
    if arm == "prior_high_range_long":
        return [PaperReturn(t.day, t.intraday_return) for t in trials
                if t.prior_mean_range >= HIGH_RANGE_THRESHOLD]
    if arm == "prior_quiet_range_long_control":
        return [PaperReturn(t.day, t.intraday_return) for t in trials
                if t.prior_mean_range <= QUIET_RANGE_THRESHOLD]
    raise ValueError("Unregistered range-regime arm.")


def evaluate(bars: list[RangeBar]) -> dict:
    trials = compute_trials(bars)
    result = {
        "protocol": "SPY_PREVIOUS_5_COMPLETED_SESSION_MEAN_RANGE_GE_2PCT",
        "research_status": "EXPLORATORY_REJECT_VERIFIED_EXECUTABLE_EDGE",
        "entry": "IDEALIZED_OFFICIAL_OPEN_NOT_EXECUTABLE_FILL",
        "exit": "IDEALIZED_OFFICIAL_CLOSE_NOT_EXECUTABLE_FILL",
        "cost_units": "gross_SPY_notional_roundtrip_bps",
        "input_bars": len(bars), "eligible_sessions": len(trials), "phases": {},
    }
    for name in ("train", "validation", "holdout"):
        cohort = [t for t in trials if phase(t.day) == name]
        section = {"eligible_sessions": len(cohort)}
        for arm in ("prior_high_range_long", "prior_quiet_range_long_control"):
            selected = select(cohort, arm)
            section[arm] = {
                "months": len({t.day.strftime("%Y-%m") for t in selected}),
                **{f"cost_{cost}bps": summary(selected, cost,
                   ci=(cost == 20 and name in ("validation", "holdout")))
                   for cost in COSTS_BPS},
            }
        result["phases"][name] = section
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--git-blob-sha", required=True)
    args = parser.parse_args()
    result = evaluate(read_range_bars(args.file, args.git_blob_sha))
    result["symbol"] = "SPY"
    result["immutable_input_blob_sha1"] = args.git_blob_sha
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
