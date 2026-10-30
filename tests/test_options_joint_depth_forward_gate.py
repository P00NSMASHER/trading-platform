"""Fully synthetic, no-network full-denominator integration acceptance tests."""
from datetime import datetime, timedelta, timezone
import copy
import unittest

from options_joint_depth_forward_gate import audit_joint_depth_forward, JointEvidenceError

UTC = timezone.utc
ASOF = datetime(2026, 10, 30, 5, tzinfo=UTC)
START = datetime(2026, 1, 5, 16, tzinfo=UTC)
SIDES = ("short_bid", "short_ask", "long_bid", "long_ask")


def make_case(i=0, *, underlying="TEST", losing=False):
    entry = START + timedelta(days=2*i)
    decision = entry
    exit_time = entry + timedelta(days=1)
    expiry = (entry.date() + timedelta(days=10))
    right = "C"
    short = underlying + expiry.strftime("%y%m%d") + right + "00101000"
    long = underlying + expiry.strftime("%y%m%d") + right + "00102000"
    short_bid, short_ask = ("1.25", "1.27")
    long_bid, long_ask = ("0.78", "0.80")
    values = {
        "entry_short_bid": short_bid, "entry_short_ask": short_ask,
        "entry_long_bid": long_bid, "entry_long_ask": long_ask,
        "exit_short_bid": "1.48" if losing else "0.19",
        "exit_short_ask": "1.50" if losing else "0.20",
        "exit_long_bid": "0.20" if losing else "0.10",
        "exit_long_ask": "0.21" if losing else "0.11",
    }
    # The quotes are entirely imaginary. All timestamps are explicit and UTC.
    paper = {
        "trade_id": f"SYNTHETIC_{i}_{underlying}",
        "underlying": underlying,
        "expiry": expiry.isoformat(),
        "side": "bear_call",
        "decision_utc": decision.isoformat(),
        "entry_utc": entry.isoformat(),
        "entry_quote_utc": (entry - timedelta(seconds=15)).isoformat(),
        "greeks_time_utc": (entry - timedelta(minutes=45)).isoformat(),
        "exit_utc": exit_time.isoformat(),
        "exit_quote_utc": (exit_time - timedelta(seconds=15)).isoformat(),
        "entry_spot": "100", "short_strike": "101", "long_strike": "102",
        "short_contract": short, "long_contract": long,
        "short_open_interest": "200", "long_open_interest": "250",
        "atm_iv": "0.40", "rv20": "0.20", "multiplier": "100",
        **values,
    }
    depth = {"trade_id": paper["trade_id"], "short_contract": short, "long_contract": long}
    for event in ("entry", "exit"):
        source = datetime.fromisoformat(paper[event + "_quote_utc"])
        for side in SIDES:
            key = event + "_" + side
            depth[key + "_px"] = values[key]
            depth[key + "_size"] = "1"
            depth[key + "_utc"] = (source - timedelta(seconds=2)).isoformat()
    return paper, depth


class JointGateTests(unittest.TestCase):
    def test_empty_is_not_an_edge(self):
        result = audit_joint_depth_forward([], [], asof=ASOF)
        self.assertEqual(result["status"], "NO_COMPLETED_EVIDENCE")
        self.assertEqual(result["edge_verdict"], "UNPROVEN")

    def test_valid_but_small_sample_not_promoted(self):
        paper, depth = make_case()
        r = audit_joint_depth_forward([paper], [depth], asof=ASOF)
        self.assertEqual(r["status"], "FORWARD_EVIDENCE_NOT_POSITIVE")
        self.assertEqual(r["depth_verified_quote_rows"], 1)
        self.assertFalse(r["market_provenance_attested"])

    def test_one_bad_book_blocks_full_population(self):
        p1, d1 = make_case()
        p2, d2 = make_case(1)
        d2["exit_long_bid_size"] = "0"
        r = audit_joint_depth_forward([p1, p2], [d1, d2], asof=ASOF)
        self.assertEqual(r["status"], "QUOTE_DEPTH_BLOCKED")
        self.assertEqual(r["submitted_marks"], 2)
        self.assertEqual(r["depth_verified_quote_rows"], 1)
        self.assertNotIn("net_quote_mark_scenarios", r)

    def test_no_cherry_pick_when_depth_missing(self):
        p1, d1 = make_case()
        p2, _ = make_case(1)
        with self.assertRaisesRegex(JointEvidenceError, "Quote-depth population rejected"):
            audit_joint_depth_forward([p1, p2], [d1], asof=ASOF)

    def test_contract_substitution_blocks_all_quotes(self):
        p, d = make_case()
        d["short_contract"] = "TEST261115C00101000"
        r = audit_joint_depth_forward([p], [d], asof=ASOF)
        self.assertEqual(r["status"], "QUOTE_DEPTH_BLOCKED")

    def test_bad_oi_rejected_by_canonical_evaluator(self):
        p, d = make_case()
        p["short_open_interest"] = "0"
        with self.assertRaisesRegex(JointEvidenceError, "Canonical paper population rejected"):
            audit_joint_depth_forward([p], [d], asof=ASOF)

    def test_future_exit_rejected(self):
        p, d = make_case()
        with self.assertRaisesRegex(JointEvidenceError, "Canonical paper population rejected"):
            audit_joint_depth_forward([p], [d], asof=START)

    def test_two_symbols_over_risk_even_with_good_depth_and_small_sample(self):
        p1, d1 = make_case(0, underlying="TEST")
        p2, d2 = make_case(0, underlying="PAIR")
        r = audit_joint_depth_forward([p1, p2], [d1, d2], asof=ASOF)
        self.assertEqual(r["max_simultaneous_modeled_risk_usd"], 115.2)
        self.assertEqual(r["status"], "ACCOUNT_RISK_BLOCKED")

    def test_adequate_but_completely_synthetic_profitable_marks_are_never_proven(self):
        cases = [make_case(i) for i in range(65)]
        p, d = zip(*cases)
        r = audit_joint_depth_forward(p, d, asof=ASOF)
        self.assertEqual(r["status"], "PAPER_QUOTE_SCREEN_ONLY")
        self.assertEqual(r["edge_verdict"], "UNPROVEN")
        self.assertEqual(r["execution_proof"], "UNVERIFIED")
        self.assertFalse(r["assignment_risk_calibrated"])

    def test_synthetic_losing_cohort_not_positive(self):
        cases = [make_case(i, losing=True) for i in range(65)]
        p, d = zip(*cases)
        r = audit_joint_depth_forward(p, d, asof=ASOF)
        self.assertEqual(r["status"], "FORWARD_EVIDENCE_NOT_POSITIVE")

    def test_order_permutation_same_aggregate(self):
        cases = [make_case(i) for i in range(4)]
        p, d = map(list, zip(*cases))
        first = audit_joint_depth_forward(p, d, asof=ASOF)
        second = audit_joint_depth_forward(list(reversed(p)), list(reversed(d)), asof=ASOF)
        self.assertEqual(first, second)

    def test_raw_private_values_not_echoed(self):
        p, d = make_case()
        d["entry_short_ask_px"] = "PRIVATE_QUOTE_MARK_7419"
        with self.assertRaises(JointEvidenceError) as e:
            audit_joint_depth_forward([p], [d], asof=ASOF)
        self.assertNotIn("PRIVATE_QUOTE_MARK_7419", str(e.exception))

    def test_reject_no_cutoff_or_non_sequence(self):
        with self.assertRaises(JointEvidenceError):
            audit_joint_depth_forward([], [], asof=None)
        with self.assertRaises(JointEvidenceError):
            audit_joint_depth_forward(iter([]), [], asof=ASOF)

    def test_no_network_or_order_code(self):
        from pathlib import Path
        import options_joint_depth_forward_gate as g
        s = Path(g.__file__).read_text()
        for forbidden in ("requests.", "api.tradier.com", "/accounts/", "os.environ", "Authorization"):
            self.assertNotIn(forbidden, s)


if __name__ == "__main__":
    unittest.main()
