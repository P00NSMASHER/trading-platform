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
    diagnostics_by_dte = {label: {} for label in counts}
    pair_funnel: dict[str, int] = {}
    pair_funnel_by_dte = {label: {} for label in counts}
    requested = 0
    observed = 0
    premium = 0
    h1_greeks_quality: dict[str, int] = {}
    proxy_totals = {
        "chains_primary_window": 0,
        "chains_with_paired_atm_quotes_and_rv20": 0,
        "chains_without_usable_paired_quote_or_rv20": 0,
        "chains_straddle_bid_ratio_above_1_20": 0,
        "chains_straddle_ask_ratio_below_0_80": 0,
        "model_is_not_profit_or_implied_vol": True,
    }
    best_case_feasibility = {
        label: {"after_fees_positive": 0,
                "after_fees_and_5_slippage_positive": 0,
                "after_fees_and_10_slippage_positive": 0}
        for label in counts
    }
    h1_chains = 0
    h1_symbols = 0
    h1_signal_sides = {"bear_call": 0, "bull_put": 0}
    atm_stats = {"chains_primary_window": 0,
                 "chains_with_two_sided_atm_iv": 0,
                 "chains_missing_atm_iv": 0,
                 "chains_with_completed_rv20": 0,
                 "candidate_spreads_with_complete_atm_signal": 0}
    all_rows = []
    for i in range(0, len(symbols), CHUNK_SIZE):
        # Live mode lets the probe use the actual clock on each received chain.
        # Explicit now remains available only for deterministic offline replay.
        rows, result = probe.run(symbols[i:i + CHUNK_SIZE], token, now=now)
        all_rows.extend(rows)
        requested += result["chains_requested"]
        observed += result["chains_with_contracts"]
        premium += result["iv_rv_ge_1_20_seven_to_21_dte"]
        proxy_data = result.get("greeks_independent_straddle_move_proxy", {})
        for key, value in proxy_data.items():
            if key == "model_is_not_profit_or_implied_vol":
                if value is not True:
                    raise probe.ProbeFailure("Model-free screen must deny profit inference")
                continue
            if key not in proxy_totals or not isinstance(value, int) or value < 0:
                raise probe.ProbeFailure("Invalid model-free straddle proxy count")
            proxy_totals[key] += value
        for key, n in result.get("h1_greeks_quality", {}).items():
            if (key not in probe.atm_greeks_quality(
                    {}, symbol="", spot=1.0, now=(now or datetime.now(timezone.utc)))
                or not isinstance(n, int) or n < 0):
                raise probe.ProbeFailure("Invalid Greek-quality aggregate receipt")
            h1_greeks_quality[key] = h1_greeks_quality.get(key, 0) + n
        for label, stages in result.get("best_case_payoff_feasibility_by_dte", {}).items():
            if label not in best_case_feasibility or not isinstance(stages, dict):
                raise probe.ProbeFailure("Invalid payoff-feasibility expiry bucket")
            for key, n in stages.items():
                if key not in best_case_feasibility[label] or not isinstance(n, int) or n < 0:
                    raise probe.ProbeFailure("Invalid payoff-feasibility aggregate count")
                best_case_feasibility[label][key] += n
        h1_chain_count = result.get("h1_qualifying_chains", 0)
        h1_symbol_count = result.get("h1_qualifying_symbols", 0)
        if (not isinstance(h1_chain_count, int) or h1_chain_count < 0
            or not isinstance(h1_symbol_count, int) or h1_symbol_count < 0
            or h1_symbol_count > len(symbols[i:i + CHUNK_SIZE])
            or h1_symbol_count > h1_chain_count):
            raise probe.ProbeFailure("Invalid H1 independent coverage receipt")
        if h1_chain_count > result["chains_requested"]:
            raise probe.ProbeFailure("H1 chain count exceeds scanned chains")
        h1_chains += h1_chain_count
        h1_symbols += h1_symbol_count  # symbol batches are disjoint by validation
        for side, count in result.get("h1_signal_spread_sides", {}).items():
            if side not in h1_signal_sides or not isinstance(count, int) or count < 0:
                raise probe.ProbeFailure("Invalid H1 spread side count")
            h1_signal_sides[side] += count
        for key, count in result.get("atm_iv_coverage", {}).items():
            if key not in atm_stats or not isinstance(count, int) or count < 0:
                raise probe.ProbeFailure("Unexpected primary-window IV coverage receipt")
            atm_stats[key] += count
        for key, count in result["candidate_counts"].items():
            counts[key] += count
        for key, count in result["spread_counts"].items():
            spread_counts[key] += count
        for key, count in result["quote_filter_diagnostics"].items():
            diagnostics[key] = diagnostics.get(key, 0) + count
        for label, stages in result.get("quote_filter_by_dte", {}).items():
            if label not in diagnostics_by_dte:
                raise probe.ProbeFailure("Unexpected expiry bucket in quote diagnostics")
            for key, count in stages.items():
                totals = diagnostics_by_dte[label]
                totals[key] = totals.get(key, 0) + count
        for key, count in result.get("spread_pair_funnel", {}).items():
            pair_funnel[key] = pair_funnel.get(key, 0) + count
        for label, stages in result.get("spread_pair_funnel_by_dte", {}).items():
            if label not in pair_funnel_by_dte:
                raise probe.ProbeFailure("Unexpected expiry bucket in spread diagnostics")
            for key, count in stages.items():
                totals = pair_funnel_by_dte[label]
                totals[key] = totals.get(key, 0) + count
    # Time & Sales adds bounded, independent intraday equity-bar context.
    # It cannot be used to infer executable historical option bid-ask.
    intraday = recent_bar_evidence(
        token, now if now is not None else datetime.now(timezone.utc), symbols
    )
    if (sum(h1_signal_sides.values()) != premium
        or h1_chains > premium or h1_symbols > h1_chains):
        raise probe.ProbeFailure("H1 nonindependent-count receipt parity failed")
    if (proxy_totals["chains_primary_window"] !=
        proxy_totals["chains_with_paired_atm_quotes_and_rv20"] +
        proxy_totals["chains_without_usable_paired_quote_or_rv20"] or
        proxy_totals["chains_straddle_bid_ratio_above_1_20"] >
            proxy_totals["chains_with_paired_atm_quotes_and_rv20"] or
        proxy_totals["chains_straddle_ask_ratio_below_0_80"] >
            proxy_totals["chains_with_paired_atm_quotes_and_rv20"]):
        raise probe.ProbeFailure("Model-free straddle proxy chain coverage parity failed")
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
        "quote_filter_by_dte": diagnostics_by_dte,
        "spread_pair_funnel": pair_funnel,
        "spread_pair_funnel_by_dte": pair_funnel_by_dte,
        "iv_rv_ge_1_20_seven_to_21_dte": premium,
        "h1_qualifying_chains": h1_chains,
        "h1_qualifying_symbols": h1_symbols,
        "h1_signal_spread_sides": h1_signal_sides,
        "atm_iv_coverage": atm_stats,
        "h1_greeks_quality": h1_greeks_quality,
        "greeks_independent_straddle_move_proxy": proxy_totals,
        "best_case_payoff_feasibility_by_dte": best_case_feasibility,
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
