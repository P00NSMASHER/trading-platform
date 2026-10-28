"""Bounded Tradier Greek timestamp cross-endpoint corroboration (research only).

This does NOT alter the strict H1 signal gate. Public Actions logs contain only
aggregate counts, no symbols, option quotes, strikes or timestamps. No orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re

import tradier_options_probe as probe

SYMBOL = "SPY"  # Fixed small ETF-only scope, not a stock recommendation.
MAX_GREEK_AGE_SECONDS = 90 * 60
MAX_QUOTE_AGE_SECONDS = 120
MAX_CROSS_ENDPOINT_TIME_DIFFERENCE_SECONDS = 60
MAX_CROSS_ENDPOINT_IV_DIFFERENCE = 0.005
MAX_EXPIRATION_CHECKS = 4


def _datetime_utc(raw, *, require_timezone):
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        stamp = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if require_timezone:
        return stamp.astimezone(timezone.utc) if stamp.tzinfo is not None else None
    return stamp if stamp.tzinfo is None else None


def _nearest_naive_atm_contracts(chain, *, symbol, spot, now, counters=None):
    """Select near-ATM put/call options; return anonymous stage counts if requested.

    Counters are an ordered filter funnel, not independent classifications.
    No contract ID, quote, strike, timestamp or symbol leaves this process.
    """
    node = chain.get("options")
    records = probe.many(node.get("option")) if isinstance(node, dict) else []
    stages = {
        "raw_rows": 0,
        "standard_symbol_legs": 0,
        "occ_symbol_shape_matches": 0,
        "within_3pct_spot": 0,
        "valid_market": 0,
        "open_interest_at_least_100": 0,
        "fresh_quote_at_most_120s": 0,
        "valid_fractional_iv": 0,
        "greek_naive_iso_timestamp": 0,
    }
    best = {}
    for item in records:
        stages["raw_rows"] += 1
        if not isinstance(item, dict):
            continue
        side = item.get("option_type")
        contract = item.get("symbol")
        if (side not in ("call", "put")
            or item.get("root_symbol") != symbol
            or probe.nonnegative_int(item.get("contract_size")) != 100):
            continue
        stages["standard_symbol_legs"] += 1
        if (not isinstance(contract, str)
            or not re.fullmatch(r"SPY[0-9]{6}[CP][0-9]{8}", contract)):
            continue
        stages["occ_symbol_shape_matches"] += 1
        strike = probe.positive(item.get("strike"))
        if strike is None or abs(strike - spot) / spot > 0.03:
            continue
        stages["within_3pct_spot"] += 1
        bid, ask = probe.positive(item.get("bid")), probe.positive(item.get("ask"))
        if (bid is None or ask is None or ask < bid
            or (ask - bid) / ((ask + bid) / 2) > 0.25):
            continue
        stages["valid_market"] += 1
        if probe.nonnegative_int(item.get("open_interest")) < 100:
            continue
        stages["open_interest_at_least_100"] += 1
        quote_age = probe.quote_age(item, now)
        if quote_age is None or quote_age > MAX_QUOTE_AGE_SECONDS:
            continue
        stages["fresh_quote_at_most_120s"] += 1
        greeks = item.get("greeks")
        if not isinstance(greeks, dict) or probe.option_iv(item) is None:
            continue
        stages["valid_fractional_iv"] += 1
        if _datetime_utc(greeks.get("updated_at"), require_timezone=False) is None:
            continue
        stages["greek_naive_iso_timestamp"] += 1
        rank = (abs(strike - spot), -probe.nonnegative_int(item.get("open_interest")))
        if side not in best or rank < best[side][0]:
            best[side] = (rank, item)
    if counters is not None:
        counters.update(stages)
    return {side: pair[1] for side, pair in best.items()}


def _find_unique_direct_contract(payload, contract):
    node = payload.get("greeks")
    rows = probe.many(node.get("greek")) if isinstance(node, dict) else []
    matches = [r for r in rows if isinstance(r, dict) and r.get("symbol") == contract]
    return matches[0] if len(matches) == 1 else None


def corroborate(chain_option, direct_greeks, *, now):
    """A matching, current, explicit-zone Greek is evidence, not a license to infer all zones."""
    if not isinstance(chain_option, dict) or not isinstance(direct_greeks, dict):
        return {
            "direct_offset_aware": False, "iv_concordant": False,
            "utc_wallclock_concordant": False, "utc_fresh_concordant": False,
        }
    ch = chain_option.get("greeks") or {}
    raw_chain_time = ch.get("updated_at") if isinstance(ch, dict) else None
    chain_naive = _datetime_utc(raw_chain_time, require_timezone=False)
    direct_utc = _datetime_utc(direct_greeks.get("updated_at"), require_timezone=True)
    direct_aware = direct_utc is not None
    chain_iv = probe.option_iv(chain_option)
    direct_iv = probe.option_iv({"greeks": direct_greeks})
    iv_match = (chain_iv is not None and direct_iv is not None
                and abs(chain_iv - direct_iv) <= MAX_CROSS_ENDPOINT_IV_DIFFERENCE)
    utc_match = (chain_naive is not None and direct_utc is not None
                 and abs((chain_naive - direct_utc.replace(tzinfo=None)).total_seconds())
                 <= MAX_CROSS_ENDPOINT_TIME_DIFFERENCE_SECONDS)
    age = (now - direct_utc).total_seconds() if direct_utc is not None else None
    fresh = (iv_match and utc_match and age is not None
             and -60 <= age <= MAX_GREEK_AGE_SECONDS)
    return {
        "direct_offset_aware": direct_aware,
        "iv_concordant": iv_match,
        "utc_wallclock_concordant": utc_match,
        "utc_fresh_concordant": fresh,
    }


def run_crosscheck(token, *, now=None):
    """At most nine HTTPS GET market-data requests, diagnostic-only.

    Scan at most four expirations nearest 14 DTE, favoring a chain with
    both liquid near-ATM sides. A single thin expiration must not prevent
    validation of the direct Greek endpoint on a different listed expiry.
    """
    now = now or datetime.now(timezone.utc)
    state = probe.get_json(token, "/markets/clock", {}).get("clock") or {}
    state_name = state.get("state") if isinstance(state, dict) else None
    if state_name not in ("open", "closed", "premarket", "postmarket"):
        raise probe.ProbeFailure("Market clock unknown; Greek crosscheck failed closed")
    if state_name != "open":
        return {"status": "MARKET_CLOSED_SKIPPED", "h1_signal_status": "UNVERIFIED",
                "cross_endpoint_only": True, "read_only": True, "requests_beyond_clock": 0}

    spot = probe.spot_quote(probe.get_json(token, "/markets/quotes", {"symbols": SYMBOL}))
    if spot is None:
        raise probe.ProbeFailure("Greek crosscheck missing valid underlying quote")
    expiries = probe.expiry_dates(probe.get_json(
        token, "/markets/options/expirations", {"symbol": SYMBOL}))
    local_date = now.astimezone(probe.EASTERN).date()
    eligible = sorted(
        (abs(dte - 14), expiry)
        for expiry in expiries
        if 7 <= (dte := (datetime.strptime(expiry, "%Y-%m-%d").date() - local_date).days) <= 21
    )
    if not eligible:
        return {"status": "NO_ELIGIBLE_EXPIRATION", "h1_signal_status": "UNVERIFIED",
                "cross_endpoint_only": True, "read_only": True,
                "requests_beyond_clock": 2, "expirations_sampled": 0}

    selector_totals = {}
    fallback = None
    selected = {}
    selected_expiration = None
    expirations_sampled = 0
    expirations_with_two_liquid_sides = 0
    expirations_with_one_liquid_side = 0
    for _, expiration in eligible[:MAX_EXPIRATION_CHECKS]:
        chain = probe.get_json(token, "/markets/options/chains", {
            "symbol": SYMBOL, "expiration": expiration, "greeks": "true"})
        stages = {}
        options = _nearest_naive_atm_contracts(
            chain, symbol=SYMBOL, spot=spot, now=now, counters=stages)
        expirations_sampled += 1
        for key, amount in stages.items():
            selector_totals[key] = selector_totals.get(key, 0) + amount
        if len(options) == 2:
            expirations_with_two_liquid_sides += 1
            selected = options
            selected_expiration = expiration
            break
        if len(options) == 1:
            expirations_with_one_liquid_side += 1
            if fallback is None:
                fallback = (expiration, options)
    if not selected and fallback is not None:
        selected_expiration, selected = fallback

    report = {
        "status": "INCONCLUSIVE",
        "h1_signal_status": "UNVERIFIED",
        "cross_endpoint_only": True,
        "does_not_change_h1_gate": True,
        "read_only": True,
        "sampled_expirations": expirations_sampled,
        "expirations_considered": len(eligible),
        "max_expiration_checks": MAX_EXPIRATION_CHECKS,
        "expirations_with_two_liquid_sides": expirations_with_two_liquid_sides,
        "expirations_with_one_liquid_side": expirations_with_one_liquid_side,
        "selector_filter_funnel": selector_totals,
        "naive_atm_call_legs_selected": int("call" in selected),
        "naive_atm_put_legs_selected": int("put" in selected),
        "direct_side_requests": 0,
        "direct_offset_aware": 0,
        "same_contract_iv_matches": 0,
        "utc_wallclock_matches": 0,
        "utc_fresh_concordant": 0,
    }
    for side in ("call", "put"):
        item = selected.get(side)
        if item is None:
            continue
        direct = probe.get_json(token, "/markets/options/greeks", {
            "symbol": SYMBOL, "expiration": selected_expiration, "type": side})
        report["direct_side_requests"] += 1
        direct_item = _find_unique_direct_contract(direct, item["symbol"])
        result = corroborate(item, direct_item, now=now)
        report["direct_offset_aware"] += int(result["direct_offset_aware"])
        report["same_contract_iv_matches"] += int(result["iv_concordant"])
        report["utc_wallclock_matches"] += int(result["utc_wallclock_concordant"])
        report["utc_fresh_concordant"] += int(result["utc_fresh_concordant"])
    if len(selected) == 2 and report["utc_fresh_concordant"] == 2:
        report["status"] = "TWO_SIDES_CORROBORATED_DIAGNOSTIC_ONLY"
    return report


def main():
    try:
        result = run_crosscheck(os.environ.get("TRADIER_TOKEN", ""))
        print(json.dumps(result, sort_keys=True))
        return 0
    except probe.ProbeFailure as exc:
        print("GREEKS_CROSSCHECK_FAILED: " + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
