"""Synthetic-only tests for selection admissions and missing-outcome bias controls."""
import csv
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import options_population_audit as pop
import options_forward_evaluator as ev

UTC = timezone.utc
ASOF = datetime(2026, 10, 28, 16, tzinfo=UTC)
START = datetime(2026, 1, 5, 16, tzinfo=UTC)


def mark(index=0, *, underlying="TEST", losing=False):
    entry = START + timedelta(days=index * 2)
    exit_time = entry + timedelta(days=1)
    expiry = entry.astimezone(ev.EASTERN).date() + timedelta(days=10)
    occ_date = expiry.strftime("%y%m%d")
    return {
        "trade_id": "SYN_" + underlying + "_" + str(index),
        "underlying": underlying,
        "expiry": expiry.isoformat(),
        "side": "bear_call",
        "decision_utc": entry.isoformat(),
        "entry_utc": entry.isoformat(),
        "entry_quote_utc": (entry - timedelta(seconds=15)).isoformat(),
        "greeks_time_utc": (entry - timedelta(minutes=30)).isoformat(),
        "exit_utc": exit_time.isoformat(),
        "exit_quote_utc": (exit_time - timedelta(seconds=12)).isoformat(),
        "entry_spot": "100",
        "short_strike": "101",
        "long_strike": "102",
        "short_contract": underlying + occ_date + "C00101000",
        "long_contract": underlying + occ_date + "C00102000",
        "entry_short_bid": "1.25",
        "entry_short_ask": "1.27",
        "entry_long_bid": "0.78",
        "entry_long_ask": "0.80",
        "exit_short_bid": "1.48" if losing else "0.19",
        "exit_short_ask": "1.50" if losing else "0.20",
        "exit_long_bid": "0.20" if losing else "0.10",
        "exit_long_ask": "0.21" if losing else "0.11",
        "short_open_interest": "220",
        "long_open_interest": "250",
        "atm_iv": "0.4",
        "rv20": "0.2",
        "multiplier": "100",
    }


def admission(outcome, *, selected=True, reason="DATA_QUALITY"):
    return {
        "trade_id": outcome["trade_id"],
        "underlying": outcome["underlying"],
        "expiry": outcome["expiry"],
        "side": outcome["side"],
        "decision_utc": outcome["decision_utc"],
        "recorded_utc": outcome["decision_utc"],
        "disposition": "SELECTED" if selected else "REJECTED",
        "reject_reason": "" if selected else reason,
    }


class PopulationAuditTests(unittest.TestCase):
    def test_complete_synthetic_population_still_is_not_proof_of_profits(self):
        marks = [mark(i) for i in range(65)]
        admissions = [admission(row) for row in marks]
        result = pop.evaluate_population(admissions, marks, asof=ASOF)
        self.assertEqual(result["status"], "COMPLETE_SUBMITTED_SELECTION_LEDGER_ONLY")
        self.assertEqual(result["selected_signals"], 65)
        self.assertEqual(result["completed_selected_outcomes"], 65)
        self.assertEqual(result["missing_expired_outcomes"], 0)
        self.assertFalse(result["full_candidate_universe_verified"])
        self.assertFalse(result["selection_manifest_timestamp_attested"])
        self.assertEqual(result["edge_verdict"], "UNPROVEN")
        self.assertEqual(result["execution_proof"], "UNVERIFIED")
        paper = result["paper_quote_mark_evaluation"]
        self.assertEqual(paper["status"], "PAPER_ONLY_PROMISING_NOT_VERIFIED")
        self.assertEqual(paper["edge_verdict"], "UNPROVEN")

    def test_omitted_matured_loser_blocks_all_pnl_reporting(self):
        outcomes = [mark(i, losing=i % 6 == 0) for i in range(65)]
        manifest = [admission(row) for row in outcomes]
        kept = outcomes[1:]  # the missing row would have lost money
        result = pop.evaluate_population(manifest, kept, asof=ASOF)
        self.assertEqual(result["status"], "INCOMPLETE_EXPIRED_OUTCOMES")
        self.assertEqual(result["missing_expired_outcomes"], 1)
        self.assertEqual(result["completed_selected_outcomes"], 64)
        self.assertNotIn("paper_quote_mark_evaluation", result)
        self.assertNotIn("mean_net_quote_mark_usd", str(result))

    def test_open_unexpired_signals_block_winner_only_evaluation(self):
        now = ASOF - timedelta(days=1)
        selected = mark()
        selected["trade_id"] = "FUTURE1"
        selected["decision_utc"] = now.isoformat()
        selected["expiry"] = (now.date() + timedelta(days=10)).isoformat()
        result = pop.evaluate_population([admission(selected)], [], asof=ASOF)
        self.assertEqual(result["status"], "PENDING_UNCLOSED_SIGNAL_OUTCOMES")
        self.assertEqual(result["pending_unexpired_outcomes"], 1)
        self.assertNotIn("paper_quote_mark_evaluation", result)

    def test_outcome_not_selected_in_manifest_is_rejected(self):
        row = mark()
        not_selected = admission(row, selected=False)
        with self.assertRaisesRegex(ev.EvidenceError, "previously selected"):
            pop.evaluate_population([not_selected], [row], asof=ASOF)
        with self.assertRaisesRegex(ev.EvidenceError, "previously selected"):
            pop.evaluate_population([], [row], asof=ASOF)

    def test_outcome_cannot_rewrite_underlying_expiry_side_or_decision(self):
        original = mark()
        adm = admission(original)
        for change in (
            {"underlying": "OTHER"},
            {"expiry": "2026-01-16"},
            {"side": "bull_put"},
            {"decision_utc": (START + timedelta(seconds=1)).isoformat()},
        ):
            altered = dict(original, **change)
            with self.assertRaisesRegex(ev.EvidenceError, "contradicts"):
                pop.evaluate_population([adm], [altered], asof=ASOF)

    def test_duplicate_and_unrecognized_disposition_or_rejection_reason(self):
        a = admission(mark())
        with self.assertRaisesRegex(ev.EvidenceError, "Duplicate"):
            pop.evaluate_population([a, a], [], asof=ASOF)
        for change in (
            {"disposition": "AUTO_TRADE"},
            {"disposition": "REJECTED", "reject_reason": ""},
            {"disposition": "SELECTED", "reject_reason": "NO_H1"},
            {"disposition": "REJECTED", "reject_reason": "because it lost"},
        ):
            with self.assertRaises(ev.EvidenceError):
                pop.evaluate_population([dict(a, **change)], [], asof=ASOF)

    def test_selected_must_be_recorded_before_paper_entry(self):
        row = mark()
        adm = admission(row)
        adm["recorded_utc"] = (START + timedelta(seconds=30)).isoformat()
        with self.assertRaisesRegex(ev.EvidenceError, "after its purported"):
            pop.evaluate_population([adm], [row], asof=ASOF)

    def test_future_or_late_selection_memo_fails_closed(self):
        row = mark()
        adm = admission(row)
        for timestamp in (START + timedelta(minutes=3),
                          ASOF + timedelta(days=1),
                          START - timedelta(minutes=1)):
            bad = dict(adm, recorded_utc=timestamp.isoformat())
            with self.assertRaisesRegex(ev.EvidenceError, "timestamp"):
                pop.evaluate_population([bad], [], asof=ASOF)

    def test_rejected_signals_remain_in_population_counts(self):
        rows = [mark(i) for i in range(4)]
        adm = [
            admission(rows[0], selected=True),
            admission(rows[1], selected=False, reason="NO_H1"),
            admission(rows[2], selected=False, reason="ACCOUNT_CAPACITY"),
            admission(rows[3], selected=False, reason="DATA_QUALITY"),
        ]
        report = pop.evaluate_population(adm, [rows[0]], asof=ASOF)
        self.assertEqual(report["selected_signals"], 1)
        self.assertEqual(report["rejected_signals"], 3)
        self.assertEqual(report["rejected_reason_counts"]["NO_H1"], 1)
        self.assertEqual(report["status"], "COMPLETE_SUBMITTED_SELECTION_LEDGER_ONLY")

    def test_empty_vs_all_rejected_are_distinguished(self):
        empty = pop.evaluate_population([], [], asof=ASOF)
        self.assertEqual(empty["status"], "NO_ADMISSION_MANIFEST")
        row = mark()
        rejected = pop.evaluate_population(
            [admission(row, selected=False)], [], asof=ASOF)
        self.assertEqual(rejected["status"], "NO_SELECTED_SIGNALS")

    def test_duplicate_completed_outcomes_do_not_count_twice(self):
        row = mark()
        with self.assertRaisesRegex(ev.EvidenceError, "Duplicate completed"):
            pop.evaluate_population([admission(row)], [row, row], asof=ASOF)

    def test_local_private_cli_outputs_only_aggregate_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            adm_path = Path(folder) / "private_admissions.csv"
            outcome_path = Path(folder) / "private_outcomes.csv"
            row = mark()
            with adm_path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=pop.ADMISSION_COLUMNS)
                writer.writeheader()
                writer.writerow(admission(row))
            with outcome_path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=ev.COLUMNS)
                writer.writeheader()
                writer.writerow(row)
            with patch("sys.stdout", new_callable=io.StringIO) as stdout:
                code = pop.main([
                    "--private-admissions", str(adm_path),
                    "--private-outcomes", str(outcome_path),
                ])
            self.assertEqual(code, 0)
            self.assertIn("UNPROVEN", stdout.getvalue())
            self.assertNotIn("TEST", stdout.getvalue())
            self.assertNotIn("1.25", stdout.getvalue())

    def test_public_repository_manifest_is_rejected(self):
        source = Path(pop.__file__).resolve().parents[1] / "README.md"
        with self.assertRaisesRegex(ev.EvidenceError, "public repository"):
            pop.load_private_admissions(str(source))

    def test_source_is_offline_and_contains_no_broker_account_calls(self):
        source = Path(pop.__file__).read_text(encoding="utf-8")
        self.assertNotIn("api.tradier.com", source)
        self.assertNotIn("/accounts/", source)
        self.assertNotIn("requests.", source)


if __name__ == "__main__":
    unittest.main()
