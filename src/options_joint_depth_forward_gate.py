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

# Official Cboe U.S. OPTIONS RTH calendars, confirmed 2026-11-01:
# https://www.cboe.com/about/hours/us-options (2026 and 2027 tables).
# This screen supports conservative ordinary equity-option RTH only, not
# select extended hours or special 13:15/16:15 eligible option classes.
# Unattested years fail closed rather than silently assuming a normal day.
_CBOE_RTH_HOLIDAYS = {
    2026: frozenset(date(2026, m, d) for m, d in (
        (1, 1), (1, 19), (2, 16), (4, 3), (5, 25), (6, 19),
        (7, 3), (9, 7), (11, 26), (12, 25),
    )),
    2027: frozenset(date(2027, m, d) for m, d in (
        (1, 1), (1, 18), (2, 15), (3, 26), (5, 31), (6, 18),
        (7, 5), (9, 6), (11, 25), (12, 24),
    )),
}
_CBOE_RTH_EARLY_CLOSE = {
    2026: frozenset((date(2026, 11, 27), date(2026, 12, 24))),
    2027: frozenset((date(2027, 11, 26),)),
}


def _in_attested_regular_session(raw):
    """Fail closed for unknown calendar years and non-RTH quote timestamps."""
    if not isinstance(raw, str):
        return False
    try:
        observed = datetime.fromisoformat(
            raw.strip().replace("Z", "+00:00")
        )
    except ValueError:
        return False
    if observed.tzinfo is None or observed.utcoffset() is None:
        return False
    observed = observed.astimezone(EASTERN)
    holidays = _CBOE_RTH_HOLIDAYS.get(observed.year)
    if (holidays is None or observed.weekday() >= 5
            or observed.date() in holidays):
        return False
    close_minutes = (13 * 60 if observed.date()
                     in _CBOE_RTH_EARLY_CLOSE[observed.year] else 16 * 60)
    minutes = observed.hour * 60 + observed.minute
    return 9 * 60 + 30 <= minutes < close_minutes


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
    # The canonical paper validator and the independent depth validator each
    # require fresh side clocks, but independent freshness alone does not
    # prove that matching prices represent the SAME side update. Bind all
    # eight observations across both ledgers before crediting a joint book.
    # The depth screen can return an explicit blocked status for partial
    # evidence: do not access missing fields in that case.
    if depth["status"] == "QUOTE_DEPTH_SCREEN_ONLY":
        by_id = {row["trade_id"]: row for row in depth_rows}
        for paper in paper_rows:
            depth_row = by_id[paper["trade_id"]]
            for event in ("entry", "exit"):
                for leg_side in ("short_bid", "short_ask", "long_bid", "long_ask"):
                    paper_clock = _cutoff(paper[event + "_" + leg_side + "_quote_utc"])
                    depth_clock = _cutoff(depth_row[event + "_" + leg_side + "_utc"])
                    if paper_clock != depth_clock:
                        raise JointEvidenceError(
                            "Quote side clock identity mismatch across research ledgers"
                        )

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

    # Conservative regular-session envelope for all entry/exit evidence.
    # Official closures and 13:00 early closes are included for 2026/2027;
    # RTH-only marks still NEVER establish broker fillability.

    for row in paper_rows:
        for field in ("decision_utc", "entry_utc", "entry_quote_utc",
                      "exit_utc", "exit_quote_utc"):
            if not _in_attested_regular_session(row[field]):
                raise JointEvidenceError(
                    "Regular-session quote observation missing"
                )
    # A coherent side book may contain source timestamps that precede the
    # official 09:30 opening even when quote capture is timestamped at 09:30.
    # Examine all eight side updates only after depth validity is confirmed.
    if depth["status"] == "QUOTE_DEPTH_SCREEN_ONLY":
        for row in depth_rows:
            for event in ("entry", "exit"):
                for leg_side in ("short_bid", "short_ask", "long_bid", "long_ask"):
                    if not _in_attested_regular_session(row[event + "_" + leg_side + "_utc"]):
                        raise JointEvidenceError(
                            "Regular-session quote observation missing"
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
