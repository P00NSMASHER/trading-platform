"""Offline, deterministic Tradier observer acceptance tests. No network or token."""
import io
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from urllib.request import Request

import tradier_options_probe as probe

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

    def test_completed_close_volatility_excludes_partial_current_day(self):
        historical = [
            {"date": f"2026-09-{i:02d}", "close": float(95 + i + (i % 3))}
            for i in range(1, 22)
        ]
        reference = {"history": {"day": historical}}
        latest = {"history": {"day": historical + [
            {"date": "2026-09-22", "close": 1_000_000.0}
        ]}}
        baseline = probe.realized_vol20(reference, asof_date=date(2026, 9, 22))
        observed = probe.realized_vol20(latest, asof_date=date(2026, 9, 22))
        self.assertEqual(baseline, observed)
        self.assertIsNotNone(baseline)
        self.assertGreater(baseline, 0)

    def test_duplicate_daily_bars_do_not_generate_false_volatility(self):
        days = [{"date": f"2026-09-{i:02d}", "close": 100 + i} for i in range(1, 22)]
        days[-1]["date"] = days[-2]["date"]
        self.assertIsNone(probe.realized_vol20(
            {"history": {"day": days}}, asof_date=date(2026, 9, 22)
        ))

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
        self.assertEqual(len(ALLOWED), 6)
        self.assertIn('/markets/clock', ALLOWED)
        self.assertIn('/markets/timesales', ALLOWED)
        for path in ("/accounts/123/orders", "/accounts/balances", "/markets/quotes/extra"):
            with self.assertRaises(ProbeFailure):
                get_json("TEST-TOKEN", path, {})

    def test_redirects_deny_token_forwarding(self):
        with self.assertRaises(ProbeFailure):
            _NoRedirects().redirect_request(Request("https://api.tradier.com/x",
                                                    headers={"Authorization": "Bearer TEST-TOKEN"}),
                                           None, 302, "redirect", {}, "https://example.com")


    def test_second_and_millisecond_quote_clocks_are_equivalent(self):
        sec = {"bid_date": TS - 10, "ask_date": TS - 8}
        millis = {"bid_date": (TS - 10) * 1000, "ask_date": (TS - 8) * 1000}
        self.assertEqual(quote_age(sec, NOW), 10)
        self.assertEqual(quote_age(millis, NOW), 10)
        self.assertEqual(quote_age(sec, NOW), quote_age(millis, NOW))

    def test_malformed_microsecond_or_future_epoch_fails_closed(self):
        for value in (None, 0, -1, True, "not-a-timestamp", TS * 1000000,
                      (TS + 120) * 1000):
            self.assertIsNone(quote_age({"bid_date": value, "ask_date": TS}, NOW))

    def test_millisecond_chain_accepts_eligible_otm_legs(self):
        o = option(101, 1.25, 1.27)
        o["bid_date"] = (TS - 10) * 1000
        o["ask_date"] = (TS - 10) * 1000
        diag = probe.diagnose_chain(
            {"options": {"option": [o]}}, symbol="TEST", spot=100, now=NOW
        )
        self.assertEqual(diag["quotes_with_millisecond_timestamps"], 1)
        self.assertEqual(diag["stale_or_missing_quote_time"], 0)
        self.assertEqual(diag["otm_liquid_legs"], 1)


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


    def test_put_credit_vertical_uses_otm_strikes_and_natural_fills(self):
        puts = [
            {**option(99, 1.25, 1.27), "option_type": "put"},
            {**option(98, 0.78, 0.80), "option_type": "put"},
        ]
        rows = probe.put_candidates(
            {"options": {"option": puts}}, symbol="TEST", spot=100,
            expiry="2026-11-06", now=NOW, rv20=0.25,
        )
        assert len(rows) == 1
        assert rows[0]["spread_side"] == "bull_put"
        assert rows[0]["short_strike"] == 99
        assert rows[0]["long_strike"] == 98
        assert abs(rows[0]["credit_per_share"] - 0.45) < 1e-9
        assert abs(rows[0]["risk_estimate_usd"] - 57.60) < 1e-9


    def test_put_credit_rejects_itm_or_adjusted_deliverables(self):
        short = {**option(101, 0.73, 0.75), "option_type": "put"}
        long = {**option(100, 0.48, 0.51), "option_type": "put"}
        assert probe.put_candidates(
            {"options": {"option": [short, long]}},
            symbol="TEST", spot=100, expiry="2026-11-06", now=NOW,
            rv20=0.2,
        ) == []
        short["strike"] = 99
        long["strike"] = 98
        long["contract_size"] = 10
        assert probe.put_candidates(
            {"options": {"option": [short, long]}},
            symbol="TEST", spot=100, expiry="2026-11-06", now=NOW,
            rv20=0.2,
        ) == []


    def test_diagnostics_one_failure_reason_per_contract_without_quotes_in_output(self):
        live = option(101, 1.25, 1.27)
        stale = option(102, 0.78, 0.8, age=10_000)
        low_oi = option(103, 0.70, 0.73, oi=1)
        put = {**option(99, 0.65, 0.68), "option_type": "put"}
        funnel = probe.diagnose_chain(
            {"options": {"option": [live, stale, low_oi, put]}},
            symbol="TEST", spot=100, now=NOW,
        )
        assert funnel["raw_option_rows"] == 4
        assert funnel["call_or_put_rows"] == 4
        assert funnel["stale_or_missing_quote_time"] == 1
        assert funnel["low_open_interest"] == 1
        assert funnel["otm_liquid_legs"] == 2
        assert "TEST" not in str(funnel)
        assert "1.25" not in str(funnel)


    def test_full_probe_reports_aggregate_put_spread_and_premium_count(self):
        puts = [
            {**option(99, 1.25, 1.27), "option_type": "put"},
            {**option(98, 0.78, 0.80), "option_type": "put"},
        ]
        responses = {
            "/markets/quotes": {"quotes": {"quote": {"bid": 100, "ask": 100.02}}},
            "/markets/options/expirations": {"expirations": {"date": ["2026-11-06"]}},
            "/markets/history": {"history": {"day": []}},
            "/markets/options/chains": {"options": {"option": puts}},
        }
        with patch("tradier_options_probe.get_json",
                   side_effect=lambda _token, endpoint, _params: responses[endpoint]):
            rows, summary = probe.run(["TEST"], "DUMMY", now=NOW)
        assert len(rows) == 1
        assert summary["spread_counts"] == {"bear_call": 0, "bull_put": 1}
        assert summary["quote_filter_diagnostics"]["otm_liquid_legs"] == 2
        assert summary["edge_status"] == "UNVERIFIED"



if __name__ == "__main__":
    unittest.main()
