"""Compare pinned SPY price archives without mistaking scaled prices for replications.

Offline research QA only. No orders, broker access, raw bars embedded or vendored.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

MAX_BYTES = 10_000_000
MAX_ROWS = 100_000
THRESHOLD = 0.01
COST_BPS = 20


class InvalidArchive(ValueError):
    """A source is not suitable for a traceable market-data comparison."""


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float


def git_blob_id(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def load_bars(path: Path, expected_git_blob: str) -> list[Bar]:
    """Accept only source-identical, bounded, ordered, well-formed OHLC CSV."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected_git_blob):
        raise InvalidArchive("Expected complete lowercase Git blob SHA-1")
    if path.stat().st_size > MAX_BYTES:
        raise InvalidArchive("Source exceeds byte limit")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES or git_blob_id(raw) != expected_git_blob:
        raise InvalidArchive("Source bytes do not match pinned Git blob")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        keys = reader.fieldnames
        if not keys or len(keys) != len(set(keys)) or not {"Date", "Open", "High", "Low", "Close"}.issubset(keys):
            raise InvalidArchive("Missing or duplicate OHLC fields")
        bars: list[Bar] = []
        for row in reader:
            if len(bars) >= MAX_ROWS or None in row or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["Date"] or ""):
                raise InvalidArchive("Malformed row, date or row count")
            b = Bar(date.fromisoformat(row["Date"]), *(float(row[key]) for key in ("Open", "High", "Low", "Close")))
            if b.day.weekday() >= 5 or (bars and b.day <= bars[-1].day):
                raise InvalidArchive("Duplicate, unordered or weekend session")
            if not all(math.isfinite(v) and v > 0 for v in (b.open, b.high, b.low, b.close)):
                raise InvalidArchive("Nonpositive or nonfinite OHLC")
            if b.low > min(b.open, b.close) or b.high < max(b.open, b.close):
                raise InvalidArchive("Impossible OHLC bounds")
            bars.append(b)
    except (UnicodeError, ValueError, TypeError, OverflowError, csv.Error) as exc:
        if isinstance(exc, InvalidArchive):
            raise
        raise InvalidArchive("Unparseable archived OHLC source") from exc
    if len(bars) < 3:
        raise InvalidArchive("Need at least three sessions")
    return bars


def phase(day: date) -> str:
    return "train" if day < date(2013, 1, 1) else "validation" if day < date(2019, 1, 1) else "retrospective"


def compare_archives(primary: list[Bar], secondary: list[Bar]) -> dict:
    """Count contradictory T-1 gap signals on the identical shared calendar.

    Unlike a strategy backtest this reports source disagreement, not alpha.
    A long signal is prior-day open / older close - 1 >= +1%; diagnostic
    short control is <= -1%. Today's intraday return is never a signal.
    """
    if len(primary) < 3 or len(secondary) < 3:
        raise InvalidArchive("Need at least three sessions in each source")
    for bars in (primary, secondary):
        for i, b in enumerate(bars):
            if i and b.day <= bars[i - 1].day:
                raise InvalidArchive("Duplicate or unordered session")
            if b.day.weekday() >= 5 or not all(math.isfinite(v) and v > 0 for v in (b.open, b.high, b.low, b.close)):
                raise InvalidArchive("Invalid OHLC session")
            if b.low > min(b.open, b.close) or b.high < max(b.open, b.close):
                raise InvalidArchive("Impossible OHLC bounds")
    first = max(primary[0].day, secondary[0].day)
    last = min(primary[-1].day, secondary[-1].day)
    x = [b for b in primary if first <= b.day <= last]
    y = [b for b in secondary if first <= b.day <= last]
    if len(x) < 3 or [b.day for b in x] != [b.day for b in y]:
        raise InvalidArchive("Missing or mismatched overlapping calendar; cannot align")

    output = {"shared_sessions": len(x), "first": first.isoformat(), "last": last.isoformat(),
              "raw_close_ratio_first": round(y[0].close / x[0].close, 9),
              "raw_close_ratio_last": round(y[-1].close / x[-1].close, 9),
              "max_intraday_difference_bps": 0.0,
              "max_overnight_gap_difference_bps": 0.0,
              "overnight_gap_difference_over_5bps": 0, "signal_conflicts": [], "phases": {}}
    for name in ("train", "validation", "retrospective"):
        output["phases"][name] = {side: {"eligible": 0, "primary": 0, "secondary": 0,
                                          "both": 0, "primary_only": 0, "secondary_only": 0,
                                          "primary_net_bps_sum": 0.0, "secondary_net_bps_sum": 0.0}
                                  for side in ("long", "short_control")}
    for i in range(len(x)):
        dx = abs((x[i].close / x[i].open - y[i].close / y[i].open) * 10_000)
        output["max_intraday_difference_bps"] = max(output["max_intraday_difference_bps"], dx)
        if i:
            ax = x[i].open / x[i - 1].close - 1
            ay = y[i].open / y[i - 1].close - 1
            diff = abs((ax - ay) * 10_000)
            output["max_overnight_gap_difference_bps"] = max(output["max_overnight_gap_difference_bps"], diff)
            if diff > 5:
                output["overnight_gap_difference_over_5bps"] += 1
        if i < 2:
            continue
        if any((x[j].day - x[j - 1].day).days > 7 for j in (i - 1, i)):
            continue
        a = x[i - 1].open / x[i - 2].close - 1
        b = y[i - 1].open / y[i - 2].close - 1
        for side, match in (("long", lambda r: r >= THRESHOLD),
                            ("short_control", lambda r: r <= -THRESHOLD)):
            xa, ya = match(a), match(b)
            s = output["phases"][phase(x[i].day)][side]
            s["eligible"] += 1
            s["primary"] += int(xa)
            s["secondary"] += int(ya)
            s["both"] += int(xa and ya)
            s["primary_only"] += int(xa and not ya)
            s["secondary_only"] += int(ya and not xa)
            direction = 1 if side == "long" else -1
            if xa:
                s["primary_net_bps_sum"] += direction * (x[i].close / x[i].open - 1) * 10000 - COST_BPS
            if ya:
                s["secondary_net_bps_sum"] += direction * (y[i].close / y[i].open - 1) * 10000 - COST_BPS
            if xa != ya:
                output["signal_conflicts"].append({"entry_day": x[i].day.isoformat(),
                                                    "signal_day": x[i - 1].day.isoformat(),
                                                    "side": side, "primary_gap_bps": round(10000 * a, 3),
                                                    "secondary_gap_bps": round(10000 * b, 3)})
    for by_phase in output["phases"].values():
        for s in by_phase.values():
            a, b = s.pop("primary_net_bps_sum"), s.pop("secondary_net_bps_sum")
            s["primary_mean_net_20bps"] = round(a / s["primary"], 3) if s["primary"] else None
            s["secondary_mean_net_20bps"] = round(b / s["secondary"], 3) if s["secondary"] else None
    for key in ("max_intraday_difference_bps", "max_overnight_gap_difference_bps"):
        output[key] = round(output[key], 6)
    output["status"] = "SOURCE_PROVENANCE_DIAGNOSTIC_NOT_INDEPENDENT_VALIDATION_OR_PROFIT"
    return output


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--primary", type=Path, required=True)
    p.add_argument("--primary-blob", required=True)
    p.add_argument("--secondary", type=Path, required=True)
    p.add_argument("--secondary-blob", required=True)
    args = p.parse_args()
    print(json.dumps(compare_archives(load_bars(args.primary, args.primary_blob),
                                      load_bars(args.secondary, args.secondary_blob)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
