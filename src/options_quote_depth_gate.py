"""Offline, synthetic-testable quote-side depth and clock coherence audit.

Supplementary fail-closed check of proposed paper spread quote marks.
Never calls a broker, places orders, loads private files, or proves fills.
The upstream paper evaluator remains the P&L/risk authority.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re

SIDES = ("short_bid", "short_ask", "long_bid", "long_ask")
EVENTS = ("entry", "exit")
MAX_ROWS = 5000
MAX_AGE_SECONDS = 120
MAX_SIDE_SKEW_SECONDS = 30


class DepthError(ValueError):
    """Sanitized structural/coverage failure, no quote or identifier echo."""


def _time(value):
    if not isinstance(value, str):
        raise DepthError("Invalid aware timestamp")
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise DepthError("Invalid aware timestamp") from None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DepthError("Invalid aware timestamp")
    return dt.astimezone(timezone.utc)


def _size(value):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,8}", str(value)):
        raise DepthError("Invalid quote-side depth")
    return int(value)


def _price(value):
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise DepthError("Invalid quote-side price") from None
    if not decimal.is_finite() or decimal < 0:
        raise DepthError("Invalid quote-side price")
    return decimal


def _valid_id(row):
    if not isinstance(row, dict):
        raise DepthError("Malformed depth record")
    uid = row.get("trade_id")
    if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", uid):
        raise DepthError("Invalid trade identifier")
    return uid


def _check_one(paper, depth, *, asof, contracts):
    decision_time = _time(paper.get("decision_utc"))
    entry_time = _time(paper.get("entry_utc"))
    exit_time = _time(paper.get("exit_utc"))
    if exit_time > asof:
        return "FUTURE_EXIT"
    # A coherent quote book cannot rehabilitate an entry made before a signal.
    # Match the standalone chronology rule used by the paper-mark evaluator.
    if not decision_time <= entry_time < exit_time:
        return "CLOCK_INCOHERENT"
    for event in EVENTS:
        event_time = _time(paper.get(event + "_utc"))
        source_capture = _time(paper.get(event + "_quote_utc"))
        decision_or_exit = (_time(paper.get("decision_utc"))
                            if event == "entry" else event_time)
        if event_time > asof or source_capture > decision_or_exit:
            return "CLOCK_INCOHERENT"
        observations = []
        leg_prices = {}
        for leg_side in SIDES:
            key = event + "_" + leg_side
            if key + "_size" not in depth or key + "_utc" not in depth or key + "_px" not in depth:
                return "MISSING_SIDE"
            if _size(depth[key + "_size"]) < contracts:
                return "INSUFFICIENT_DEPTH"
            leg_prices[leg_side] = _price(depth[key + "_px"])
            if leg_prices[leg_side] != _price(paper.get(key)):
                return "PRICE_MISMATCH"
            update_time = _time(depth[key + "_utc"])
            if update_time > source_capture or update_time > decision_or_exit:
                return "FUTURE_SIDE_UPDATE"
            age = (event_time - update_time).total_seconds()
            if not 0 <= age <= MAX_AGE_SECONDS:
                return "STALE_SIDE_UPDATE"
            observations.append(update_time)
        # A crossed individual option book can create a fictitious spread credit.
        # Equal bid/ask (locked book) is allowed; executions are still unproven.
        for leg in ("short", "long"):
            bid, ask = leg_prices[leg + "_bid"], leg_prices[leg + "_ask"]
            if ask == 0:
                return "NONPOSITIVE_ASK"
            if bid > ask:
                return "CROSSED_LEG_BOOK"
        if (max(observations) - min(observations)).total_seconds() > MAX_SIDE_SKEW_SECONDS:
            return "UNSYNCHRONIZED_BOOK"
    return None


def audit_quote_depth(paper_rows, depth_rows, *, asof, contracts=1):
    """Demand 1:1 complete side records, never filter losers from the cohort.

    Input depth rows contain one bid and one ask with observed side sizes,
    timestamps and prices for each leg at both entry and exit. These fields
    are documented by Tradier's quotes API but NOT a guarantee of executions.
    Returns only sanitized aggregate counts, never paper marks or quotes.
    """
    cutoff = _time(asof) if isinstance(asof, str) else asof
    if not isinstance(cutoff, datetime) or cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise DepthError("Evaluation cutoff requires an aware timestamp")
    cutoff = cutoff.astimezone(timezone.utc)
    if not isinstance(contracts, int) or isinstance(contracts, bool) or not 1 <= contracts <= 10:
        raise DepthError("Invalid bounded paper contract size")
    if not isinstance(paper_rows, (list, tuple)) or not isinstance(depth_rows, (list, tuple)):
        raise DepthError("Evidence population must be a bounded sequence")
    if len(paper_rows) > MAX_ROWS or len(depth_rows) > MAX_ROWS:
        raise DepthError("Evidence population exceeds row limit")
    paper_by_id, depth_by_id = {}, {}
    for source, destination in ((paper_rows, paper_by_id), (depth_rows, depth_by_id)):
        for row in source:
            uid = _valid_id(row)
            if uid in destination:
                raise DepthError("Duplicate trade identifier")
            destination[uid] = row
    if paper_by_id.keys() != depth_by_id.keys():
        raise DepthError("Depth evidence does not exactly cover submitted paper population")
    defects = Counter()
    for uid in sorted(paper_by_id):
        reason = _check_one(paper_by_id[uid], depth_by_id[uid], asof=cutoff,
                            contracts=contracts)
        if reason:
            defects[reason] += 1
    return {
        "status": "QUOTE_DEPTH_SCREEN_ONLY" if not defects and paper_by_id
                  else ("NO_PAPER_MARKS" if not paper_by_id
                        else "DEPTH_SCREEN_BLOCKED"),
        "submitted_marks": len(paper_by_id),
        "verified_quote_depth_rows": len(paper_by_id) - sum(defects.values()),
        "reason_counts": dict(sorted(defects.items())),
        "all_mark_rows_covered": True,
        "forward_risk_and_outcome_audit_required": True,
        "actual_fill_proof": False,
        "edge_verdict": "UNPROVEN",
    }
