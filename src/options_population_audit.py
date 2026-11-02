"""Offline selection-completeness gate for privately retained options paper observations.

It joins a prior decision/admission manifest to the private forward quote-mark
ledger and prevents omitted selected outcomes from masquerading as a winning
strategy. It cannot independently prove the manifest was recorded prospectively.
No network, Tradier credentials, or trade execution.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re

import options_forward_evaluator as forward

ADMISSION_COLUMNS = (
    "trade_id", "underlying", "expiry", "side", "decision_utc",
    "recorded_utc", "disposition", "reject_reason",
)
DISPOSITIONS = frozenset(("SELECTED", "REJECTED"))
REJECT_REASONS = frozenset((
    "DATA_QUALITY", "NO_H1", "ACCOUNT_CAPACITY",
    "CONFLICTING_EXPOSURE", "OTHER_PREDECLARED",
))


@dataclass(frozen=True)
class Admission:
    trade_id: str
    underlying: str
    expiry: date
    side: str
    decision: datetime
    recorded: datetime
    disposition: str
    reject_reason: str


def parse_admission(row, *, asof):
    if not isinstance(row, dict) or any(k not in row for k in ADMISSION_COLUMNS):
        raise forward.EvidenceError("Private admission manifest missing required fields")
    uid = row["trade_id"]
    if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", uid):
        raise forward.EvidenceError("Admission identifier is missing or malformed")
    symbol = row["underlying"]
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", symbol):
        raise forward.EvidenceError("Admission has an invalid underlying identifier")
    side = row["side"]
    if side not in ("bear_call", "bull_put"):
        raise forward.EvidenceError("Admission has an unsupported strategy side")
    try:
        expiry = date.fromisoformat(row["expiry"])
    except (ValueError, TypeError):
        raise forward.EvidenceError("Admission has an invalid expiration") from None
    decision = forward._ts(row, "decision_utc")
    recorded = forward._ts(row, "recorded_utc")
    if (decision > asof or recorded > asof or recorded < decision
        or (recorded - decision).total_seconds() > 120):
        raise forward.EvidenceError("Admission timestamp missing or outside decision-time boundary")
    if not 7 <= (expiry - decision.astimezone(forward.EASTERN).date()).days <= 21:
        raise forward.EvidenceError("Admission not in preregistered 7-21 DTE interval")
    disposition = row["disposition"]
    reason = row["reject_reason"]
    if disposition not in DISPOSITIONS:
        raise forward.EvidenceError("Admission disposition is not an approved enum")
    if disposition == "SELECTED":
        if reason not in ("", None):
            raise forward.EvidenceError("Selected admission must not carry a rejection reason")
    elif reason not in REJECT_REASONS:
        raise forward.EvidenceError("Rejected admission lacks a fixed reason enum")
    return Admission(
        trade_id=uid, underlying=symbol, expiry=expiry, side=side,
        decision=decision, recorded=recorded, disposition=disposition,
        reject_reason=reason or "",
    )


def evaluate_population(admissions, outcomes, *, asof=None):
    """Reconcile all selected decision IDs before evaluating paper P&L.

    Even a complete submitted manifest does NOT prove source-population capture,
    authentic precommitment, an executable fill, or actual profitability.
    """
    asof = asof or datetime.now(timezone.utc)
    if asof.tzinfo is None or asof.utcoffset() is None:
        raise forward.EvidenceError("Evaluation cutoff requires timezone")
    asof = asof.astimezone(timezone.utc)
    admission_by_id = {}
    summary = {
        "manifest_rows": 0,
        "selected_signals": 0,
        "rejected_signals": 0,
        "rejected_reason_counts": {key: 0 for key in sorted(REJECT_REASONS)},
        "completed_selected_outcomes": 0,
        "missing_expired_outcomes": 0,
        "pending_unexpired_outcomes": 0,
        "selection_manifest_timestamp_attested": False,
        "full_candidate_universe_verified": False,
        "execution_proof": "UNVERIFIED",
        "edge_verdict": "UNPROVEN",
    }
    for row in admissions:
        if summary["manifest_rows"] >= forward.MAX_ROWS:
            raise forward.EvidenceError("Admission population exceeds bounded row limit")
        item = parse_admission(row, asof=asof)
        if item.trade_id in admission_by_id:
            raise forward.EvidenceError("Duplicate signal identifier in admission manifest")
        admission_by_id[item.trade_id] = item
        summary["manifest_rows"] += 1
        if item.disposition == "SELECTED":
            summary["selected_signals"] += 1
        else:
            summary["rejected_signals"] += 1
            summary["rejected_reason_counts"][item.reject_reason] += 1

    outcomes_by_id = {}
    for row in outcomes:
        if not isinstance(row, dict):
            raise forward.EvidenceError("Invalid paper-outcome row")
        uid = row.get("trade_id")
        selected = admission_by_id.get(uid) if isinstance(uid, str) else None
        if selected is None or selected.disposition != "SELECTED":
            raise forward.EvidenceError("Paper outcome lacks a previously selected admission")
        if uid in outcomes_by_id:
            raise forward.EvidenceError("Duplicate completed paper outcome")
        try:
            expiry = date.fromisoformat(row.get("expiry"))
        except (TypeError, ValueError):
            raise forward.EvidenceError("Malformed paper outcome expiration") from None
        if (row.get("underlying") != selected.underlying
            or row.get("side") != selected.side
            or expiry != selected.expiry
            or forward._ts(row, "decision_utc") != selected.decision):
            raise forward.EvidenceError("Paper outcome contradicts its admitted signal")
        if forward._ts(row, "entry_utc") < selected.recorded:
            raise forward.EvidenceError("Admission was recorded after its purported paper entry")
        outcomes_by_id[uid] = row
        if len(outcomes_by_id) > forward.MAX_ROWS:
            raise forward.EvidenceError("Outcome population exceeds bounded row limit")

    for item in admission_by_id.values():
        if item.disposition != "SELECTED":
            continue
        if item.trade_id in outcomes_by_id:
            summary["completed_selected_outcomes"] += 1
        elif item.expiry < asof.astimezone(forward.EASTERN).date():
            summary["missing_expired_outcomes"] += 1
        else:
            summary["pending_unexpired_outcomes"] += 1

    # Do not expose selectively recorded winners' P&L while ANY admitted
    # paper signal lacks a completed outcome, even if still unexpired.
    if summary["missing_expired_outcomes"]:
        summary["status"] = "INCOMPLETE_EXPIRED_OUTCOMES"
    elif summary["pending_unexpired_outcomes"]:
        summary["status"] = "PENDING_UNCLOSED_SIGNAL_OUTCOMES"
    elif not summary["manifest_rows"]:
        summary["status"] = "NO_ADMISSION_MANIFEST"
    elif not summary["selected_signals"]:
        summary["status"] = "NO_SELECTED_SIGNALS"
    else:
        paper = forward.evaluate_paper_marks(
            list(outcomes_by_id.values()), asof=asof)
        summary["status"] = "COMPLETE_SUBMITTED_SELECTION_LEDGER_ONLY"
        summary["paper_quote_mark_evaluation"] = paper
        # Never turn an unsupported paper mark into real trading profit.
        summary["paper_screen_status"] = paper["status"]
    return summary


def load_private_admissions(path):
    filename = Path(path).expanduser().resolve()
    root = Path(__file__).resolve().parents[1]
    if filename == root or root in filename.parents:
        raise forward.EvidenceError("Private admission data may not be stored in public repository")
    if not filename.is_file() or filename.stat().st_size > forward.MAX_PRIVATE_CSV_BYTES:
        raise forward.EvidenceError("Private admission manifest missing or too large")
    try:
        with filename.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or any(k not in reader.fieldnames for k in ADMISSION_COLUMNS):
                raise forward.EvidenceError("Admission manifest lacks required header fields")
            return list(reader)
    except (UnicodeError, OSError, csv.Error):
        raise forward.EvidenceError("Cannot read private admission manifest") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline private options selection-completeness audit")
    parser.add_argument("--private-admissions", required=True)
    parser.add_argument("--private-outcomes", required=True)
    args = parser.parse_args(argv)
    try:
        admissions = load_private_admissions(args.private_admissions)
        outcomes = forward.load_private_csv(args.private_outcomes)
        result = evaluate_population(admissions, outcomes)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "COMPLETE_SUBMITTED_SELECTION_LEDGER_ONLY" else 2
    except forward.EvidenceError as err:
        print("RESEARCH_POPULATION_BLOCKED: " + str(err))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
