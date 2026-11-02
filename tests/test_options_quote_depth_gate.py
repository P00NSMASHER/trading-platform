"""Deterministic no-network, all-synthetic adverse-book controls."""
from datetime import datetime, timedelta, timezone
import copy
import unittest

from options_quote_depth_gate import audit_quote_depth, DepthError

UTC = timezone.utc
T0 = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)
ASOF = datetime(2026, 10, 30, 4, 0, tzinfo=UTC)
SIDES = ("short_bid", "short_ask", "long_bid", "long_ask")
VALUES = {"short_bid": "1.25", "short_ask": "1.27", "long_bid": "0.78", "long_ask": "0.80"}


def row(i=0):
    decision = T0 + timedelta(minutes=3 * i)
    entry = decision + timedelta(seconds=15)
    entry_quote = decision - timedelta(seconds=5)
    exit_time = entry + timedelta(hours=23)
    exit_quote = exit_time - timedelta(seconds=5)
    paper = {"trade_id": "SYNTHETIC_" + str(i),
             "decision_utc": decision.isoformat(), "entry_utc": entry.isoformat(),
             "entry_quote_utc": entry_quote.isoformat(),
             "exit_utc": exit_time.isoformat(), "exit_quote_utc": exit_quote.isoformat()}
    # Fabricated but OCC-shaped, unique and stable across entry/exit.
    paper["short_contract"] = "SPY261113C00660000"
    paper["long_contract"] = "SPY261113C00661000"
    depth = {"trade_id": paper["trade_id"],
             "short_contract": paper["short_contract"],
             "long_contract": paper["long_contract"]}
    for event, stamp in (("entry", entry_quote), ("exit", exit_quote)):
        for side in SIDES:
            key = event + "_" + side
            paper[key] = VALUES[side]
            depth[key + "_size"] = "1"
            depth[key + "_px"] = VALUES[side]
            depth[key + "_utc"] = (stamp - timedelta(seconds=2)).isoformat()
    return paper, depth


class DepthTests(unittest.TestCase):
    def test_valid_book_is_screen_only_not_broker_fill(self):
        p, d = row()
        result = audit_quote_depth([p], [d], asof=ASOF)
        self.assertEqual(result["status"], "QUOTE_DEPTH_SCREEN_ONLY")
        self.assertFalse(result["actual_fill_proof"])
        self.assertEqual(result["edge_verdict"], "UNPROVEN")

    def test_one_zero_bid_size_blocks_entire_cohort(self):
        a, b = row()
        c, d = row(1)
        d["entry_short_bid_size"] = "0"
        result = audit_quote_depth([a, c], [b, d], asof=ASOF)
        self.assertEqual(result["status"], "DEPTH_SCREEN_BLOCKED")
        self.assertEqual(result["reason_counts"], {"INSUFFICIENT_DEPTH": 1})

    def test_missing_loser_depth_does_not_leave_winners(self):
        a, b = row()
        c, _ = row(1)
        with self.assertRaisesRegex(DepthError, "exactly cover"):
            audit_quote_depth([a, c], [b], asof=ASOF)

    def test_price_mismatch_blocks(self):
        p, d = row()
        d["exit_short_ask_px"] = "0.01"
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"PRICE_MISMATCH": 1})

    def test_millisecond_quote_skew_counterexample(self):
        p, d = row()
        dt = datetime.fromisoformat(d["exit_short_ask_utc"])
        d["exit_short_ask_utc"] = (dt - timedelta(seconds=35)).isoformat()
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"UNSYNCHRONIZED_BOOK": 1})

    def test_source_quote_update_after_decision_blocks_lookahead(self):
        p, d = row()
        d["entry_short_bid_utc"] = (T0 + timedelta(seconds=1)).isoformat()
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"FUTURE_SIDE_UPDATE": 1})

    def test_stale_bid_update_blocks(self):
        p, d = row()
        d["entry_short_bid_utc"] = (T0 - timedelta(minutes=3)).isoformat()
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"STALE_SIDE_UPDATE": 1})

    def test_one_missing_depth_field_blocks(self):
        p, d = row()
        del d["exit_long_ask_size"]
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"MISSING_SIDE": 1})

    def test_rejected_late_or_future_capture(self):
        p, d = row()
        p["entry_quote_utc"] = (T0 + timedelta(seconds=1)).isoformat()
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"CLOCK_INCOHERENT": 1})

    def test_entry_before_signal_is_not_depth_eligible(self):
        p, d = row()
        decision = datetime.fromisoformat(p["entry_utc"]) + timedelta(seconds=2)
        p["decision_utc"] = decision.isoformat()
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"CLOCK_INCOHERENT": 1})

    def test_signal_after_outcome_is_not_depth_eligible(self):
        p, d = row()
        decision = datetime.fromisoformat(p["exit_utc"]) + timedelta(seconds=1)
        p["decision_utc"] = decision.isoformat()
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"CLOCK_INCOHERENT": 1})

    def test_equal_entry_exit_is_not_depth_eligible(self):
        p, d = row()
        p["exit_utc"] = p["entry_utc"]
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"CLOCK_INCOHERENT": 1})

    def test_chronological_control_remains_quote_only(self):
        p, d = row()
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["status"],
                         "QUOTE_DEPTH_SCREEN_ONLY")

    def test_identical_prices_cannot_pass_from_wrong_contract(self):
        p, d = row()
        # v0.6 accepted this substitute OCC quote: timestamps and prices
        # were identical and the ID still matched the paper mark.
        d["short_contract"] = "SPY261113C00662000"
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"CONTRACT_MISMATCH": 1})

    def test_missing_contract_binding_is_all_cohort_blocker(self):
        p, d = row()
        p2, d2 = row(1)
        d2.pop("long_contract")
        report = audit_quote_depth([p, p2], [d, d2], asof=ASOF)
        self.assertEqual(report["status"], "DEPTH_SCREEN_BLOCKED")
        self.assertEqual(report["verified_quote_depth_rows"], 1)
        self.assertEqual(report["reason_counts"],
                         {"MISSING_CONTRACT_BINDING": 1})

    def test_identical_spread_legs_rejected(self):
        p, d = row()
        p["long_contract"] = d["long_contract"] = p["short_contract"]
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"CONTRACT_MISMATCH": 1})

    def test_non_occ_identity_rejected_even_when_consistent(self):
        p, d = row()
        p["short_contract"] = d["short_contract"] = "NON_OCC"
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"INVALID_CONTRACT_BINDING": 1})

    def test_contract_binding_never_echoes_private_symbol(self):
        p, d = row()
        d["short_contract"] = "PRIVATE_CONTRACT_MARKER_75431"
        report = audit_quote_depth([p], [d], asof=ASOF)
        self.assertEqual(report["status"], "DEPTH_SCREEN_BLOCKED")
        self.assertNotIn("PRIVATE_CONTRACT_MARKER_75431", str(report))

    def test_crossed_entry_short_leg_blocks_false_credit(self):
        p, d = row()
        p["entry_short_bid"] = d["entry_short_bid_px"] = "2.00"
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"CROSSED_LEG_BOOK": 1})

    def test_crossed_exit_long_leg_blocks_impossible_book(self):
        p, d = row()
        p["exit_long_bid"] = d["exit_long_bid_px"] = "2.00"
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"CROSSED_LEG_BOOK": 1})

    def test_zero_ask_is_not_firm_executable_quote(self):
        p, d = row()
        p["entry_long_ask"] = d["entry_long_ask_px"] = "0"
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["reason_counts"],
                         {"NONPOSITIVE_ASK": 1})

    def test_locked_leg_book_is_not_automatically_crossed(self):
        p, d = row()
        p["entry_short_bid"] = d["entry_short_bid_px"] = "1.27"
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF)["status"],
                         "QUOTE_DEPTH_SCREEN_ONLY")

    def test_crossed_market_blocks_whole_population(self):
        ps, ds = list(zip(*(row(i) for i in range(10))))
        ps, ds = list(ps), list(ds)
        ps[9]["entry_short_bid"] = ds[9]["entry_short_bid_px"] = "2.00"
        result = audit_quote_depth(ps, ds, asof=ASOF)
        self.assertEqual(result["status"], "DEPTH_SCREEN_BLOCKED")
        self.assertEqual(result["verified_quote_depth_rows"], 9)
        self.assertEqual(result["submitted_marks"], 10)

    def test_reject_duplicate_evidence_ids(self):
        p, d = row()
        with self.assertRaisesRegex(DepthError, "Duplicate"):
            audit_quote_depth([p, p], [d], asof=ASOF)

    def test_reject_bad_depth_and_contracts(self):
        p, d = row()
        d["entry_long_ask_size"] = "1.25"
        with self.assertRaisesRegex(DepthError, "depth"):
            audit_quote_depth([p], [d], asof=ASOF)
        p, d = row()
        self.assertEqual(audit_quote_depth([p], [d], asof=ASOF, contracts=2)["status"],
                         "DEPTH_SCREEN_BLOCKED")

    def test_no_raw_sensitive_values_in_errors_or_output(self):
        p, d = row()
        d["entry_long_ask_px"] = "PRIVATE_MARKER_987"
        with self.assertRaises(DepthError) as caught:
            audit_quote_depth([p], [d], asof=ASOF)
        self.assertNotIn("PRIVATE_MARKER_987", str(caught.exception))

    def test_same_input_is_reproducible(self):
        ps, ds = zip(*(row(i) for i in range(100)))
        first = audit_quote_depth(ps, ds, asof=ASOF)
        second = audit_quote_depth(ps, ds, asof=ASOF)
        self.assertEqual(first, second)
        self.assertEqual(first["submitted_marks"], 100)

    def test_empty_is_not_positive_evidence(self):
        result = audit_quote_depth([], [], asof=ASOF)
        self.assertEqual(result["status"], "NO_PAPER_MARKS")

    def test_no_ordering_or_broker_network_code(self):
        from pathlib import Path
        import options_quote_depth_gate as g
        s = Path(g.__file__).read_text()
        self.assertNotIn("requests.", s)
        self.assertNotIn("api.tradier.com", s)
        self.assertNotIn("/accounts/", s)


if __name__ == "__main__":
    unittest.main()
