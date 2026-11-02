"""Private-only, read-only forward options edge evaluation.

This module NEVER calls Tradier or places trades. It loads independently
retained, permissioned entry and exit observations on the local machine,
verifies quote/data quality, and reports aggregates only. Bid/ask counterfactual
marks are NOT actual fills, and a successful statistical screen is NOT a
verified exploitable advantage.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import random
import re
import statistics
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
COLUMNS = (
    "trade_id", "underlying", "expiry", "side", "decision_utc",
    "entry_utc", "entry_quote_utc", "greeks_time_utc", "exit_utc",
    "exit_quote_utc", "entry_spot", "short_strike", "long_strike",
    "short_contract", "long_contract",
    "entry_short_bid", "entry_short_ask", "entry_long_bid", "entry_long_ask",
    "exit_short_bid", "exit_short_ask", "exit_long_bid", "exit_long_ask",
    "short_open_interest", "long_open_interest",
    "atm_iv", "rv20", "multiplier",
)
BROKER_MULTIPLIER = 100
MODELED_TRADE_RISK_LIMIT_USD = 100.0
MODELED_PORTFOLIO_RISK_LIMIT_USD = 100.0
COMMISSION_PER_CONTRACT_SIDE_USD = 0.65
ROUND_TRIP_COMMISSION_USD = 4 * COMMISSION_PER_CONTRACT_SIDE_USD
SLIPPAGE_STRESS_USD = (0, 5, 10)
MIN_PROSPECTIVE_TRADES = 60
MIN_CALENDAR_SPAN_DAYS = 90
MIN_UNIQUE_WEEKS = 12
MAX_PRIVATE_CSV_BYTES = 1_000_000
MAX_ROWS = 5000
BOOTSTRAP_REPETITIONS = 1500
BOOTSTRAP_SEED = 20261028


class EvidenceError(ValueError):
    """Intentionally sanitized and safe to print without input values."""


@dataclass(frozen=True)
class PaperMark:
    trade_id: str
    underlying: str
    expiry: date
    side: str
    entry: datetime
    exit: datetime
    modeled_risk_usd: float
    quote_mark_pnl_before_costs_usd: float


def _ts(row, field):
    raw = row.get(field)
    if not isinstance(raw, str):
        raise EvidenceError("Missing observation timestamp")
    try:
        value = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        raise EvidenceError("Malformed observation timestamp") from None
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceError("Observation timestamp lacks an explicit timezone")
    return value.astimezone(timezone.utc)


def _num(row, field, *, allow_zero=False):
    raw = row.get(field)
    try:
        value = float(raw)
    except (ValueError, TypeError):
        raise EvidenceError("Missing or invalid required market-data number") from None
    if (not math.isfinite(value)
        or (value < 0 if allow_zero else value <= 0)):
        raise EvidenceError("Non-finite or nonpositive required market-data number")
    return value


def _fresh(asof, quote_time, seconds):
    age = (asof - quote_time).total_seconds()
    return 0 <= age <= seconds


def _verify_occ_contract(raw, *, underlying, expiry, right, strike):
    """Reject adjusted, mismatched or unidentified contract delivery roots."""
    if not isinstance(raw, str):
        raise EvidenceError("Missing OCC option contract identity")
    m = re.fullmatch(r"([A-Z]{1,6}) *([0-9]{6})([CP])([0-9]{8})", raw)
    if m is None:
        raise EvidenceError("Invalid or adjusted OCC option contract identity")
    root, expiration, option_right, encoded_strike = m.groups()
    if root != underlying.replace(".", "") or option_right != right:
        raise EvidenceError("OCC option root or call/put side mismatch")
    try:
        parsed_expiry = datetime.strptime(expiration, "%y%m%d").date()
    except ValueError:
        raise EvidenceError("Invalid OCC option expiration") from None
    if parsed_expiry != expiry or abs(int(encoded_strike) / 1000 - strike) > 0.00001:
        raise EvidenceError("OCC option expiry or strike does not match paper mark")


def parse_paper_mark(row: dict, *, asof: datetime | None = None) -> PaperMark:
    if not isinstance(row, dict) or any(key not in row for key in COLUMNS):
        raise EvidenceError("Private paper-mark ledger missing required columns")
    trade_id = row["trade_id"]
    underlying = row["underlying"]
    side = row["side"]
    if (not isinstance(trade_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", trade_id)):
        raise EvidenceError("Invalid or missing research trade identifier")
    if (not isinstance(underlying, str)
        or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", underlying)):
        raise EvidenceError("Invalid underlying identifier")
    if side not in ("bear_call", "bull_put"):
        raise EvidenceError("Only defined-risk vertical call/put credit spreads accepted")
    try:
        expiry = date.fromisoformat(row["expiry"])
    except (ValueError, TypeError):
        raise EvidenceError("Invalid option expiration date") from None

    decision = _ts(row, "decision_utc")
    entry = _ts(row, "entry_utc")
    entry_quote = _ts(row, "entry_quote_utc")
    greek_time = _ts(row, "greeks_time_utc")
    exit_time = _ts(row, "exit_utc")
    exit_quote = _ts(row, "exit_quote_utc")

    if not decision <= entry < exit_time:
        raise EvidenceError("Lookahead or non-chronological paper entry/exit timestamps")
    if not _fresh(entry, decision, 120) or entry_quote > decision:
        raise EvidenceError("Paper entry decision was not contemporaneous with its observed quote")
    if asof is not None and exit_time > asof:
        raise EvidenceError("Paper mark contains an outcome beyond the evaluation cutoff")
    if not (_fresh(entry, entry_quote, 120)
            and _fresh(exit_time, exit_quote, 120)
            and _fresh(decision, greek_time, 90 * 60)):
        raise EvidenceError("Missing, future, or stale entry/exit quote or IV calculation")

    entry_date = decision.astimezone(EASTERN).date()
    exit_date = exit_time.astimezone(EASTERN).date()
    dte = (expiry - entry_date).days
    if not 7 <= dte <= 21 or exit_date > expiry:
        raise EvidenceError("Paper mark outside preregistered 7-21 DTE or expires before exit")

    multiplier = _num(row, "multiplier")
    if multiplier != BROKER_MULTIPLIER:
        raise EvidenceError("Nonstandard option deliverable rejected")
    spot = _num(row, "entry_spot")
    short = _num(row, "short_strike")
    long = _num(row, "long_strike")
    if side == "bear_call":
        width = long - short
        otm = spot < short < long
    else:
        width = short - long
        otm = long < short < spot
    if not otm or not 0 < width <= 3:
        raise EvidenceError("Option spread is not standard OTM defined-width vertical")
    right = "C" if side == "bear_call" else "P"
    _verify_occ_contract(row["short_contract"], underlying=underlying,
                         expiry=expiry, right=right, strike=short)
    _verify_occ_contract(row["long_contract"], underlying=underlying,
                         expiry=expiry, right=right, strike=long)
    if row["short_contract"] == row["long_contract"]:
        raise EvidenceError("Spread legs must reference distinct OCC contracts")

    for column in ("short_open_interest", "long_open_interest"):
        oi = _num(row, column, allow_zero=True)
        if int(oi) != oi or oi < 100:
            raise EvidenceError("Option open interest fails fixed liquidity floor")

    iv, rv = _num(row, "atm_iv"), _num(row, "rv20")
    if iv > 3 or rv > 3 or iv / rv < 1.20:
        raise EvidenceError("Paper mark fails preregistered paired ATM-IV/realized-vol H1")

    quote = {}
    for event in ("entry", "exit"):
        for leg in ("short", "long"):
            bid_key = event + "_" + leg + "_bid"
            ask_key = event + "_" + leg + "_ask"
            bid = _num(row, bid_key, allow_zero=True)
            ask = _num(row, ask_key)
            if ask < bid:
                raise EvidenceError("Crossed or reversed option leg quote")
            mid = (ask + bid) / 2
            if mid <= 0 or (ask - bid) / mid > 0.25:
                raise EvidenceError("Paper option leg market exceeds fixed liquidity spread")
            quote[bid_key] = bid
            quote[ask_key] = ask
    short_bid = quote["entry_short_bid"]
    long_ask = quote["entry_long_ask"]
    short_ask_exit = quote["exit_short_ask"]
    long_bid_exit = quote["exit_long_bid"]
    credit = (short_bid - long_ask) * BROKER_MULTIPLIER
    if not 0 < credit < width * BROKER_MULTIPLIER:
        raise EvidenceError("Missing positive conservative entry credit")
    risk = width * BROKER_MULTIPLIER - credit + ROUND_TRIP_COMMISSION_USD
    if risk > MODELED_TRADE_RISK_LIMIT_USD + 1e-8:
        raise EvidenceError("Paper spread exceeds modeled individual risk limit")

    # No free profits from a crossed package exit: buying back at negative
    # debit is floored at zero, and real execution may be worse than quoted.
    exit_debit = max(0.0, short_ask_exit - long_bid_exit) * BROKER_MULTIPLIER
    return PaperMark(
        trade_id=trade_id, underlying=underlying, expiry=expiry, side=side,
        entry=entry, exit=exit_time, modeled_risk_usd=round(risk, 6),
        quote_mark_pnl_before_costs_usd=round(credit - exit_debit, 6),
    )


def _max_simultaneous_modeled_risk(marks: list[PaperMark]) -> float:
    events = []
    for mark in marks:
        events.append((mark.entry, 1, mark.modeled_risk_usd))
        events.append((mark.exit, 0, -mark.modeled_risk_usd))
    active = peak = 0.0
    for _, _, change in sorted(events):
        active += change
        peak = max(peak, active)
    return round(peak, 2)


def _quote_equity_drawdown(marks, stress_dollars):
    running = high_water = max_drawdown = 0.0
    for mark in sorted(marks, key=lambda m: (m.exit, m.trade_id)):
        running += (mark.quote_mark_pnl_before_costs_usd
                    - ROUND_TRIP_COMMISSION_USD - stress_dollars)
        high_water = max(high_water, running)
        max_drawdown = max(max_drawdown, high_water - running)
    return round(max_drawdown, 2)


def _week_block_interval(marks, stress_dollars, repetitions=BOOTSTRAP_REPETITIONS):
    weeks = {}
    for mark in marks:
        local = mark.entry.astimezone(EASTERN).date()
        iso = local.isocalendar()
        week_key = (iso.year, iso.week)
        weeks.setdefault(week_key, []).append(
            mark.quote_mark_pnl_before_costs_usd
            - ROUND_TRIP_COMMISSION_USD - stress_dollars
        )
    clusters = [weeks[k] for k in sorted(weeks)]
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(repetitions):
        sample = [clusters[rng.randrange(len(clusters))]
                  for _ in range(len(clusters))]
        values = [v for cluster in sample for v in cluster]
        means.append(statistics.fmean(values))
    means.sort()
    return [round(means[int(0.025 * len(means))], 2),
            round(means[int(0.975 * len(means))], 2)]


def evaluate_paper_marks(rows, *, asof: datetime | None = None):
    """Summarize private quote-marked outcomes; never labels them executable.

    Quotes and labels must have been preregistered before any exits were known;
    this function cannot cryptographically certify that history or broker fills.
    """
    asof = asof or datetime.now(timezone.utc)
    if asof.tzinfo is None or asof.utcoffset() is None:
        raise EvidenceError("Evaluation cutoff timestamp requires a timezone")
    marks = []
    ids = set()
    for row in rows:
        if len(marks) >= MAX_ROWS:
            raise EvidenceError("Private evidence exceeds bounded evaluation row limit")
        mark = parse_paper_mark(row, asof=asof)
        if mark.trade_id in ids:
            raise EvidenceError("Duplicate research trade identifier")
        ids.add(mark.trade_id)
        marks.append(mark)
    if not marks:
        return {"status": "NO_COMPLETED_PAPER_MARKS",
                "execution_proof": "UNVERIFIED",
                "completed_marks": 0,
                "edge_verdict": "UNPROVEN"}

    marks.sort(key=lambda mark: (mark.entry, mark.trade_id))
    seen_entry_keys = set()
    latest_end = {}
    for mark in marks:
        local_entry = mark.entry.astimezone(EASTERN).date()
        key = (mark.underlying, mark.expiry, local_entry)
        if key in seen_entry_keys:
            raise EvidenceError("Correlated same-symbol/expiry entry duplicates")
        seen_entry_keys.add(key)
        if mark.underlying in latest_end and mark.entry < latest_end[mark.underlying]:
            raise EvidenceError("Overlapping same-underlying paper positions")
        latest_end[mark.underlying] = mark.exit

    days = [m.entry.astimezone(EASTERN).date() for m in marks]
    weeks = {(d.isocalendar().year, d.isocalendar().week) for d in days}
    span_days = (max(days) - min(days)).days
    peak_risk = _max_simultaneous_modeled_risk(marks)
    metrics = {}
    for extra_dollars in SLIPPAGE_STRESS_USD:
        values = [
            m.quote_mark_pnl_before_costs_usd
            - ROUND_TRIP_COMMISSION_USD - extra_dollars for m in marks
        ]
        metrics[str(extra_dollars)] = {
            "mean_net_quote_mark_usd": round(statistics.fmean(values), 2),
            "weekly_cluster_bootstrap95_usd": _week_block_interval(
                marks, extra_dollars),
            "positive_mark_fraction": round(
                sum(v > 0 for v in values) / len(values), 4),
            "worst_mark_usd": round(min(values), 2),
            "max_exit_mark_drawdown_usd": _quote_equity_drawdown(
                marks, extra_dollars),
        }

    enough = (len(marks) >= MIN_PROSPECTIVE_TRADES
              and span_days >= MIN_CALENDAR_SPAN_DAYS
              and len(weeks) >= MIN_UNIQUE_WEEKS)
    risk_fit = peak_risk <= MODELED_PORTFOLIO_RISK_LIMIT_USD + 1e-8
    stressed_lower = metrics["5"]["weekly_cluster_bootstrap95_usd"][0]
    if not enough:
        status = "INSUFFICIENT_FORWARD_EVIDENCE"
    elif not risk_fit:
        status = "ACCOUNT_RISK_CAPACITY_EXCEEDED"
    elif stressed_lower <= 0:
        status = "NO_POSITIVE_NET_EVIDENCE"
    else:
        status = "PAPER_ONLY_PROMISING_NOT_VERIFIED"

    return {
        "status": status,
        "edge_verdict": "UNPROVEN",
        "execution_proof": "UNVERIFIED",
        "mark_type": "CONSERVATIVE_QUOTE_COUNTERFACTUAL_NOT_BROKER_FILL",
        "completed_marks": len(marks),
        "underlying_count": len({m.underlying for m in marks}),
        "independent_entry_dates": len(set(days)),
        "independent_entry_weeks": len(weeks),
        "entry_span_days": span_days,
        "max_simultaneous_modeled_risk_usd": peak_risk,
        "account_risk_limit_usd": MODELED_PORTFOLIO_RISK_LIMIT_USD,
        "minimum_required": {
            "nonoverlapping_marks": MIN_PROSPECTIVE_TRADES,
            "entry_span_days": MIN_CALENDAR_SPAN_DAYS,
            "entry_weeks": MIN_UNIQUE_WEEKS,
        },
        "full_roundtrip_commissions_per_spread_usd":
            ROUND_TRIP_COMMISSION_USD,
        "extra_roundtrip_slippage_stress_usd": list(SLIPPAGE_STRESS_USD),
        "net_quote_mark_scenarios": metrics,
        "uncertainty_method": "DETERMINISTIC_ENTRY_WEEK_CLUSTER_BOOTSTRAP",
        "data_provenance_attested": False,
        "source_selection_preregistered_verified": False,
        "actual_broker_fills_verified": False,
    }


def load_private_csv(path: str) -> list[dict]:
    filename = Path(path).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]
    if filename == repo_root or repo_root in filename.parents:
        raise EvidenceError("Private market data may not be stored inside the public repository")
    if not filename.is_file() or filename.stat().st_size > MAX_PRIVATE_CSV_BYTES:
        raise EvidenceError("Private ledger missing or exceeds file-size limit")
    try:
        with filename.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or any(c not in reader.fieldnames for c in COLUMNS):
                raise EvidenceError("Private ledger header missing required columns")
            rows = list(reader)
    except (UnicodeError, csv.Error, OSError):
        raise EvidenceError("Private ledger could not be safely parsed") from None
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Private, read-only quote-marked options forward evaluator")
    parser.add_argument("--private-csv", required=True)
    args = parser.parse_args(argv)
    try:
        report = evaluate_paper_marks(load_private_csv(args.private_csv))
        print(json.dumps(report, sort_keys=True))
        return 0
    except EvidenceError as err:
        print("RESEARCH_VALIDATION_BLOCKED: " + str(err))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
