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
            "greeks": {"mid_iv": 0.35, "updated_at": NOW.isoformat()}}


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


    def test_tradier_iv_is_decimal_not_percent_and_rejects_ambiguous_units(self):
        self.assertEqual(probe.option_iv({"greeks": {"mid_iv": 0.35}}), 0.35)
        self.assertEqual(probe.option_iv({"greeks": {"mid_iv": 2.5}}), 2.5)
        self.assertIsNone(probe.option_iv({"greeks": {"mid_iv": 35.0}}))
        self.assertIsNone(probe.option_iv({"greeks": {"mid_iv": None}}))

    def test_atm_iv_uses_both_nearest_valid_sides_not_short_leg_skew(self):
        call_atm = option(100, 2.20, 2.25)
        call_atm["greeks"]["mid_iv"] = 0.40
        put_atm = {**option(100, 2.10, 2.15), "option_type": "put",
                   "greeks": {"mid_iv": 0.36, "updated_at": NOW.isoformat()}}
        short_call = option(101, 1.25, 1.27)
        short_call["greeks"]["mid_iv"] = 0.80
        long_call = option(102, .78, .80)
        chain = {"options": {"option": [
            call_atm, put_atm, short_call, long_call,
        ]}}
        observed = probe.atm_chain_iv(chain, symbol="TEST", spot=100, now=NOW)
        self.assertEqual(observed, 0.38)
        rows = probe.candidates(
            chain, symbol="TEST", spot=100, expiry="2026-11-06",
            now=NOW, rv20=0.25,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["short_iv"], 0.8)
        self.assertNotEqual(observed, rows[0]["short_iv"])

    def test_atm_iv_rejects_one_sided_stale_and_adjusted_data(self):
        call_atm = option(100, 2.2, 2.25)
        put_atm = {**option(100, 2.1, 2.15), "option_type": "put"}
        chain = {"options": {"option": [call_atm]}}
        self.assertIsNone(probe.atm_chain_iv(
            chain, symbol="TEST", spot=100, now=NOW))
        put_atm["bid_date"] = TS - 3600
        chain["options"]["option"].append(put_atm)
        self.assertIsNone(probe.atm_chain_iv(
            chain, symbol="TEST", spot=100, now=NOW))
        put_atm["bid_date"] = TS - 10
        put_atm["contract_size"] = 10
        self.assertIsNone(probe.atm_chain_iv(
            chain, symbol="TEST", spot=100, now=NOW))
        put_atm["contract_size"] = 100
        self.assertEqual(probe.atm_chain_iv(
            chain, symbol="TEST", spot=100, now=NOW), 0.35)

    def test_primary_iv_screen_requires_both_atm_sides_and_completed_rv(self):
        calls = [option(100, 2.2, 2.25),
                 option(101, 1.25, 1.27),
                 option(102, .78, .80)]
        put = {**option(100, 2.1, 2.15), "option_type": "put"}
        for row in calls + [put]:
            row["greeks"]["mid_iv"] = 0.40
        history = [
            {"date": f"2026-09-{i:02d}", "close": float(95 + i + (i % 3))}
            for i in range(1, 22)
        ]
        responses = {
            "/markets/quotes": {"quotes": {"quote": {"bid": 100, "ask": 100.02}}},
            "/markets/options/expirations": {"expirations": {"date": ["2026-11-06"]}},
            "/markets/history": {"history": {"day": history}},
            "/markets/options/chains": {"options": {"option": calls + [put]}},
        }
        with patch("tradier_options_probe.get_json",
                   side_effect=lambda _t, p, _x: responses[p]):
            rows, summary = probe.run(["TEST"], "FAKE", now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["atm_iv"], 0.4)
        self.assertGreater(rows[0]["atm_iv_rv_ratio"], 1.2)
        self.assertEqual(summary["iv_rv_ge_1_20_seven_to_21_dte"], 1)
        self.assertEqual(summary["h1_qualifying_chains"], 1)
        self.assertEqual(summary["h1_qualifying_symbols"], 1)
        self.assertEqual(summary["h1_signal_spread_sides"], {"bear_call": 1, "bull_put": 0})
        self.assertEqual(summary["atm_iv_coverage"]["chains_primary_window"], 1)
        self.assertEqual(summary["atm_iv_coverage"]["chains_with_two_sided_atm_iv"], 1)
        self.assertEqual(summary["atm_iv_coverage"]["candidate_spreads_with_complete_atm_signal"], 1)


    def test_many_h1_spread_pairs_count_one_chain_and_symbol(self):
        spot = 100
        raw = [
            option(100, 2.0, 2.04),
            {**option(100, 2.0, 2.04), "option_type": "put"},
            option(101, 1.25, 1.27),
            option(102, .78, .80),
            option(103, .39, .42),
        ]
        for row in raw:
            row["greeks"]["mid_iv"] = 0.60
        days = [
            {"date": f"2026-09-{i:02d}", "close": float(99 + i + (i % 2))}
            for i in range(1, 22)
        ]
        responses = {
            "/markets/quotes": {"quotes": {"quote": {"bid": 100, "ask": 100.02}}},
            "/markets/options/expirations": {"expirations": {"date": ["2026-11-06"]}},
            "/markets/history": {"history": {"day": days}},
            "/markets/options/chains": {"options": {"option": raw}},
        }
        with patch("tradier_options_probe.get_json",
                   side_effect=lambda _t, p, _x: responses[p]):
            rows, summary = probe.run(["TEST"], "FAKE", now=NOW)
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(summary["iv_rv_ge_1_20_seven_to_21_dte"], len(rows))
        self.assertEqual(summary["h1_qualifying_chains"], 1)
        self.assertEqual(summary["h1_qualifying_symbols"], 1)
        self.assertEqual(summary["h1_signal_spread_sides"]["bear_call"], len(rows))
        self.assertEqual(summary["h1_signal_spread_sides"]["bull_put"], 0)


    def test_hourly_greek_freshness_requires_timestamp_not_quote_freshness(self):
        good = option(100, 1.0, 1.04)
        put = {**option(100, 1.0, 1.04), "option_type": "put"}
        good["greeks"]["updated_at"] = (
            NOW - probe.timedelta(minutes=45)).isoformat()
        put["greeks"]["updated_at"] = (
            NOW - probe.timedelta(minutes=89)).isoformat()
        chain = {"options": {"option": [good, put]}}
        self.assertEqual(probe.atm_chain_iv(
            chain, symbol="TEST", spot=100, now=NOW), 0.35)
        put["greeks"]["updated_at"] = (
            NOW - probe.timedelta(minutes=92)).isoformat()
        self.assertIsNone(probe.atm_chain_iv(
            chain, symbol="TEST", spot=100, now=NOW))
        for bad in ("", "2026-10-27T18:00:00", "invalid"):
            put["greeks"]["updated_at"] = bad
            self.assertIsNone(probe.atm_chain_iv(
                chain, symbol="TEST", spot=100, now=NOW))
        put["greeks"]["updated_at"] = (
            NOW + probe.timedelta(minutes=5)).isoformat()
        self.assertIsNone(probe.atm_chain_iv(
            chain, symbol="TEST", spot=100, now=NOW))


    def test_atm_quality_funnel_distinguishes_missing_stale_and_fresh_greeks(self):
        call = option(100, 1.1, 1.13)
        put = {**option(100, 1.2, 1.23), "option_type": "put"}
        call["greeks"]["mid_iv"] = 0.30
        put["greeks"]["mid_iv"] = 0.32
        chain = {"options": {"option": [call, put]}}
        quality = probe.atm_greeks_quality(
            chain, symbol="TEST", spot=100, now=NOW)
        self.assertEqual(quality["near_atm_standard_legs"], 2)
        self.assertEqual(quality["near_atm_fresh_greeks_legs"], 2)
        self.assertEqual(quality["near_atm_fresh_call_greeks_legs"], 1)
        self.assertEqual(quality["near_atm_fresh_put_greeks_legs"], 1)
        put["greeks"]["updated_at"] = ""
        quality = probe.atm_greeks_quality(
            chain, symbol="TEST", spot=100, now=NOW)
        self.assertEqual(quality["near_atm_greeks_timestamp_missing"], 1)
        self.assertEqual(quality["near_atm_fresh_greeks_legs"], 1)
        put["greeks"]["updated_at"] = (
            NOW - probe.timedelta(hours=3)).isoformat()
        quality = probe.atm_greeks_quality(
            chain, symbol="TEST", spot=100, now=NOW)
        self.assertEqual(quality["near_atm_greeks_timestamp_stale"], 1)
        put["greeks"]["updated_at"] = "2026-10-27T17:00:00"
        quality = probe.atm_greeks_quality(
            chain, symbol="TEST", spot=100, now=NOW)
        self.assertEqual(
            quality["near_atm_greeks_timestamp_malformed_or_naive"], 1)
        self.assertEqual(quality["near_atm_fresh_greeks_legs"], 1)

    def test_positive_bestcase_payoff_requires_more_than_fees_and_fill_stress(self):
        calls = [option(103, 0.16, 0.17), option(104, 0.10, 0.11)]
        responses = {
            "/markets/quotes": {"quotes": {"quote": {"bid": 100, "ask": 100.02}}},
            "/markets/options/expirations": {
                "expirations": {"date": ["2026-11-06"]}},
            "/markets/history": {"history": {"day": []}},
            "/markets/options/chains": {"options": {"option": calls}},
        }
        with patch("tradier_options_probe.get_json",
                   side_effect=lambda _t, p, _x: responses[p]):
            rows, summary = probe.run(["TEST"], "FAKE", now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(summary["candidate_counts"]["7-21DTE"], 1)
        feasibility = summary["best_case_payoff_feasibility_by_dte"]["7-21DTE"]
        self.assertEqual(feasibility["after_fees_positive"], 1)
        self.assertEqual(feasibility["after_fees_and_5_slippage_positive"], 0)
        self.assertEqual(feasibility["after_fees_and_10_slippage_positive"], 0)
        self.assertEqual(summary["edge_status"], "UNVERIFIED")

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
        assert summary["quote_filter_by_dte"]["7-21DTE"]["otm_liquid_legs"] == 2
        assert summary["spread_pair_funnel"]["pairs_eligible"] == 1
        assert summary["spread_pair_funnel_by_dte"]["7-21DTE"]["pairs_eligible"] == 1
        assert summary["edge_status"] == "UNVERIFIED"


    def test_quote_age_bins_are_exclusive_and_do_not_waive_staleness(self):
        chain = {"options": {"option": [
            option(101, 1.25, 1.27, age=10),
            option(102, .78, .80, age=240),
            option(103, .78, .80, age=720),
            option(104, .78, .80, age=1600),
            {**option(105, .78, .80), "ask_date": None},
        ]}}
        diag = probe.diagnose_chain(chain, "TEST", 100, NOW)
        assert diag["call_or_put_rows"] == 5
        assert [diag[k] for k in (
            "age_at_most_120s", "age_121_to_300s", "age_301_to_900s",
            "age_over_900s", "age_missing_or_unparseable",
        )] == [1, 1, 1, 1, 1]
        assert diag["stale_or_missing_quote_time"] == 4
        assert diag["otm_liquid_call_legs"] == 1

    def test_invalid_market_subtypes_do_not_obscure_first_failure(self):
        raw = [
            option(None, .25, .28),
            option(102, 0, .28),
            option(103, .30, .20),
            option(104, .20, .22, age=300),
        ]
        diag = probe.diagnose_chain(
            {"options": {"option": raw}}, "TEST", 100, NOW)
        assert diag["invalid_market"] == 3
        assert diag["invalid_strike"] == 1
        assert diag["invalid_nonpositive_bid_or_ask"] == 1
        assert diag["invalid_crossed_market"] == 1
        assert diag["stale_or_missing_quote_time"] == 1

    def test_pair_funnel_counts_width_risk_and_actual_candidate_parity(self):
        calls = [option(101, 1.25, 1.27), option(102, .78, .80),
                 option(105, .05, .06)]
        puts = [{**option(99, 1.25, 1.27), "option_type": "put"},
                {**option(98, .78, .80), "option_type": "put"},
                {**option(95, .05, .06), "option_type": "put"}]
        chain = {"options": {"option": calls + puts}}
        pair = probe.diagnose_spread_pairs(
            chain, symbol="TEST", spot=100, now=NOW)
        assert pair["otm_call_legs"] == 3
        assert pair["otm_put_legs"] == 3
        assert pair["pairs_considered"] == 6
        assert pair["pairs_over_3_width"] == 2
        assert pair["pairs_over_100_risk_cap"] == 2
        assert pair["pairs_eligible"] == 2
        selected = probe.candidates(
            chain, symbol="TEST", spot=100, expiry="2026-11-06", now=NOW, rv20=.2)
        selected += probe.put_candidates(
            chain, symbol="TEST", spot=100, expiry="2026-11-06", now=NOW, rv20=.2)
        assert pair["pairs_eligible"] == len(selected)
        assert all(row["risk_estimate_usd"] <= 100 for row in selected)
        assert all(row["credit_per_share"] > 0 for row in selected)

    def test_pair_funnel_never_turns_negative_bid_ask_credit_into_trade(self):
        chain = {"options": {"option": [
            option(101, .20, .22), option(102, .21, .23),
        ]}}
        pair = probe.diagnose_spread_pairs(
            chain, symbol="TEST", spot=100, now=NOW)
        assert pair["pairs_considered"] == 1
        assert pair["pairs_nonpositive_credit"] == 1
        assert pair["pairs_eligible"] == 0
        assert probe.candidates(
            chain, symbol="TEST", spot=100, expiry="2026-11-06",
            now=NOW, rv20=.2) == []


if __name__ == "__main__":
    unittest.main()
