"""Bounded, read-only Tradier research cycle for personal market-data analysis.

The private API token is loaded solely from TRADIER_TOKEN in a protected-main job.
No account or trade endpoints. No persistent raw quotes or quotes in GitHub logs.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

import tradier_options_probe as probe

# Fixed research universe; not a recommendation or a historical winner list.
# ETFs provide comparators without single-company earnings announcements.
DEFAULT_SYMBOLS = (
    "SPY", "QQQ", "IWM", "TLT", "GLD", "XLF", "XLE", "SMH",
    "AAPL", "NVDA", "AMD", "MSFT", "BAC", "SOFI", "F", "PFE",
)
MAX_SYMBOLS = 20
CHUNK_SIZE = 5
TIMESALES_ETFS = ("SPY", "QQQ", "IWM")


def parse_symbols(raw: str) -> list[str]:
    values = list(dict.fromkeys(s.strip().upper() for s in raw.split(",")))
    if (not 1 <= len(values) <= MAX_SYMBOLS
        or any(not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", s) for s in values)):
        raise probe.ProbeFailure("Symbol universe must contain 1-20 valid unique tickers")
    return values


def market_state(token: str) -> str:
    payload = probe.get_json(token, "/markets/clock", {})
    clock = payload.get("clock")
    if not isinstance(clock, dict):
        raise probe.ProbeFailure("Market clock response missing state")
    state = clock.get("state")
    if state not in ("open", "closed", "premarket", "postmarket"):
        raise probe.ProbeFailure("Market clock returned unknown state")
    return state


def recent_bar_evidence(token: str, now: datetime, symbols: list[str]) -> dict:
    """Time & Sales only for underlying 1-minute context, never option fills."""
    eligible = [symbol for symbol in TIMESALES_ETFS if symbol in symbols]
    summary = {"symbols_requested": len(eligible), "symbols_with_bars": 0,
               "bars_observed": 0, "missing_or_invalid_bars": 0}
    et_end = now.astimezone(probe.EASTERN).replace(second=0, microsecond=0)
    et_start = et_end - timedelta(minutes=30)
    for symbol in eligible:
        payload = probe.get_json(token, "/markets/timesales", {
            "symbol": symbol, "interval": "1min",
            "start": et_start.strftime("%Y-%m-%d %H:%M"),
            "end": et_end.strftime("%Y-%m-%d %H:%M"),
            "session_filter": "open",
        })
        series = payload.get("series")
        bars = probe.many(series.get("data")) if isinstance(series, dict) else []
        n = 0
        for bar in bars:
            if not isinstance(bar, dict):
                summary["missing_or_invalid_bars"] += 1
                continue
            close = probe.positive(bar.get("close"))
            if close is None or not bar.get("time"):
                summary["missing_or_invalid_bars"] += 1
                continue
            n += 1
        if n:
            summary["symbols_with_bars"] += 1
            summary["bars_observed"] += n
    return summary


def run_cycle(token: str, symbols: list[str], now: datetime | None = None):
    """Closed markets cause an explicit SKIP, never a zero-trade edge verdict."""
    if not 1 <= len(symbols) <= MAX_SYMBOLS:
        raise probe.ProbeFailure("Symbol count exceeds bounded research universe")
    state = market_state(token)
    if state != "open":
        return [], {
            "status": "MARKET_CLOSED_SKIPPED",
            "market_state": state,
            "research_only": True,
            "read_only": True,
            "edge_status": "UNVERIFIED",
            "symbols_requested": len(symbols),
            "chains_requested": 0,
        }
    counts = {"0DTE": 0, "1DTE": 0, "7-21DTE": 0}
    spread_counts = {"bear_call": 0, "bull_put": 0}
    diagnostics: dict[str, int] = {}
    requested = 0
    observed = 0
    premium = 0
    all_rows = []
    for i in range(0, len(symbols), CHUNK_SIZE):
        # Live mode lets the probe use the actual clock on each received chain.
        # Explicit now remains available only for deterministic offline replay.
        rows, result = probe.run(symbols[i:i + CHUNK_SIZE], token, now=now)
        all_rows.extend(rows)
        requested += result["chains_requested"]
        observed += result["chains_with_contracts"]
        premium += result["iv_rv_ge_1_20_seven_to_21_dte"]
        for key, count in result["candidate_counts"].items():
            counts[key] += count
        for key, count in result["spread_counts"].items():
            spread_counts[key] += count
        for key, count in result["quote_filter_diagnostics"].items():
            diagnostics[key] = diagnostics.get(key, 0) + count
    # Time & Sales adds bounded, independent intraday equity-bar context.
    # It cannot be used to infer executable historical option bid-ask.
    intraday = recent_bar_evidence(
        token, now if now is not None else datetime.now(timezone.utc), symbols
    )
    return all_rows, {
        "status": "MARKET_DATA_ACCESS_VERIFIED",
        "market_state": "open",
        "research_only": True,
        "read_only": True,
        "edge_status": "UNVERIFIED",
        "symbols_requested": len(symbols),
        "chains_requested": requested,
        "chains_with_contracts": observed,
        "candidate_counts": counts,
        "spread_counts": spread_counts,
        "quote_filter_diagnostics": diagnostics,
        "iv_rv_ge_1_20_seven_to_21_dte": premium,
        "intraday_underlying_context": intraday,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded read-only Tradier options research")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--out", required=True, help="Ephemeral, private runner file only")
    args = parser.parse_args(argv)
    try:
        symbols = parse_symbols(args.symbols)
        token = os.getenv("TRADIER_TOKEN", "")
        if not token:
            raise probe.ProbeFailure("TRADIER_TOKEN missing from protected GitHub Actions secret")
        rows, summary = run_cycle(token, symbols)
        if summary["status"] == "MARKET_DATA_ACCESS_VERIFIED":
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=probe.HEADERS)
                writer.writeheader()
                writer.writerows(rows)
        print(json.dumps(summary, sort_keys=True))
        return 0
    except probe.ProbeFailure as exc:
        print("PROBE_FAILED: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
