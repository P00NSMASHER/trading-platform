"""Fail-closed composition of the canonical private forward screen and depth audit.

No market-data transport, broker calls, orders, persistence, or token access.
All input evidence must be a complete, privately retained, preregistered cohort.
The result is only a research screen; bid/ask marks do not prove fills or edge.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from options_forward_evaluator import (
    EvidenceError,
    EASTERN,
    MODELED_PORTFOLIO_RISK_LIMIT_USD,
    evaluate_paper_marks,
)
from options_quote_depth_gate import DepthError, audit_quote_depth

MAX_ROWS = 5000


class JointEvidenceError(ValueError):
    """Sanitized admission failure; never embeds private marks or OCC symbols."""


def _cutoff(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            raise JointEvidenceError("Invalid cutoff timestamp") from None
    if (not isinstance(value, datetime) or value.tzinfo is None
            or value.utcoffset() is None):
        raise JointEvidenceError("Cutoff timestamp must have a timezone")
    return value.astimezone(timezone.utc)


def audit_joint_depth_forward(paper_rows, depth_rows, *, asof):
    """Check EVERY mark against canonical risk AND 1:1 observed quote depth.

    Return no mark-level records, P&L, strategy ranking, quote or OCC symbol.
    Neither partial depth coverage nor insufficient liquidity may be removed
    from the denominator to create a favorable apparent forward result.
    """
    if (not isinstance(paper_rows, (list, tuple))
            or not isinstance(depth_rows, (list, tuple))):
        raise JointEvidenceError("Input cohorts must be bounded sequences")
    if len(paper_rows) > MAX_ROWS or len(depth_rows) > MAX_ROWS:
        raise JointEvidenceError("Input cohort exceeds bounded row limit")
    cutoff = _cutoff(asof)
    try:
        # Run the complete canonical model: it enforces OCC expiry/strike,
        # 7-21 DTE, timestamp order, risk, overlap, fee, and cost stresses.
        forward = evaluate_paper_marks(paper_rows, asof=cutoff)
    except EvidenceError:
        raise JointEvidenceError("Canonical paper population rejected") from None
    try:
        # Independently require depth/side clocks for the EXACT same IDs.
        depth = audit_quote_depth(paper_rows, depth_rows, asof=cutoff, contracts=1)
    except DepthError:
        raise JointEvidenceError("Quote-depth population rejected") from None
    # Individually valid legs can still imply an impossible, inverted
    # same-expiry vertical exit. The canonical evaluator floors negative
    # close debits at zero; never interpret such books as a free paper exit.
    # Fail the entire submitted cohort rather than dropping an adverse row.
    for row in paper_rows:
        if (Decimal(str(row["exit_short_ask"]))
                < Decimal(str(row["exit_long_bid"]))):
            raise JointEvidenceError("Cross-leg exit package quote is inverted")

    # An expiration-day L1 mark is not a broker-confirmed closing fill.
    # Pin/early assignment can leave 100-share stock exposure after exercise,
    # even when entry spread width passes the nominal $100 modeled-risk cap.
    # Apply to the ENTIRE cohort; compare dates in New York, not UTC.
    for row in paper_rows:
        exit_day = datetime.fromisoformat(
            row["exit_utc"].strip().replace("Z", "+00:00")
        ).astimezone(EASTERN).date()
        if exit_day == date.fromisoformat(row["expiry"]):
            raise JointEvidenceError(
                "Expiry-day quote mark cannot prove assignment-safe close"
            )

    count = forward["completed_marks"]
    if count != depth["submitted_marks"]:
        raise JointEvidenceError("Paper and depth populations disagree")

    if not count:
        status = "NO_COMPLETED_EVIDENCE"
        risk = 0.0
    else:
        risk = forward["max_simultaneous_modeled_risk_usd"]
        if risk > MODELED_PORTFOLIO_RISK_LIMIT_USD + 1e-8:
            status = "ACCOUNT_RISK_BLOCKED"
        elif depth["status"] != "QUOTE_DEPTH_SCREEN_ONLY":
            status = "QUOTE_DEPTH_BLOCKED"
        elif forward["status"] == "PAPER_ONLY_PROMISING_NOT_VERIFIED":
            status = "PAPER_QUOTE_SCREEN_ONLY"
        else:
            status = "FORWARD_EVIDENCE_NOT_POSITIVE"
    return {
        "status": status,
        "submitted_marks": count,
        "depth_verified_quote_rows": depth["verified_quote_depth_rows"],
        "depth_status": depth["status"],
        "max_simultaneous_modeled_risk_usd": risk,
        "account_risk_limit_usd": MODELED_PORTFOLIO_RISK_LIMIT_USD,
        "all_mark_rows_covered": depth["all_mark_rows_covered"],
        "all_mark_risk_evaluated": True,
        "edge_verdict": "UNPROVEN",
        "execution_proof": "UNVERIFIED",
        "market_provenance_attested": False,
        "selection_preregistered_verified": False,
        "assignment_risk_calibrated": False,
        "note": "QUOTE_ONLY_NO_ACTUAL_FILL_OR_PROFIT_CLAIM",
    }
