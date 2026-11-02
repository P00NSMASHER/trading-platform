"""Offline, source-pinned ETF next-session reversal falsification audit.

Research only. No API, brokerage access, data download, orders or fills.
Every input must be a locally supplied, immutable Git-blob-pinned CSV.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class InvalidPriceEvidence(ValueError):
    """Missing, corrupted, or ambiguous historical price source."""


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    close: float
    adjusted_close: float


@dataclass(frozen=True)
class Trial:
    day: date
    previous_daily_return: float
    intraday_return: float


def git_blob_sha(content: bytes) -> str:
    """Calculate the same SHA-1 blob identifier used by GitHub."""
    return hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()


def read_bars(path: Path, expected_blob_sha: str) -> list[Bar]:
    """Read raw CSV bytes only when the supplied Git blob identity matches."""
    if not re.fullmatch(r"[0-9a-f]{40}", expected_blob_sha):
        raise InvalidPriceEvidence("Expected a full 40-character Git blob SHA.")
    payload = path.read_bytes()
    if git_blob_sha(payload) != expected_blob_sha:
        raise InvalidPriceEvidence("Git blob hash mismatch: refuse mutable evidence.")
    try:
        decoded = payload.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(decoded, newline=""))
        required = {"Date", "Open", "High", "Low", "Close"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise InvalidPriceEvidence("Missing mandatory OHLC columns.")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise InvalidPriceEvidence("Duplicate CSV column.")
        bars: list[Bar] = []
        for row in reader:
            if None in row or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["Date"] or ""):
                raise InvalidPriceEvidence("Malformed CSV row/date.")
            day = date.fromisoformat(row["Date"])
            op = float(row["Open"])
            hi = float(row["High"])
            lo = float(row["Low"])
            cl = float(row["Close"])
            adj = float(row["Adj Close"]) if "Adj Close" in row else cl
            if not all(math.isfinite(x) and x > 0 for x in (op, hi, lo, cl, adj)):
                raise InvalidPriceEvidence("Non-positive/nonfinite OHLC or adjusted close.")
            if lo > min(op, cl) or hi < max(op, cl) or hi < lo:
                raise InvalidPriceEvidence("Impossible OHLC bounds.")
            if bars and day <= bars[-1].day:
                raise InvalidPriceEvidence("CSV is unsorted or has duplicate dates.")
            bars.append(Bar(day, op, cl, adj))
    except (UnicodeError, KeyError, TypeError, OverflowError, ValueError) as exc:
        if isinstance(exc, InvalidPriceEvidence):
            raise
        raise InvalidPriceEvidence("Unparseable historical CSV.") from exc
    if len(bars) < 3:
        raise InvalidPriceEvidence("Need at least three ordered sessions.")
    return bars


def compute_trials(bars: list[Bar]) -> list[Trial]:
    """Yesterday's fully known close-to-close return predicts today's OPEN->CLOSE.

    IMPORTANT: Do not use today's close in the entry signal, infer an open
    execution from a same-day open gap, or silently drop losing sessions.
    """
    out: list[Trial] = []
    for i in range(2, len(bars)):
        signal = bars[i - 1].adjusted_close / bars[i - 2].adjusted_close - 1
        intraday = bars[i].close / bars[i].open - 1
        if abs(intraday) > 0.35:
            raise InvalidPriceEvidence("Unusually large intraday move: verify adjustments.")
        out.append(Trial(bars[i].day, signal, intraday))
    return out


def phase(day: date) -> str:
    if day < date(2013, 1, 1):
        return "train"
    if day < date(2019, 1, 1):
        return "validation"
    return "holdout"


def select(trials: list[Trial], condition: str) -> list[Trial]:
    if condition == "prior_down_1pct":
        return [x for x in trials if x.previous_daily_return <= -0.01]
    if condition == "prior_up_1pct":
        return [x for x in trials if x.previous_daily_return >= 0.01]
    if condition == "every_day":
        return list(trials)
    raise ValueError("Unknown pre-registered strategy.")


def block_confidence_interval(trials: list[Trial], cost_bps: float, seed: int = 102391,
                              replicates: int = 1500) -> list[float] | None:
    """Cluster bootstrap by entry month, preserving clustered trade outcomes."""
    months: dict[str, list[float]] = defaultdict(list)
    for t in trials:
        months[t.day.strftime("%Y-%m")].append(10000 * t.intraday_return - cost_bps)
    clusters = list(months.values())
    if len(clusters) < 5:
        return None
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(replicates):
        sample = [clusters[rng.randrange(len(clusters))] for __ in clusters]
        draws.append(sum(sum(cluster) for cluster in sample) / sum(map(len, sample)))
    draws.sort()
    return [round(draws[int(0.025 * (len(draws) - 1))], 3),
            round(draws[int(0.975 * (len(draws) - 1))], 3)]


def summary(trials: list[Trial], cost_bps: float, ci: bool = False) -> dict:
    net_bps = [10000 * x.intraday_return - cost_bps for x in trials]
    if not net_bps:
        return {"trades": 0, "mean_net_bps": None, "ci95_month_cluster_bps": None}
    mean = sum(net_bps) / len(net_bps)
    out = {
        "trades": len(trials),
        "mean_gross_bps": round(mean + cost_bps, 3),
        "mean_net_bps": round(mean, 3),
        "win_pct_net": round(100 * sum(x > 0 for x in net_bps) / len(net_bps), 2),
    }
    if ci:
        out["ci95_month_cluster_bps"] = block_confidence_interval(trials, cost_bps)
    return out


def evaluate(bars: list[Bar]) -> dict:
    trials = compute_trials(bars)
    result = {"bars": len(bars), "first": bars[0].day.isoformat(),
              "last": bars[-1].day.isoformat(), "phases": {}}
    for p in ("train", "validation", "holdout"):
        cohort = [x for x in trials if phase(x.day) == p]
        result["phases"][p] = {}
        for key in ("prior_down_1pct", "prior_up_1pct", "every_day"):
            matched = select(cohort, key)
            result["phases"][p][key] = {
                "cost_10bps": summary(matched, 10, ci=(p == "holdout" and key == "prior_down_1pct")),
                "cost_30bps": summary(matched, 30),
                "cost_50bps": summary(matched, 50),
            }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True, help="Locally supplied CSV, never network-fetched")
    parser.add_argument("--git-blob-sha", required=True, help="Expected SHA-1 Git BLOB, not a branch name")
    parser.add_argument("--symbol", required=True, help="Human-readable research label")
    args = parser.parse_args()
    output = evaluate(read_bars(args.file, args.git_blob_sha))
    output["symbol"] = args.symbol
    output["research_status"] = "HYPOTHESIS_ONLY_NO_EXECUTION_OR_PROFIT_CLAIM"
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
