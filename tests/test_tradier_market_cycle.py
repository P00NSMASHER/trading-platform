"""Offline safety and coverage tests for the Tradier market research orchestration."""
import io
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import tradier_market_cycle as cycle
from tradier_options_probe import ProbeFailure

NOW = datetime(2026, 10, 27, 15, 20, tzinfo=timezone.utc)


class MarketCycleTests(unittest.TestCase):
    def test_curated_universe_is_distinct_and_bounded(self):
        self.assertEqual(len(cycle.DEFAULT_SYMBOLS), 16)
        self.assertEqual(len(set(cycle.DEFAULT_SYMBOLS)), 16)
        self.assertEqual(cycle.parse_symbols("SPY,QQQ,SPY"), ["SPY", "QQQ"])
        for raw in ("", "SPY,../BAD", ",".join(["SPY"] + [f"SYM{i}" for i in range(20)])):
            with self.assertRaises(ProbeFailure):
                cycle.parse_symbols(raw)

    def test_closed_market_skips_all_option_and_intraday_requests(self):
        with patch("tradier_market_cycle.probe.get_json", return_value={"clock": {"state": "closed"}}) as fetch, \
             patch("tradier_market_cycle.probe.run") as observe:
            rows, summary = cycle.run_cycle("NONSECRET", ["SPY"], now=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(summary["status"], "MARKET_CLOSED_SKIPPED")
        self.assertEqual(summary["chains_requested"], 0)
        self.assertEqual(summary["edge_status"], "UNVERIFIED")
        fetch.assert_called_once_with("NONSECRET", "/markets/clock", {})
        observe.assert_not_called()

    def test_invalid_clock_never_defaults_to_open(self):
        for payload in ({}, {"clock": {}}, {"clock": {"state": "unknown"}}, {"clock": {"state": True}}):
            with patch("tradier_market_cycle.probe.get_json", return_value=payload):
                with self.assertRaises(ProbeFailure):
                    cycle.run_cycle("NONSECRET", ["SPY"], now=NOW)

    def test_four_bounded_batches_no_account_or_trade_routes(self):
        all_calls = []
        def mock_data(token, path, params):
            all_calls.append((path, params))
            if path == "/markets/clock":
                return {"clock": {"state": "open"}}
            if path == "/markets/timesales":
                return {"series": {"data": [{"time": "2026-10-27 11:20:00", "close": 101.5}]}}
            raise AssertionError("Unexpected data endpoint")

        def mock_batch(symbols, token, now=None):
            self.assertLessEqual(len(symbols), 5)
            self.assertEqual(token, "NONSECRET")
            return [], {
                "chains_requested": len(symbols) * 2,
                "chains_with_contracts": len(symbols) * 2,
                "candidate_counts": {"0DTE": 1, "1DTE": 2, "7-21DTE": 3},
                "spread_counts": {"bear_call": 1, "bull_put": 2},
                "iv_rv_ge_1_20_seven_to_21_dte": 2,
                "h1_qualifying_chains": 1,
                "h1_qualifying_symbols": 1,
                "h1_signal_spread_sides": {"bear_call": 1, "bull_put": 1},
                "atm_iv_coverage": {
                    "chains_primary_window": 3,
                    "chains_with_two_sided_atm_iv": 2,
                    "chains_missing_atm_iv": 1,
                    "chains_with_completed_rv20": 3,
                    "candidate_spreads_with_complete_atm_signal": 2,
                },
                "quote_filter_diagnostics": {"raw_option_rows": 10, "otm_liquid_legs": 4},
                "quote_filter_by_dte": {
                    "7-21DTE": {"raw_option_rows": 10, "otm_liquid_legs": 4}
                },
                "spread_pair_funnel": {"pairs_considered": 8, "pairs_eligible": 3},
                "spread_pair_funnel_by_dte": {
                    "7-21DTE": {"pairs_considered": 8, "pairs_eligible": 3}
                },
            }

        with patch("tradier_market_cycle.probe.get_json", side_effect=mock_data), \
             patch("tradier_market_cycle.probe.run", side_effect=mock_batch) as observe:
            rows, summary = cycle.run_cycle("NONSECRET", list(cycle.DEFAULT_SYMBOLS), now=NOW)

        self.assertEqual(rows, [])
        self.assertEqual(observe.call_count, 4)
        self.assertEqual(summary["symbols_requested"], 16)
        self.assertEqual(summary["chains_requested"], 32)
        self.assertEqual(summary["candidate_counts"]["7-21DTE"], 12)
        self.assertEqual(summary["spread_counts"]["bull_put"], 8)
        self.assertEqual(summary["quote_filter_diagnostics"]["raw_option_rows"], 40)
        self.assertEqual(summary["quote_filter_by_dte"]["7-21DTE"]["raw_option_rows"], 40)
        self.assertEqual(summary["spread_pair_funnel"]["pairs_eligible"], 12)
        self.assertEqual(summary["spread_pair_funnel_by_dte"]["7-21DTE"]["pairs_eligible"], 12)
        self.assertEqual(summary["iv_rv_ge_1_20_seven_to_21_dte"], 8)
        self.assertEqual(summary["h1_qualifying_chains"], 4)
        self.assertEqual(summary["h1_qualifying_symbols"], 4)
        self.assertEqual(summary["h1_signal_spread_sides"], {"bear_call": 4, "bull_put": 4})
        self.assertEqual(summary["atm_iv_coverage"]["chains_primary_window"], 12)
        self.assertEqual(summary["atm_iv_coverage"]["chains_with_two_sided_atm_iv"], 8)
        self.assertEqual(summary["atm_iv_coverage"]["chains_missing_atm_iv"], 4)
        self.assertEqual(summary["atm_iv_coverage"]["candidate_spreads_with_complete_atm_signal"], 8)
        self.assertEqual(summary["intraday_underlying_context"]["bars_observed"], 3)
        self.assertEqual(summary["edge_status"], "UNVERIFIED")
        self.assertEqual([x[0] for x in all_calls], ["/markets/clock"] + ["/markets/timesales"] * 3)

    def test_bars_bad_inputs_counted_not_invented(self):
        def fake(_t, path, _p):
            self.assertEqual(path, "/markets/timesales")
            return {"series": {"data": [
                {"time": "2026-10-27 11:19:00", "close": 4.25},
                {"time": "2026-10-27 11:18:00", "close": None},
                {"time": None, "close": 3.25},
                "garbage",
            ]}}
        with patch("tradier_market_cycle.probe.get_json", side_effect=fake):
            result = cycle.recent_bar_evidence("NONSECRET", NOW, ["SPY"])
        self.assertEqual(result["symbols_requested"], 1)
        self.assertEqual(result["bars_observed"], 1)
        self.assertEqual(result["missing_or_invalid_bars"], 3)

    def test_any_failed_batch_fails_whole_market_run(self):
        with patch("tradier_market_cycle.probe.get_json", return_value={"clock": {"state": "open"}}), \
             patch("tradier_market_cycle.probe.run", side_effect=ProbeFailure("Synthetic market gap")):
            with self.assertRaisesRegex(ProbeFailure, "Synthetic market gap"):
                cycle.run_cycle("NONSECRET", ["SPY"], now=NOW)

    def test_missing_secret_fails_without_emitting_or_persisting(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch("sys.stdout", new_callable=io.StringIO) as out, \
             patch("tradier_market_cycle.run_cycle") as observe:
            self.assertEqual(cycle.main(["--out", "/tmp/no-write.csv"]), 1)
        self.assertIn("TRADIER_TOKEN missing", out.getvalue())
        observe.assert_not_called()

    def test_only_explicit_market_data_routes_can_be_used(self):
        import tradier_options_probe as probe
        self.assertEqual(set(probe.ALLOWED), {
            "/markets/quotes", "/markets/options/expirations",
            "/markets/options/chains", "/markets/history",
            "/markets/clock", "/markets/timesales",
        })
        for path in ("/accounts/0001/orders", "/markets/stream", "/markets/events"):
            with self.assertRaises(ProbeFailure):
                probe.get_json("NONSECRET", path, {})


if __name__ == "__main__":
    unittest.main()
