"""No-network, synthetic-only acceptance for provider Greek timezone corroboration."""
import io
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import tradier_greeks_crosscheck as cross
from tradier_options_probe import ProbeFailure

NOW = datetime(2026, 10, 28, 17, 5, tzinfo=timezone.utc)
EXPIRATION = "2026-11-13"
WHEN = "2026-10-28T16:30:00"
SYMBOLS = {"call": "SPY261113C00100000", "put": "SPY261113P00100000"}


def option(side):
    return {
        "symbol": SYMBOLS[side],
        "option_type": side,
        "root_symbol": "SPY",
        "strike": 100,
        "bid": 2.1,
        "ask": 2.15,
        "bid_date": int((NOW - timedelta(seconds=8)).timestamp() * 1000),
        "ask_date": int((NOW - timedelta(seconds=7)).timestamp() * 1000),
        "open_interest": 400,
        "contract_size": 100,
        "greeks": {
            "mid_iv": 0.30 if side == "call" else 0.28,
            "updated_at": WHEN,
        },
    }


def direct(side, utc=WHEN + "Z"):
    return {"greeks": {"greek": [{
        "symbol": SYMBOLS[side],
        "mid_iv": 0.30 if side == "call" else 0.28,
        "updated_at": utc,
    }]}}


def fake_api(token, endpoint, params):
    if token != "NONSECRET":
        raise AssertionError("Unexpected token used in synthetic test")
    if endpoint == "/markets/clock":
        return {"clock": {"state": "open"}}
    if endpoint == "/markets/quotes":
        return {"quotes": {"quote": {"bid": 99.99, "ask": 100.01}}}
    if endpoint == "/markets/options/expirations":
        return {"expirations": {"date": [EXPIRATION]}}
    if endpoint == "/markets/options/chains":
        return {"options": {"option": [option("call"), option("put")]}}
    if endpoint == "/markets/options/greeks":
        return direct(params["type"])
    raise AssertionError("Unexpected endpoint " + endpoint)


class GreekCorroborationTests(unittest.TestCase):
    def test_two_sides_corrob_only_after_matched_explicit_utc_and_iv(self):
        calls = []
        def fetch(t, endpoint, params):
            calls.append((endpoint, params))
            return fake_api(t, endpoint, params)
        with patch("tradier_greeks_crosscheck.probe.get_json", side_effect=fetch):
            result = cross.run_crosscheck("NONSECRET", now=NOW)
        self.assertEqual(result["status"], "TWO_SIDES_CORROBORATED_DIAGNOSTIC_ONLY")
        self.assertEqual(result["h1_signal_status"], "UNVERIFIED")
        self.assertTrue(result["does_not_change_h1_gate"])
        self.assertEqual(result["direct_side_requests"], 2)
        self.assertEqual(result["utc_fresh_concordant"], 2)
        self.assertEqual(result["selector_filter_funnel"]["raw_rows"], 2)
        self.assertEqual(result["selector_filter_funnel"]["standard_symbol_legs"], 2)
        self.assertEqual(result["selector_filter_funnel"]["occ_symbol_shape_matches"], 2)
        self.assertEqual(result["selector_filter_funnel"]["within_3pct_spot"], 2)
        self.assertEqual(result["selector_filter_funnel"]["fresh_quote_at_most_120s"], 2)
        self.assertEqual(result["selector_filter_funnel"]["greek_naive_iso_timestamp"], 2)
        self.assertEqual(len(calls), 6)
        self.assertEqual(sum(x[0] == "/markets/options/greeks" for x in calls), 2)
        self.assertEqual([p["type"] for path, p in calls
                          if path == "/markets/options/greeks"], ["call", "put"])
        self.assertNotIn("SPY", str(result))
        self.assertNotIn("2.1", str(result))


    def test_selector_funnel_identifies_contract_shape_without_guessing_root(self):
        pad = option("call")
        pad["symbol"] = "SPY   261113C00100000"
        data = {"options": {"option": [pad]}}
        counters = {}
        selected = cross._nearest_naive_atm_contracts(
            data, symbol="SPY", spot=100, now=NOW, counters=counters)
        self.assertEqual(selected, {})
        self.assertEqual(counters["raw_rows"], 1)
        self.assertEqual(counters["standard_symbol_legs"], 1)
        self.assertEqual(counters["occ_symbol_shape_matches"], 0)
        self.assertEqual(counters["greek_naive_iso_timestamp"], 0)

    def test_selector_funnel_stale_quote_rejected_without_logging_raw_market_rows(self):
        stale = option("call")
        stale["bid_date"] = int((NOW - timedelta(seconds=600)).timestamp() * 1000)
        data = {"options": {"option": [stale]}}
        counters = {}
        selected = cross._nearest_naive_atm_contracts(
            data, symbol="SPY", spot=100, now=NOW, counters=counters)
        self.assertEqual(selected, {})
        self.assertEqual(counters["open_interest_at_least_100"], 1)
        self.assertEqual(counters["fresh_quote_at_most_120s"], 0)
        self.assertNotIn(SYMBOLS["call"], str(counters))
        self.assertNotIn(WHEN, str(counters))


    def test_bounded_fallback_skips_low_oi_weekly_without_loosened_liquidity(self):
        calls = []
        def fetch(token, path, params):
            calls.append((path, params))
            if path == "/markets/options/expirations":
                return {"expirations": {"date": ["2026-11-13", "2026-11-06"]}}
            if path == "/markets/options/chains":
                if params["expiration"] == "2026-11-13":
                    first = [option("call"), option("put")]
                    for leg in first:
                        leg["open_interest"] = 5
                    return {"options": {"option": first}}
                second = [option("call"), option("put")]
                for leg in second:
                    leg["symbol"] = leg["symbol"].replace("261113", "261106")
                return {"options": {"option": second}}
            if path == "/markets/options/greeks":
                response = direct(params["type"])
                response["greeks"]["greek"][0]["symbol"] = (
                    response["greeks"]["greek"][0]["symbol"]
                    .replace("261113", "261106"))
                return response
            return fake_api(token, path, params)
        with patch("tradier_greeks_crosscheck.probe.get_json", side_effect=fetch):
            result = cross.run_crosscheck("NONSECRET", now=NOW)
        self.assertEqual(result["status"], "TWO_SIDES_CORROBORATED_DIAGNOSTIC_ONLY")
        self.assertEqual(result["sampled_expirations"], 2)
        self.assertEqual(result["two_sided_eligible_expirations_found"], 1)
        self.assertEqual(result["direct_side_requests"], 2)
        self.assertEqual(result["selector_filter_funnel"]["raw_rows"], 4)
        self.assertEqual(result["selector_filter_funnel"]["open_interest_at_least_100"], 2)
        self.assertEqual(len(calls), 7)
        self.assertEqual(
            [params["expiration"] for path, params in calls
             if path == "/markets/options/chains"],
            ["2026-11-13", "2026-11-06"])

    def test_max_three_expiries_without_liquid_pair_is_bounded_and_inconclusive(self):
        calls = []
        def fetch(token, path, params):
            calls.append(path)
            if path == "/markets/options/expirations":
                return {"expirations": {"date": [
                    "2026-11-06", "2026-11-13", "2026-11-17", "2026-11-18"]}}
            if path == "/markets/options/chains":
                row = option("call")
                row["symbol"] = row["symbol"].replace(
                    "261113", params["expiration"][2:].replace("-", ""))
                row["open_interest"] = 5
                return {"options": {"option": [row]}}
            return fake_api(token, path, params)
        with patch("tradier_greeks_crosscheck.probe.get_json", side_effect=fetch):
            result = cross.run_crosscheck("NONSECRET", now=NOW)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertEqual(result["sampled_expirations"], 3)
        self.assertEqual(result["direct_side_requests"], 0)
        self.assertEqual(result["two_sided_eligible_expirations_found"], 0)
        self.assertEqual(calls.count("/markets/options/chains"), 3)
        self.assertEqual(len(calls), 6)

    def test_different_expiry_occ_contracts_cannot_substitute_sampled_date(self):
        counters = {}
        selected = cross._nearest_naive_atm_contracts(
            {"options": {"option": [option("call")]}},
            symbol="SPY", spot=100, now=NOW,
            expiration="2026-11-06", counters=counters)
        self.assertEqual(selected, {})
        self.assertEqual(counters["occ_symbol_shape_matches"], 1)
        self.assertEqual(counters["expiry_matches_requested"], 0)

    def test_timezones_must_match_same_instant_not_same_wallclock(self):
        good = option("call")
        self.assertTrue(cross.corroborate(
            good, direct("call")["greeks"]["greek"][0], now=NOW)["utc_fresh_concordant"])
        wrong = direct("call", "2026-10-28T16:30:00-04:00")["greeks"]["greek"][0]
        result = cross.corroborate(good, wrong, now=NOW)
        self.assertTrue(result["direct_offset_aware"])
        self.assertFalse(result["utc_wallclock_concordant"])
        self.assertFalse(result["utc_fresh_concordant"])

    def test_no_timezone_or_mismatched_iv_never_proves_utc(self):
        original = option("call")
        naive = direct("call", WHEN)["greeks"]["greek"][0]
        self.assertFalse(cross.corroborate(original, naive, now=NOW)["utc_fresh_concordant"])
        mismatch = direct("call")["greeks"]["greek"][0]
        mismatch["mid_iv"] = 0.10
        result = cross.corroborate(original, mismatch, now=NOW)
        self.assertTrue(result["utc_wallclock_concordant"])
        self.assertFalse(result["iv_concordant"])
        self.assertFalse(result["utc_fresh_concordant"])

    def test_expired_or_future_greeks_fail_corroboration(self):
        original = option("call")
        for timestamp in ("2026-10-28T12:00:00Z", "2026-10-28T19:00:00Z", ""):
            other = direct("call", timestamp)["greeks"]["greek"][0]
            self.assertFalse(cross.corroborate(original, other, now=NOW)[
                "utc_fresh_concordant"])

    def test_duplicate_direct_contracts_rejected(self):
        example = direct("call")
        example["greeks"]["greek"].append(dict(example["greeks"]["greek"][0]))
        self.assertIsNone(cross._find_unique_direct_contract(example, SYMBOLS["call"]))

    def test_market_closed_never_fetches_tokenized_quotes_or_greeks(self):
        with patch("tradier_greeks_crosscheck.probe.get_json",
                   return_value={"clock": {"state": "closed"}}) as fetch:
            result = cross.run_crosscheck("NONSECRET", now=NOW)
        self.assertEqual(result["status"], "MARKET_CLOSED_SKIPPED")
        self.assertEqual(result["requests_beyond_clock"], 0)
        fetch.assert_called_once_with("NONSECRET", "/markets/clock", {})

    def test_one_side_not_available_is_inconclusive(self):
        def get_partial(t, endpoint, params):
            if endpoint == "/markets/options/chains":
                return {"options": {"option": [option("call")]}}
            return fake_api(t, endpoint, params)
        with patch("tradier_greeks_crosscheck.probe.get_json",
                   side_effect=get_partial):
            result = cross.run_crosscheck("NONSECRET", now=NOW)
        self.assertEqual(result["status"], "INCONCLUSIVE")
        self.assertEqual(result["naive_atm_call_legs_selected"], 0)
        self.assertEqual(result["naive_atm_put_legs_selected"], 0)
        self.assertEqual(result["utc_fresh_concordant"], 0)
        self.assertEqual(result["direct_side_requests"], 0)
        self.assertEqual(result["two_sided_eligible_expirations_found"], 0)

    def test_invalid_clock_fails_closed_without_token_printing(self):
        with patch("tradier_greeks_crosscheck.probe.get_json",
                   return_value={"clock": {"state": "unknown"}}):
            with self.assertRaises(ProbeFailure):
                cross.run_crosscheck("NONSECRET", now=NOW)

    def test_symbol_matching_prevents_substitution(self):
        wrong = direct("call")
        wrong["greeks"]["greek"][0]["symbol"] = "AAPL261113C00100000"
        self.assertIsNone(cross._find_unique_direct_contract(wrong, SYMBOLS["call"]))


if __name__ == "__main__":
    unittest.main()
