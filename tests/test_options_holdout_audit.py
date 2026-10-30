"""Synthetic-only no-network tests for private temporal holdout auditing."""
from datetime import datetime, timedelta, timezone
import unittest

import options_forward_evaluator as forward
import options_holdout_audit as audit
from test_options_forward_evaluator import synthetic_row, ASOF, START

UTC = timezone.utc
BOUNDARY = datetime(2026, 4, 15, 16, tzinfo=UTC)


class TemporalHoldoutTests(unittest.TestCase):
    def test_untouched_chronology_and_embargo_are_disjoint(self):
        rows = [synthetic_row(i) for i in range(120)]
        result = audit.evaluate_holdout(rows, holdout_start=BOUNDARY, asof=ASOF)
        self.assertEqual(result["population_rows"], 120)
        self.assertEqual(result["population_rows"],
                         result["development_rows"] +
                         result["withheld_pre_holdout_rows"] +
                         result["holdout_rows"])
        self.assertGreater(result["development_rows"], 0)
        self.assertGreater(result["withheld_pre_holdout_rows"], 0)
        self.assertGreaterEqual(result["holdout_rows"], 60)
        self.assertEqual(result["status"], "PAPER_HOLDOUT_SCREEN_ONLY_UNATTESTED")
        self.assertEqual(result["edge_verdict"], "UNPROVEN")
        self.assertEqual(result["execution_proof"], "UNVERIFIED")
        self.assertFalse(result["holdout_boundary_precommitted_verified"])
        self.assertEqual(result["holdout_only_paper_metrics"]["completed_marks"],
                         result["holdout_rows"])

    def test_losing_holdout_never_borrows_development_wins(self):
        rows = [synthetic_row(i, losing=(START + timedelta(days=2*i) >= BOUNDARY))
                for i in range(120)]
        result = audit.evaluate_holdout(rows, holdout_start=BOUNDARY, asof=ASOF)
        self.assertEqual(result["status"], "NO_VALIDATED_OUT_OF_SAMPLE_EDGE")
        self.assertEqual(result["edge_verdict"], "UNPROVEN")
        self.assertLess(result["holdout_only_paper_metrics"]
                        ["net_quote_mark_scenarios"]["5"]["mean_net_quote_mark_usd"], 0)

    def test_empty_holdout_is_not_a_positive_result(self):
        rows = [synthetic_row(i) for i in range(8)]
        result = audit.evaluate_holdout(
            rows, holdout_start=datetime(2026, 9, 1, tzinfo=UTC), asof=ASOF)
        self.assertEqual(result["holdout_rows"], 0)
        self.assertEqual(result["status"], "NO_VALIDATED_OUT_OF_SAMPLE_EDGE")

    def test_no_pre_boundary_development_is_not_paper_promising(self):
        rows = [synthetic_row(i) for i in range(120)]
        result = audit.evaluate_holdout(
            rows, holdout_start=datetime(2026, 1, 1, tzinfo=UTC), asof=ASOF)
        self.assertEqual(result["development_rows"], 0)
        self.assertEqual(result["status"], "NO_VALIDATED_OUT_OF_SAMPLE_EDGE")

    def test_concurrent_account_risk_from_full_population_blocks_subset(self):
        rows = [synthetic_row(0, underlying="TEST"),
                synthetic_row(0, underlying="PAIR")]
        result = audit.evaluate_holdout(rows, holdout_start=BOUNDARY, asof=ASOF)
        self.assertEqual(result["status"], "WHOLE_POPULATION_ACCOUNT_RISK_EXCEEDED")
        self.assertNotIn("holdout_only_paper_metrics", result)

    def test_fail_closed_nonaware_invalid_and_future_cutoff(self):
        rows = [synthetic_row(0)]
        for cutoff in (datetime(2026, 4, 15), ASOF, ASOF + timedelta(days=1)):
            with self.assertRaises(forward.EvidenceError):
                audit.evaluate_holdout(rows, holdout_start=cutoff, asof=ASOF)
        with self.assertRaises(forward.EvidenceError):
            audit.evaluate_holdout(rows, holdout_start=BOUNDARY,
                                   asof=datetime(2026, 10, 28))

    def test_embargo_cannot_be_silently_removed(self):
        for gap in (0, -1, 20, 366, 21.1, True):
            with self.subTest(gap=gap), self.assertRaises(forward.EvidenceError):
                audit.evaluate_holdout([], holdout_start=BOUNDARY,
                                       asof=ASOF, embargo_days=gap)

    def test_bad_population_rejects_before_returning_favorable_holdout(self):
        rows = [synthetic_row(i) for i in range(120)]
        rows.append(dict(rows[-1]))
        with self.assertRaises(forward.EvidenceError):
            audit.evaluate_holdout(rows, holdout_start=BOUNDARY, asof=ASOF)

    def test_stream_input_is_bounded_before_materialization(self):
        def untrusted_stream():
            for _ in range(forward.MAX_ROWS + 1):
                yield synthetic_row(0)
            raise RuntimeError("Unbounded stream consumption")

        with self.assertRaisesRegex(forward.EvidenceError, "bounded"):
            audit.evaluate_holdout(untrusted_stream(),
                                   holdout_start=BOUNDARY, asof=ASOF)

    def test_deterministic_under_reordered_rows(self):
        rows = [synthetic_row(i) for i in range(120)]
        first = audit.evaluate_holdout(rows, holdout_start=BOUNDARY, asof=ASOF)
        reverse = audit.evaluate_holdout(list(reversed(rows)), holdout_start=BOUNDARY, asof=ASOF)
        self.assertEqual(first, reverse)


if __name__ == "__main__":
    unittest.main()
