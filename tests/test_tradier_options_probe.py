"""Offline, deterministic Tradier observer acceptance tests. No network or token."""
import io
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.request import Request

from tradier_options_probe import (ALLOWED, ProbeFailure, _NoRedirects, bucket,
    candidates, expiry_dates, get_json, main, option_iv, quote_age, run, spot_quote)

NOW = datetime(2026, 10, 27, 18, 5, tzinfo=timezone.utc)
TS = int(NOW.timestamp())


def option(strike, bid, ask, age=10, size=100, oi=500):
    return {"symbol": "TEST" + str(strike), "option_type": "call",
            "strike": strike, "bid": bid, "ask": ask,
            "bid_date": TS - age, "ask_date": TS - age,
            "open_interest": oi, "contract_size": size, "root_symbol": "TEST",
            "greeks": {"mid_iv": 0.35}}


class Tests(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual([bucket(i) for i in (0, 1, 6, 7, 21, 22)],
                         ["0DTE", "1DTE", None, "7-21DTE", "7-21DTE", None])

    def test_expiries_two_formats(self):
        self.assertEqual(expiry_dates({"expirations": {"date": ["2026-11-06"]}}), ["2026-11-06"])
        self.assertEqual(expiry_dates({"expirations": {"expiration": [{"date": "2026-11-06"}]}}), ["2026-11-06"])

    def test_uses_natural_entry_prices_and_defined_risk(self):
        chain = {"options": {"option": [option(101, 1.25, 1.27), option(102, 0.78, 0.80)]}}
        rows = candidates(chain, symbol="TEST", spot=100, expiry="2026-11-06", now=NOW, rv20=0.25)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["credit_per_share"], 0.45)
        self.assertAlmostEqual(rows[0]["risk_estimate_usd"], 57.6)
        self.assertEqual(rows[0]["bucket"], "7-21DTE")
        self.assertTrue(rows[0]["research_only"])

    def test_rejects_nonstandard_unknown_stale_wide_or_low_oi(self):
        valid = option(101, 1.25, 1.27)
        rejects = [option(102, .78, .80, age=99999),
                   option(102, .10, .99),
                   option(102, .78, .80, oi=1),
                   option(102, .78, .80, size=10),
                   option(102, .78, .80, size=None)]
        for bad in rejects:
            self.assertEqual(candidates({"options": {"option": [valid, bad]}},
                     symbol="TEST", spot=100, expiry="2026-11-06", now=NOW, rv20=.2), [])

    def test_rejects_uncovered_naked_call(self):
        rows = candidates({"options": {"option": [option(99, 1.5, 1.55), option(101, .7, .75)]}},
                          symbol="TEST", spot=100, expiry="2026-11-06", now=NOW, rv20=.2)
        self.assertEqual(rows, [])

    def test_allowlist_denies_orders_and_account_routes(self):
        self.assertEqual(len(ALLOWED), 4)
        for path in ("/accounts/123/orders", "/accounts/balances", "/markets/quotes/extra"):
            with self.assertRaises(ProbeFailure):
                get_json("TEST-TOKEN", path, {})

    def test_redirects_deny_token_forwarding(self):
        with self.assertRaises(ProbeFailure):
            _NoRedirects().redirect_request(Request("https://api.tradier.com/x",
                                                    headers={"Authorization": "Bearer TEST-TOKEN"}),
                                           None, 302, "redirect", {}, "https://example.com")

    def test_both_quote_timestamps_required(self):
        self.assertIsNone(quote_age({"bid_date": TS}, NOW))
        self.assertIsNone(quote_age({"bid_date": TS+100, "ask_date": TS}, NOW))

    def test_live_metadata_check_not_edge_proof(self):
        responses = {
            "/markets/quotes": {"quotes": {"quote": {"bid": 100, "ask": 100.02}}},
            "/markets/options/expirations": {"expirations": {"date": ["2026-10-27", "2026-10-28", "2026-11-06"]}},
            "/markets/history": {"history": {"day": []}},
            "/markets/options/chains": {"options": {"option": [option(101, 1.25, 1.27), option(102, .78, .80)]}},
        }
        with patch("tradier_options_probe.get_json", side_effect=lambda _t, path, _p: responses[path]):
            rows, summary = run(["TEST"], "DUMMY", now=NOW)
        self.assertEqual(summary["status"], "MARKET_DATA_ACCESS_VERIFIED")
        self.assertEqual(summary["edge_status"], "UNVERIFIED")
        self.assertEqual(summary["candidate_counts"]["7-21DTE"], 1)
        self.assertEqual(summary["chains_requested"], 3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(summary["candidate_counts"]["0DTE"], 1)
        self.assertEqual(summary["candidate_counts"]["1DTE"], 1)

    def test_missing_token_must_fail_cli(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(main(["--out", "/tmp/dont-write.csv"]), 1)
                self.assertIn("PROBE_FAILED", output.getvalue())
                self.assertNotIn("Bearer", output.getvalue())

    def test_one_bad_symbol_aborts_whole_scan(self):
        with patch("tradier_options_probe.get_json", return_value={"quotes": {"quote": []}}):
            with self.assertRaises(ProbeFailure):
                run(["SPY"], "DUMMY", now=NOW)


if __name__ == "__main__":
    unittest.main()
