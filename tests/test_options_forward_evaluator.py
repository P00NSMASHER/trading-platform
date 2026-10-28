"""No-network tests for private-only forward options evidence and false-edge gates."""
import csv
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import options_forward_evaluator as ev

UTC = timezone.utc
ASOF = datetime(2026, 10, 28, 16, tzinfo=UTC)
START = datetime(2026, 1, 5, 16, tzinfo=UTC)


def synthetic_row(index=0, *, losing=False, underlying="TEST"):
    entry = START + timedelta(days=2 * index)
    exit_time = entry + timedelta(days=1)
    day = entry.astimezone(ev.EASTERN).date()
    return {
        "trade_id": "SYNTHETIC_" + str(index) + "_" + underlying,
        "underlying": underlying,
        "expiry": (day + timedelta(days=10)).isoformat(),
        "side": "bear_call",
        "decision_utc": entry.isoformat(),
        "entry_utc": entry.isoformat(),
        "entry_quote_utc": (entry - timedelta(seconds=15)).isoformat(),
        "greeks_time_utc": (entry - timedelta(minutes=45)).isoformat(),
        "exit_utc": exit_time.isoformat(),
        "exit_quote_utc": (exit_time - timedelta(seconds=15)).isoformat(),
        "entry_spot": "100",
        "short_strike": "101",
        "long_strike": "102",
        "short_contract": underlying + (day + timedelta(days=10)).strftime("%y%m%d") + "C00101000",
        "long_contract": underlying + (day + timedelta(days=10)).strftime("%y%m%d") + "C00102000",
        "entry_short_bid": "1.25",
        "entry_short_ask": "1.27",
        "entry_long_bid": "0.78",
        "entry_long_ask": "0.80",
        "exit_short_bid": "1.48" if losing else "0.19",
        "exit_short_ask": "1.50" if losing else "0.20",
        "exit_long_bid": "0.20" if losing else "0.10",
        "exit_long_ask": "0.21" if losing else "0.11",
        "short_open_interest": "200",
        "long_open_interest": "250",
        "atm_iv": "0.40",
        "rv20": "0.20",
        "multiplier": "100",
    }


class ForwardEvidenceTests(unittest.TestCase):
    def test_valid_example_is_quote_mark_not_broker_fill(self):
        mark = ev.parse_paper_mark(synthetic_row(), asof=ASOF)
        self.assertEqual(mark.modeled_risk_usd, 57.6)
        self.assertEqual(mark.quote_mark_pnl_before_costs_usd, 35)
        self.assertEqual(mark.underlying, "TEST")

    def test_small_winning_sample_never_claims_positive_edge(self):
        report = ev.evaluate_paper_marks(
            [synthetic_row(i) for i in range(5)], asof=ASOF)
        self.assertEqual(report["status"], "INSUFFICIENT_FORWARD_EVIDENCE")
        self.assertEqual(report["edge_verdict"], "UNPROVEN")
        self.assertEqual(report["execution_proof"], "UNVERIFIED")
        self.assertEqual(report["completed_marks"], 5)
        self.assertEqual(report["net_quote_mark_scenarios"]["0"]["mean_net_quote_mark_usd"], 32.4)
        self.assertEqual(report["net_quote_mark_scenarios"]["5"]["mean_net_quote_mark_usd"], 27.4)
        self.assertEqual(report["net_quote_mark_scenarios"]["10"]["mean_net_quote_mark_usd"], 22.4)

    def test_robust_synthetic_wins_are_never_labeled_execution_verified(self):
        report = ev.evaluate_paper_marks(
            [synthetic_row(i) for i in range(65)], asof=ASOF)
        self.assertEqual(report["status"], "PAPER_ONLY_PROMISING_NOT_VERIFIED")
        self.assertEqual(report["edge_verdict"], "UNPROVEN")
        self.assertFalse(report["actual_broker_fills_verified"])
        self.assertFalse(report["source_selection_preregistered_verified"])
        self.assertEqual(report["completed_marks"], 65)
        self.assertGreaterEqual(report["independent_entry_weeks"], 12)
        self.assertGreaterEqual(report["entry_span_days"], 90)
        self.assertLessEqual(report["max_simultaneous_modeled_risk_usd"], 100)
        self.assertGreater(
            report["net_quote_mark_scenarios"]["5"]["weekly_cluster_bootstrap95_usd"][0], 0)

    def test_losses_no_cherry_picked_wins(self):
        report = ev.evaluate_paper_marks(
            [synthetic_row(i, losing=True) for i in range(65)], asof=ASOF)
        self.assertEqual(report["status"], "NO_POSITIVE_NET_EVIDENCE")
        self.assertLess(report["net_quote_mark_scenarios"]["5"]["mean_net_quote_mark_usd"], 0)
        self.assertGreater(report["net_quote_mark_scenarios"]["5"]["max_exit_mark_drawdown_usd"], 0)

    def test_overlap_across_symbols_exceeds_small_account_capacity(self):
        rows = []
        for i in range(65):
            rows.append(synthetic_row(i, underlying="TEST"))
            rows.append(synthetic_row(i, underlying="PAIR"))
        report = ev.evaluate_paper_marks(rows, asof=ASOF)
        self.assertEqual(report["status"], "ACCOUNT_RISK_CAPACITY_EXCEEDED")
        self.assertEqual(report["max_simultaneous_modeled_risk_usd"], 115.2)

    def test_reject_duplicate_ids_and_correlated_strike_optimizations(self):
        row = synthetic_row()
        with self.assertRaisesRegex(ev.EvidenceError, "Duplicate"):
            ev.evaluate_paper_marks([row, row], asof=ASOF)
        another = dict(row, trade_id="ANOTHER")
        with self.assertRaisesRegex(ev.EvidenceError, "Correlated"):
            ev.evaluate_paper_marks([row, another], asof=ASOF)

    def test_reject_overlapping_same_underlying_positions(self):
        a = synthetic_row()
        b = synthetic_row(1)
        # Extend first synthetic trade beyond the second entry date.
        exit_time = START + timedelta(days=3)
        a["exit_utc"] = exit_time.isoformat()
        a["exit_quote_utc"] = (exit_time - timedelta(seconds=10)).isoformat()
        with self.assertRaisesRegex(ev.EvidenceError, "Overlapping"):
            ev.evaluate_paper_marks([a, b], asof=ASOF)

    def test_future_exit_and_missing_eligible_quote_must_fail_closed(self):
        bad = synthetic_row()
        bad["exit_utc"] = (ASOF + timedelta(days=1)).isoformat()
        bad["exit_quote_utc"] = (ASOF + timedelta(days=1, seconds=-5)).isoformat()
        with self.assertRaisesRegex(ev.EvidenceError, "beyond"):
            ev.evaluate_paper_marks([bad], asof=ASOF)
        for key in ("entry_short_bid", "entry_long_ask", "exit_short_ask"):
            bad = synthetic_row()
            bad[key] = ""
            with self.assertRaises(ev.EvidenceError):
                ev.evaluate_paper_marks([bad], asof=ASOF)

    def test_cannot_look_ahead_or_accept_stale_greeks_or_quotes(self):
        for field, minutes in (("greeks_time_utc", -92), ("entry_quote_utc", -3),
                               ("exit_quote_utc", -3), ("entry_quote_utc", 3)):
            row = synthetic_row()
            reference = START if field != "exit_quote_utc" else START + timedelta(days=1)
            row[field] = (reference + timedelta(minutes=minutes)).isoformat()
            with self.assertRaisesRegex(ev.EvidenceError, "stale|future|decision"):
                ev.evaluate_paper_marks([row], asof=ASOF)

    def test_h1_and_trade_safety_reject_bad_contracts(self):
        for key, value in (
            ("atm_iv", "0.10"), ("rv20", "0.50"),
            ("multiplier", "10"), ("short_strike", "99"),
            ("long_strike", "108"), ("long_open_interest", "0"),
            ("entry_long_ask", "1.26"), ("short_open_interest", "99"),
            ("side", "naked_call"),
        ):
            row = synthetic_row()
            row[key] = value
            with self.assertRaises(ev.EvidenceError):
                ev.evaluate_paper_marks([row], asof=ASOF)


    def test_full_option_quotes_must_be_liquid_on_both_sides_at_both_times(self):
        for key, value in (
            ("entry_short_ask", "1.24"),
            ("entry_long_bid", "0.99"),
            ("exit_short_bid", "0.45"),
            ("exit_long_ask", "0.75"),
        ):
            row = synthetic_row()
            row[key] = value
            with self.assertRaisesRegex(
                ev.EvidenceError, "Crossed|liquidity"
            ):
                ev.evaluate_paper_marks([row], asof=ASOF)

    def test_decision_quote_cannot_arrive_after_signal_was_made(self):
        row = synthetic_row()
        row["decision_utc"] = (START - timedelta(seconds=20)).isoformat()
        with self.assertRaisesRegex(ev.EvidenceError, "decision"):
            ev.evaluate_paper_marks([row], asof=ASOF)
        row = synthetic_row()
        row["decision_utc"] = (START - timedelta(minutes=3)).isoformat()
        row["entry_quote_utc"] = (START - timedelta(minutes=4)).isoformat()
        with self.assertRaisesRegex(ev.EvidenceError, "decision"):
            ev.evaluate_paper_marks([row], asof=ASOF)


    def test_occ_contracts_must_match_quote_expiry_type_and_strike(self):
        for key, val in (
            ("short_contract", "TEST260115P00101000"),
            ("short_contract", "OTHER260115C00101000"),
            ("short_contract", "TEST260122C00101000"),
            ("short_contract", "TEST260115C00100000"),
            ("long_contract", "TEST260115C00101000"),
        ):
            row = synthetic_row()
            row[key] = val
            with self.assertRaises(ev.EvidenceError):
                ev.evaluate_paper_marks([row], asof=ASOF)

    def test_bull_put_occ_identity_and_risk_are_checked_too(self):
        row = synthetic_row()
        row["side"] = "bull_put"
        row["short_strike"] = "99"
        row["long_strike"] = "98"
        row["short_contract"] = "TEST260115P00099000"
        row["long_contract"] = "TEST260115P00098000"
        mark = ev.parse_paper_mark(row, asof=ASOF)
        self.assertEqual(mark.side, "bull_put")
        self.assertAlmostEqual(mark.modeled_risk_usd, 57.60)

    def test_expiry_and_dte_fail_closed(self):
        for d in (1, 6, 22):
            row = synthetic_row()
            row["expiry"] = (START.date() + timedelta(days=d)).isoformat()
            with self.assertRaisesRegex(ev.EvidenceError, "7-21"):
                ev.evaluate_paper_marks([row], asof=ASOF)

    def test_week_bootstrap_reproducible(self):
        rows = [synthetic_row(i, losing=(i % 8 == 0)) for i in range(65)]
        first = ev.evaluate_paper_marks(rows, asof=ASOF)
        second = ev.evaluate_paper_marks(rows, asof=ASOF)
        self.assertEqual(first, second)
        self.assertEqual(first["uncertainty_method"],
                         "DETERMINISTIC_ENTRY_WEEK_CLUSTER_BOOTSTRAP")

    def test_empty_input_is_explicit_not_a_profitable_result(self):
        report = ev.evaluate_paper_marks([], asof=ASOF)
        self.assertEqual(report["status"], "NO_COMPLETED_PAPER_MARKS")
        self.assertEqual(report["edge_verdict"], "UNPROVEN")

    def test_local_private_csv_parses_without_public_quote_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "private_quotes.csv"
            with source.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=ev.COLUMNS)
                writer.writeheader()
                writer.writerow(synthetic_row())
            loaded = ev.load_private_csv(str(source))
            self.assertEqual(len(loaded), 1)
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                result = ev.main(["--private-csv", str(source)])
            self.assertEqual(result, 0)
            self.assertNotIn("TEST", stdout.getvalue())
            self.assertNotIn("1.25", stdout.getvalue())
            self.assertIn("UNPROVEN", stdout.getvalue())

    def test_public_repo_copy_is_rejected_even_if_file_exists(self):
        source = Path(ev.__file__).resolve().parents[1] / "README.md"
        with self.assertRaisesRegex(ev.EvidenceError, "public repository"):
            ev.load_private_csv(str(source))

    def test_bad_input_must_not_echo_sensitive_value(self):
        row = synthetic_row()
        row["entry_short_bid"] = "SECRET_MARKER_TRADE_789"
        with self.assertRaises(ev.EvidenceError) as raised:
            ev.evaluate_paper_marks([row], asof=ASOF)
        self.assertNotIn("SECRET_MARKER_TRADE_789", str(raised.exception))

    def test_no_hardcoded_real_trade_or_order_endpoint(self):
        source = Path(ev.__file__).read_text(encoding="utf-8")
        self.assertNotIn("api.tradier.com", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("/accounts/", source)


if __name__ == "__main__":
    unittest.main()
