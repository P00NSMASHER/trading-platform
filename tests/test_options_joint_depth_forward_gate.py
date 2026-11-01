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
    # Weekday-only SYNTHETIC timing: two weekdays between entries, never
    # imply weekend quote availability. Exchange holidays are not modeled.
    entry = START
    weekday_steps = 0
    while weekday_steps < 2 * i:
        entry += timedelta(days=1)
        if entry.weekday() < 5:
            weekday_steps += 1
    decision = entry
    exit_time = entry + timedelta(days=1)
    while exit_time.weekday() >= 5:
        exit_time += timedelta(days=1)
    expiry = entry.date() + timedelta(days=(4 - entry.weekday()) % 7 + 7)
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

    def test_inverted_cross_leg_exit_blocks_quote_only_illusion(self):
        p, d = make_case()
        # Each individual leg is uncrossed and within its spread limit,
        # but short ask $0.05 < long bid $0.10; no executable debit is proven.
        p["exit_short_bid"] = d["exit_short_bid_px"] = "0.04"
        p["exit_short_ask"] = d["exit_short_ask_px"] = "0.05"
        with self.assertRaisesRegex(JointEvidenceError, "Cross-leg exit"):
            audit_joint_depth_forward([p], [d], asof=ASOF)

    def test_one_inverted_package_rejects_whole_65_mark_cohort(self):
        cases = [make_case(i) for i in range(65)]
        p, d = map(list, zip(*cases))
        p[-1]["exit_short_bid"] = d[-1]["exit_short_bid_px"] = "0.04"
        p[-1]["exit_short_ask"] = d[-1]["exit_short_ask_px"] = "0.05"
        with self.assertRaisesRegex(JointEvidenceError, "Cross-leg exit"):
            audit_joint_depth_forward(p, d, asof=ASOF)

    @staticmethod
    def _set_expiry_day_clock(p, d, *, utc_rollover=False):
        expiry = datetime.fromisoformat(p["expiry"])
        if utc_rollover:
            # UTC calendar has rolled, but 01:30Z is 20:30 EST expiry day.
            event = (expiry + timedelta(days=1)).replace(
                hour=1, minute=30, tzinfo=UTC)
        else:
            event = expiry.replace(hour=19, minute=45, tzinfo=UTC)
        p["exit_utc"] = event.isoformat()
        p["exit_quote_utc"] = (event - timedelta(seconds=15)).isoformat()
        for side in SIDES:
            d["exit_" + side + "_utc"] = (
                event - timedelta(seconds=17)).isoformat()

    def test_expiry_day_call_quote_and_utc_rollover_rejected(self):
        for rollover in (False, True):
            p, d = make_case()
            self._set_expiry_day_clock(p, d, utc_rollover=rollover)
            with self.assertRaisesRegex(JointEvidenceError, "Expiry-day quote mark"):
                audit_joint_depth_forward([p], [d], asof=ASOF)

    def test_expiry_day_put_quote_rejected(self):
        p, d = make_case()
        p["side"] = "bull_put"
        p["entry_spot"] = "103"
        p["short_strike"] = "101"
        p["long_strike"] = "100"
        p["short_contract"] = p["short_contract"].replace(
            "C00101000", "P00101000")
        p["long_contract"] = p["long_contract"].replace(
            "C00102000", "P00100000")
        d["short_contract"] = p["short_contract"]
        d["long_contract"] = p["long_contract"]
        self._set_expiry_day_clock(p, d)
        with self.assertRaisesRegex(JointEvidenceError, "Expiry-day quote mark"):
            audit_joint_depth_forward([p], [d], asof=ASOF)

    def test_expiry_day_mark_blocks_whole_65_mark_cohort(self):
        cases = [make_case(i) for i in range(65)]
        p, d = map(list, zip(*cases))
        self._set_expiry_day_clock(p[-1], d[-1])
        with self.assertRaisesRegex(JointEvidenceError, "Expiry-day quote mark"):
            audit_joint_depth_forward(p, d, asof=ASOF)

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

    @staticmethod
    def _retime(paper, depth, event, at):
        paper[event + "_utc"] = at.isoformat()
        paper[event + "_quote_utc"] = (at - timedelta(seconds=15)).isoformat()
        if event == "entry":
            paper["decision_utc"] = at.isoformat()
            paper["greeks_time_utc"] = (at - timedelta(minutes=45)).isoformat()
        for side in SIDES:
            depth[event + "_" + side + "_utc"] = (
                at - timedelta(seconds=17)
            ).isoformat()

    def test_weekend_entry_is_not_a_quote_fill(self):
        p, d = make_case()
        self._retime(p, d, "entry", datetime(2026, 1, 4, 16, tzinfo=UTC))
        with self.assertRaisesRegex(JointEvidenceError, "Regular-session"):
            audit_joint_depth_forward([p], [d], asof=ASOF)

    def test_weekend_exit_is_not_a_quote_fill(self):
        p, d = make_case()
        self._retime(p, d, "exit", datetime(2026, 1, 10, 16, tzinfo=UTC))
        with self.assertRaisesRegex(JointEvidenceError, "Regular-session"):
            audit_joint_depth_forward([p], [d], asof=ASOF)

    def test_premarket_entry_is_not_a_quote_fill(self):
        p, d = make_case()
        self._retime(p, d, "entry", datetime(2026, 1, 5, 14, tzinfo=UTC))
        with self.assertRaisesRegex(JointEvidenceError, "Regular-session"):
            audit_joint_depth_forward([p], [d], asof=ASOF)

    def test_afterhours_exit_is_not_a_quote_fill(self):
        p, d = make_case()
        self._retime(p, d, "exit", datetime(2026, 1, 6, 1, tzinfo=UTC))
        with self.assertRaisesRegex(JointEvidenceError, "Regular-session"):
            audit_joint_depth_forward([p], [d], asof=ASOF)

    def test_side_timestamp_premarket_is_not_rehabilitated_by_open_quote(self):
        p, d = make_case()
        opening = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
        self._retime(p, d, "entry", opening)
        p["entry_quote_utc"] = opening.isoformat()
        for side in SIDES:
            d["entry_" + side + "_utc"] = (
                opening - timedelta(seconds=2)
            ).isoformat()
        with self.assertRaisesRegex(JointEvidenceError, "Regular-session"):
            audit_joint_depth_forward([p], [d], asof=ASOF)

    def test_one_weekend_exit_blocks_all_65_synthetic_marks(self):
        cases = [make_case(i) for i in range(65)]
        p, d = map(list, zip(*cases))
        # Last mark enters Thursday in the synthetic schedule; Saturday exit
        # remains before the later Friday contract expiry.
        self._retime(p[-1], d[-1], "exit",
                     datetime(2026, 7, 4, 16, tzinfo=UTC))
        with self.assertRaisesRegex(JointEvidenceError, "Regular-session"):
            audit_joint_depth_forward(p, d, asof=ASOF)

    def test_no_network_or_order_code(self):
        from pathlib import Path
        import options_joint_depth_forward_gate as g
        s = Path(g.__file__).read_text()
        for forbidden in ("requests.", "api.tradier.com", "/accounts/", "os.environ", "Authorization"):
            self.assertNotIn(forbidden, s)


if __name__ == "__main__":
    unittest.main()
