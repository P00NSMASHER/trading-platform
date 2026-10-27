"""Read-only Tradier options-chain observer. Never accesses accounts or submits orders.

The outputs are quotes/candidate observations, NOT predictive signals or verified profits.
Keep raw results off public repositories and artifacts.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

BASE = "https://api.tradier.com/v1"
ALLOWED = frozenset(("/markets/quotes", "/markets/options/expirations",
                     "/markets/options/chains", "/markets/history",
                     "/markets/clock", "/markets/timesales"))
EASTERN = ZoneInfo("America/New_York")
HEADERS = ("observed_at_utc", "underlying", "bucket", "expiration", "dte", "spread_side",
           "spot", "short_contract", "long_contract", "short_strike", "long_strike",
           "short_bid", "long_ask", "credit_per_share", "risk_estimate_usd",
           "fees_assumed_usd", "short_iv", "rv20", "iv_rv_ratio",
           "quote_age_seconds", "research_only")
_last_request = 0.0


class ProbeFailure(RuntimeError):
    """Sanitized failure with no secrets or provider response content."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeFailure("Provider attempted redirect; request refused")


def get_json(token, endpoint, params):
    """Only six explicit HTTPS market-data GET routes; rejects all redirects."""
    global _last_request
    if endpoint not in ALLOWED:
        raise ProbeFailure("Denied: endpoint is not an allowed market-data route")
    if not token or not token.strip():
        raise ProbeFailure("TRADIER_TOKEN is missing; check repository Actions secret")
    elapsed = time.monotonic() - _last_request
    if _last_request and elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_request = time.monotonic()
    req = Request(BASE + endpoint + "?" + urlencode(params), method="GET",
                  headers={"Authorization": "Bearer " + token.strip(),
                           "Accept": "application/json"})
    try:
        with build_opener(_NoRedirects).open(req, timeout=20) as response:
            payload = json.load(response)
    except HTTPError as err:
        if err.code == 401:
            raise ProbeFailure("Tradier rejected authentication (HTTP 401)") from None
        if err.code == 403:
            raise ProbeFailure("Tradier rejected access (HTTP 403)") from None
        if err.code == 400:
            raise ProbeFailure("Tradier rejected request (HTTP 400: parameters or quota)") from None
        raise ProbeFailure("Tradier returned HTTP " + str(err.code)) from None
    except (URLError, TimeoutError, OSError):
        raise ProbeFailure("Tradier HTTPS connection failed") from None
    except (ValueError, TypeError):
        raise ProbeFailure("Tradier returned malformed JSON") from None
    if not isinstance(payload, dict):
        raise ProbeFailure("Tradier JSON response was not an object")
    return payload


def many(value):
    return value if isinstance(value, list) else ([] if value is None else [value])


def positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError):
        return None


def nonnegative_int(value):
    try:
        number = int(value)
        return number if number >= 0 else 0
    except (ValueError, TypeError):
        return 0


def bucket(dte):
    if dte == 0:
        return "0DTE"
    if dte == 1:
        return "1DTE"
    return "7-21DTE" if 7 <= dte <= 21 else None


def expiry_dates(payload):
    node = payload.get("expirations") or {}
    if not isinstance(node, dict):
        return []
    result = set()
    for item in many(node.get("expiration", node.get("date"))):
        raw = item.get("date") if isinstance(item, dict) else item
        try:
            datetime.strptime(raw, "%Y-%m-%d")
            result.add(raw)
        except (ValueError, TypeError):
            continue
    return sorted(result)


def _epoch_seconds(value):
    """Tradier market-data timestamps may be UNIX seconds or milliseconds.

    Ambiguous, zero, future-nonsensical and microsecond timestamps fail closed.
    """
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(numeric):
        return None
    if 1_000_000_000 <= numeric < 100_000_000_000:
        return numeric
    if 1_000_000_000_000 <= numeric < 100_000_000_000_000:
        return numeric / 1000
    return None


def quote_age(option, now):
    bid = _epoch_seconds(option.get("bid_date"))
    ask = _epoch_seconds(option.get("ask_date"))
    if bid is None or ask is None or max(bid, ask) > now.timestamp() + 60:
        return None
    return round(max(0.0, now.timestamp() - min(bid, ask)), 1)


def option_iv(option):
    greeks = option.get("greeks") or {}
    iv = positive(greeks.get("mid_iv")) if isinstance(greeks, dict) else None
    if iv is None:
        return None
    if iv > 2:
        iv /= 100
    return round(iv, 5) if 0 < iv < 3 else None


def realized_vol20(payload):
    history = payload.get("history") or {}
    if not isinstance(history, dict):
        return None
    days = sorted((row for row in many(history.get("day"))
                   if isinstance(row, dict)), key=lambda row: row.get("date", ""))
    closes = [positive(row.get("close")) for row in days[-21:]]
    if len(closes) != 21 or any(v is None for v in closes):
        return None
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, 21)]
    return round(statistics.stdev(returns) * math.sqrt(252), 5)


def spot_quote(payload):
    quotes = payload.get("quotes") or {}
    if not isinstance(quotes, dict):
        return None
    q = many(quotes.get("quote"))
    if not q or not isinstance(q[0], dict):
        return None
    bid, ask = positive(q[0].get("bid")), positive(q[0].get("ask"))
    return round((bid + ask) / 2, 4) if bid and ask and ask >= bid else None


def candidates(chain, *, symbol, spot, expiry, now, rv20,
               max_risk=100.0, max_quote_age=120, max_spread=0.25,
               min_open_interest=100, fee_per_side=0.65):
    """Out-of-the-money defined-width call credit verticals, conservatively marked."""
    dte = (datetime.strptime(expiry, "%Y-%m-%d").date()
           - now.astimezone(EASTERN).date()).days
    label = bucket(dte)
    if label is None or positive(spot) is None:
        return []
    node = chain.get("options") or {}
    options = many(node.get("option")) if isinstance(node, dict) else []
    calls = []
    for item in options:
        if not isinstance(item, dict) or item.get("option_type") != "call":
            continue
        if (nonnegative_int(item.get("contract_size")) != 100
            or item.get("root_symbol") != symbol):
            continue  # reject unknown/adjusted contracts and alternate delivery roots
        strike = positive(item.get("strike"))
        bid, ask = positive(item.get("bid")), positive(item.get("ask"))
        age = quote_age(item, now)
        if (strike is None or bid is None or ask is None or ask < bid
            or (ask - bid) / ((ask + bid) / 2) > max_spread
            or age is None or age > max_quote_age
            or nonnegative_int(item.get("open_interest")) < min_open_interest):
            continue
        calls.append((strike, age, item))
    calls.sort(key=lambda x: x[0])
    result = []
    for i, (short_strike, short_age, short) in enumerate(calls):
        if short_strike <= spot:
            continue
        for long_strike, long_age, long in calls[i + 1:]:
            width = round(long_strike - short_strike, 3)
            if width <= 0:
                continue
            if width > 3:
                break
            credit = round(float(short["bid"]) - float(long["ask"]), 4)
            if credit <= 0 or credit >= width:
                continue
            fees = 4 * fee_per_side  # two legs at entry and at exit, illustrative
            risk = round((width - credit) * 100 + fees, 2)
            if risk > max_risk:
                continue
            iv = option_iv(short)
            result.append({"spread_side": "bear_call",
                "observed_at_utc": now.isoformat(), "underlying": symbol,
                "bucket": label, "expiration": expiry, "dte": dte,
                "spot": spot, "short_contract": short.get("symbol"),
                "long_contract": long.get("symbol"),
                "short_strike": short_strike, "long_strike": long_strike,
                "short_bid": short["bid"], "long_ask": long["ask"],
                "credit_per_share": credit, "risk_estimate_usd": risk,
                "fees_assumed_usd": round(fees, 2), "short_iv": iv,
                "rv20": rv20, "iv_rv_ratio": (round(iv / rv20, 3)
                                                 if iv and rv20 and rv20 > 0 else None),
                "quote_age_seconds": max(short_age, long_age),
                "research_only": True,
            })
    return result


def put_candidates(chain, *, symbol, spot, expiry, now, rv20,
               max_risk=100.0, max_quote_age=120, max_spread=0.25,
               min_open_interest=100, fee_per_side=0.65):
    """Out-of-the-money defined-width put credit verticals, conservatively marked."""
    dte = (datetime.strptime(expiry, "%Y-%m-%d").date()
           - now.astimezone(EASTERN).date()).days
    label = bucket(dte)
    if label is None or positive(spot) is None:
        return []
    node = chain.get("options") or {}
    options = many(node.get("option")) if isinstance(node, dict) else []
    puts = []
    for item in options:
        if not isinstance(item, dict) or item.get("option_type") != "put":
            continue
        if (nonnegative_int(item.get("contract_size")) != 100
            or item.get("root_symbol") != symbol):
            continue  # reject unknown/adjusted contracts and alternate delivery roots
        strike = positive(item.get("strike"))
        bid, ask = positive(item.get("bid")), positive(item.get("ask"))
        age = quote_age(item, now)
        if (strike is None or bid is None or ask is None or ask < bid
            or (ask - bid) / ((ask + bid) / 2) > max_spread
            or age is None or age > max_quote_age
            or nonnegative_int(item.get("open_interest")) < min_open_interest):
            continue
        puts.append((strike, age, item))
    puts.sort(key=lambda x: -x[0])
    result = []
    for i, (short_strike, short_age, short) in enumerate(puts):
        if short_strike >= spot:
            continue
        for long_strike, long_age, long in puts[i + 1:]:
            width = round(short_strike - long_strike, 3)
            if width <= 0:
                continue
            if width > 3:
                break
            credit = round(float(short["bid"]) - float(long["ask"]), 4)
            if credit <= 0 or credit >= width:
                continue
            fees = 4 * fee_per_side  # two legs at entry and at exit, illustrative
            risk = round((width - credit) * 100 + fees, 2)
            if risk > max_risk:
                continue
            iv = option_iv(short)
            result.append({"spread_side": "bull_put",
                "observed_at_utc": now.isoformat(), "underlying": symbol,
                "bucket": label, "expiration": expiry, "dte": dte,
                "spot": spot, "short_contract": short.get("symbol"),
                "long_contract": long.get("symbol"),
                "short_strike": short_strike, "long_strike": long_strike,
                "short_bid": short["bid"], "long_ask": long["ask"],
                "credit_per_share": credit, "risk_estimate_usd": risk,
                "fees_assumed_usd": round(fees, 2), "short_iv": iv,
                "rv20": rv20, "iv_rv_ratio": (round(iv / rv20, 3)
                                                 if iv and rv20 and rv20 > 0 else None),
                "quote_age_seconds": max(short_age, long_age),
                "research_only": True,
            })
    return result



def diagnose_chain(chain, symbol, spot, now, max_quote_age=120):
    """Aggregate why quotes fail. Logs NEVER contain strike, symbol, or prices."""
    node = chain.get("options") or {}
    rows = many(node.get("option")) if isinstance(node, dict) else []
    stages = {
        "raw_option_rows": 0, "call_or_put_rows": 0,
        "unknown_or_adjusted_contract": 0, "invalid_market": 0,
        "stale_or_missing_quote_time": 0, "low_open_interest": 0,
        "wide_quoted_market": 0, "not_out_of_money": 0,
        "otm_liquid_legs": 0,
        "quotes_with_millisecond_timestamps": 0,
        "quotes_with_second_timestamps": 0,
    }
    for item in rows:
        stages["raw_option_rows"] += 1
        if not isinstance(item, dict) or item.get("option_type") not in ("call", "put"):
            continue
        stages["call_or_put_rows"] += 1
        bid_stamp = item.get("bid_date")
        ask_stamp = item.get("ask_date")
        try:
            bid_num, ask_num = float(bid_stamp), float(ask_stamp)
            if 1e12 <= bid_num < 1e14 and 1e12 <= ask_num < 1e14:
                stages["quotes_with_millisecond_timestamps"] += 1
            elif 1e9 <= bid_num < 1e11 and 1e9 <= ask_num < 1e11:
                stages["quotes_with_second_timestamps"] += 1
        except (ValueError, TypeError):
            pass
        if item.get("root_symbol") != symbol or nonnegative_int(item.get("contract_size")) != 100:
            stages["unknown_or_adjusted_contract"] += 1
            continue
        strike = positive(item.get("strike"))
        bid, ask = positive(item.get("bid")), positive(item.get("ask"))
        if strike is None or bid is None or ask is None or ask < bid:
            stages["invalid_market"] += 1
            continue
        age = quote_age(item, now)
        if age is None or age > max_quote_age:
            stages["stale_or_missing_quote_time"] += 1
            continue
        if nonnegative_int(item.get("open_interest")) < 100:
            stages["low_open_interest"] += 1
            continue
        if (ask - bid) / ((ask + bid) / 2) > 0.25:
            stages["wide_quoted_market"] += 1
            continue
        if ((item["option_type"] == "call" and strike <= spot)
            or (item["option_type"] == "put" and strike >= spot)):
            stages["not_out_of_money"] += 1
            continue
        stages["otm_liquid_legs"] += 1
    return stages

def run(symbols, token, now=None, max_risk=100.0, max_quote_age=120):
    """Fail on missing authentication/market data; zero candidates is not success proof."""
    now = now or datetime.now(timezone.utc)
    counts = {"0DTE": 0, "1DTE": 0, "7-21DTE": 0}
    rows = []
    diagnostics = {name: 0 for name in (
        "raw_option_rows", "call_or_put_rows", "unknown_or_adjusted_contract",
        "invalid_market", "stale_or_missing_quote_time", "low_open_interest",
        "wide_quoted_market", "not_out_of_money", "otm_liquid_legs",
        "quotes_with_millisecond_timestamps", "quotes_with_second_timestamps")}
    spread_counts = {"bear_call": 0, "bull_put": 0}
    premium_candidate_count = 0
    chains_with_contracts = 0
    examined = 0
    for symbol in symbols:
        spot = spot_quote(get_json(token, "/markets/quotes", {"symbols": symbol}))
        if spot is None:
            raise ProbeFailure("No valid underlying quote for " + symbol)
        dates = expiry_dates(get_json(token, "/markets/options/expirations", {"symbol": symbol}))
        if not dates:
            raise ProbeFailure("No listed options expirations for " + symbol)
        history = get_json(token, "/markets/history",
                           {"symbol": symbol, "interval": "daily",
                            "start": (now.date() - timedelta(days=50)).isoformat(),
                            "end": now.date().isoformat()})
        rv20 = realized_vol20(history)
        for expiry in dates:
            dte = (datetime.strptime(expiry, "%Y-%m-%d").date()
                   - now.astimezone(EASTERN).date()).days
            label = bucket(dte)
            if label is None:
                continue
            examined += 1
            chain = get_json(token, "/markets/options/chains",
                             {"symbol": symbol, "expiration": expiry, "greeks": "true"})
            node = chain.get("options") or {}
            if isinstance(node, dict) and many(node.get("option")):
                chains_with_contracts += 1
            for key, value in diagnose_chain(chain, symbol, spot, now, max_quote_age).items():
                diagnostics[key] += value
            selected = candidates(chain, symbol=symbol, spot=spot, expiry=expiry,
                                  now=now, rv20=rv20, max_risk=max_risk,
                                  max_quote_age=max_quote_age)
            selected.extend(put_candidates(chain, symbol=symbol, spot=spot, expiry=expiry,
                                           now=now, rv20=rv20, max_risk=max_risk,
                                           max_quote_age=max_quote_age))
            rows.extend(selected)
            counts[label] += len(selected)
            for candidate in selected:
                spread_counts[candidate["spread_side"]] += 1
                if (candidate["bucket"] == "7-21DTE"
                    and (candidate["iv_rv_ratio"] or 0) >= 1.20):
                    premium_candidate_count += 1
    if examined == 0 or chains_with_contracts == 0:
        raise ProbeFailure("No in-range option chains with actual contracts returned")
    return rows, {"status": "MARKET_DATA_ACCESS_VERIFIED",
                  "symbols_checked": len(symbols),
                  "chains_requested": examined,
                  "chains_with_contracts": chains_with_contracts,
                  "candidate_counts": counts, "spread_counts": spread_counts,
                  "quote_filter_diagnostics": diagnostics,
                  "iv_rv_ge_1_20_seven_to_21_dte": premium_candidate_count,
                  "read_only": True,
                  "edge_status": "UNVERIFIED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tradier read-only options research probe")
    parser.add_argument("--symbols", default="SPY,F,SOFI,BAC,PFE")
    parser.add_argument("--out", required=True, help="Private ephemeral CSV output, never a public artifact")
    parser.add_argument("--max-risk", type=float, default=100.0)
    parser.add_argument("--max-age", type=float, default=120.0)
    args = parser.parse_args(argv)
    if not 0 < args.max_risk <= 100 or not 0 < args.max_age <= 180:
        parser.error("Require 0 < max risk <= $100 and 0 < quote age <= 180 seconds")
    symbols = list(dict.fromkeys(x.strip().upper() for x in args.symbols.split(",")))
    if not 1 <= len(symbols) <= 5 or any(not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", x) for x in symbols):
        parser.error("Supply 1-5 validated underlying symbols")
    try:
        rows, summary = run(symbols, os.environ.get("TRADIER_TOKEN", ""),
                            max_risk=args.max_risk, max_quote_age=args.max_age)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        print(json.dumps(summary, sort_keys=True))  # No token, raw quote, or contract in logs.
        return 0
    except ProbeFailure as exc:
        print("PROBE_FAILED: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
