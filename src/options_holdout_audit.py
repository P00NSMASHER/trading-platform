"""Fail-closed, local-only time-block holdout audit for options paper marks.

No brokerage access, no strategy optimization and no profitability assertion.
All supplied records remain in the caller's private environment.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json

import options_forward_evaluator as forward

MIN_EMBARGO_DAYS = 21


def _aware_utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise forward.EvidenceError("Temporal holdout requires timezone-aware timestamps")
    return value.astimezone(timezone.utc)


def evaluate_holdout(rows, *, holdout_start, asof=None, embargo_days=21):
    """Assess a fixed chronological test set without training-label leakage.

    Entries in the 21+-day pre-holdout embargo, or with outcomes not available
    by the boundary, are withheld from the development set. This checks only
    the supplied records; it cannot authenticate a preregistered cutoff,
    complete signal capture, prior strategy freezing or executable fills.
    """
    if (isinstance(embargo_days, bool) or not isinstance(embargo_days, int)
            or embargo_days < MIN_EMBARGO_DAYS or embargo_days > 365):
        raise forward.EvidenceError("Embargo is outside the audited 21-365 day range")
    asof = _aware_utc(asof if asof is not None else datetime.now(timezone.utc))
    holdout_start = _aware_utc(holdout_start)
    if holdout_start >= asof:
        raise forward.EvidenceError("Holdout boundary must precede evaluation cutoff")
    # Validate the ENTIRE admitted sample before allowing a flattering subset.
    # This checks duplicates, stale quotes, nonstandard contracts, exposure
    # overlap and modeled account capacity with the existing audited rules.
    rows = list(rows)
    if len(rows) > forward.MAX_ROWS:
        raise forward.EvidenceError("Private evidence exceeds bounded evaluation row limit")
    population = forward.evaluate_paper_marks(rows, asof=asof)
    if population["status"] == "ACCOUNT_RISK_CAPACITY_EXCEEDED":
        return {
            "status": "WHOLE_POPULATION_ACCOUNT_RISK_EXCEEDED",
            "edge_verdict": "UNPROVEN",
            "execution_proof": "UNVERIFIED",
            "population_rows": len(rows),
            "cutoff_precommitted_verified": False,
            "complete_selection_population_verified": False,
        }
    marks = [forward.parse_paper_mark(row, asof=asof) for row in rows]
    purge_start = holdout_start - timedelta(days=embargo_days)
    development = []
    withheld = []
    test = []
    for row, mark in zip(rows, marks):
        if mark.entry >= holdout_start:
            test.append(row)
        elif mark.entry < purge_start and mark.exit <= holdout_start:
            development.append(row)
        else:
            withheld.append(row)

    observed = forward.evaluate_paper_marks(test, asof=asof)
    sufficient = bool(development) and observed["status"] == "PAPER_ONLY_PROMISING_NOT_VERIFIED"
    return {
        "status": ("PAPER_HOLDOUT_SCREEN_ONLY_UNATTESTED" if sufficient
                   else "NO_VALIDATED_OUT_OF_SAMPLE_EDGE"),
        "edge_verdict": "UNPROVEN",
        "execution_proof": "UNVERIFIED",
        "holdout_boundary_precommitted_verified": False,
        "unretuned_strategy_verified": False,
        "matched_controls_verified": False,
        "complete_selection_population_verified": False,
        "embargo_days": embargo_days,
        "population_rows": len(rows),
        "development_rows": len(development),
        "withheld_pre_holdout_rows": len(withheld),
        "holdout_rows": len(test),
        "holdout_only_paper_metrics": observed,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Private paper-only chronological holdout audit")
    parser.add_argument("--private-csv", required=True)
    parser.add_argument("--holdout-start-utc", required=True)
    args = parser.parse_args(argv)
    try:
        cutoff = datetime.fromisoformat(args.holdout_start_utc.replace("Z", "+00:00"))
        result = evaluate_holdout(
            forward.load_private_csv(args.private_csv), holdout_start=cutoff)
    except (ValueError, forward.EvidenceError, OSError):
        parser.error("Invalid private evidence or temporal holdout parameters")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
