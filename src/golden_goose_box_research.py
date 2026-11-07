"""Bounded, read-only option box research on a single historical snapshot.

NEVER use history-wide D1 multi-way JOINs. Call with a current Cloudflare
account-wide quota observation and an externally persisted DailyReadBudget.
No credentials, network, orders, customer content or real-money decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping

from golden_goose_data import InvalidEvidence, normalize_option
from golden_goose_query_guard import (
    DailyReadBudget, QueryPlan, QueryRejected, plan_box_minute,
)

ACCOUNT_FREE_ROWS_PER_DAY = 5_000_000
ACCOUNT_RESERVED_ROWS = 500_000
MAX_ACCOUNT_OBSERVATION_AGE_SECONDS = 120
RESEARCH_ONLY = "RESEARCH_ONLY_NONEXECUTABLE_SNAPSHOT"


@dataclass(frozen=True)
class BoxCandidate:
    expiration: str
    lower_strike: float
    upper_strike: float
    buy_discount_usd: float
    sell_premium_usd: float
    status: str = RESEARCH_ONLY


@dataclass(frozen=True)
class BoxSnapshot:
    root: str
    observed_minute: str
    contracts: int
    rows_read: int
    candidates: tuple[BoxCandidate, ...]
    complete_chain: bool = False  # A rotating snapshot is never a complete chain.


def _utc(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise QueryRejected("Invalid quota timestamp") from exc
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise QueryRejected("UTC quota timestamp required")
    return value.astimezone(timezone.utc)


def require_account_headroom(usage: Mapping, now: datetime) -> None:
    """Fail closed before any D1 read when the account counter is stale/unknown."""
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise QueryRejected("Current UTC time required")
    if not isinstance(usage, Mapping):
        raise QueryRejected("Authenticated account-wide D1 usage required")
    rows = usage.get("rows_read")
    if type(rows) is not int or not 0 <= rows <= ACCOUNT_FREE_ROWS_PER_DAY:
        raise QueryRejected("Untrusted account-wide row count")
    observed = _utc(usage.get("as_of"))
    if observed.date() != now.date() or not 0 <= (now - observed).total_seconds() <= MAX_ACCOUNT_OBSERVATION_AGE_SECONDS:
        raise QueryRejected("Stale account-wide quota evidence")
    if usage.get("day") != now.date().isoformat():
        raise QueryRejected("Account quota observation belongs to another day")
    if rows > ACCOUNT_FREE_ROWS_PER_DAY - ACCOUNT_RESERVED_ROWS:
        raise QueryRejected("Account-wide D1 headroom reserved for other services")


def analyze_box_rows(plan: QueryPlan, rows: list[Mapping]) -> tuple[BoxCandidate, ...]:
    """Compute equivalent gross four-leg arithmetic in memory, never in D1.

    Validates all rows before accepting *any* candidate. Retains no full-chain
    or executable-fill inference; a missing leg is UNKNOWN, not a failed trade.
    """
    if plan.kind != "box_minute" or type(rows) is not list or len(rows) >= plan.allowed_rows:
        raise QueryRejected("Box result is incomplete or not from a bounded snapshot")
    minute_iso, root, source, _ = plan.params
    minute = _utc(minute_iso)
    decision = minute + timedelta(seconds=59)
    quotes = {}
    for row in rows:
        try:
            q = normalize_option(row, decision)
        except (InvalidEvidence, KeyError, TypeError, ValueError) as exc:
            raise QueryRejected("Invalid or stale option snapshot evidence") from exc
        if (
            q.root != root or q.observed != minute or q.source != source
            or row.get("underlying") != root
        ):
            raise QueryRejected("Option snapshot scope mismatch")
        key = (q.expiration.isoformat(), q.strike, q.right)
        if key in quotes:
            raise QueryRejected("Duplicate option contract in minute snapshot")
        quotes[key] = q
    expirations = sorted({key[0] for key in quotes})
    found: list[BoxCandidate] = []
    for expiration in expirations:
        strikes = sorted({key[1] for key in quotes if key[0] == expiration})
        for low in strikes:
            for high in strikes:
                width = high - low
                if width > 2.000001:
                    break
                if width < 0.999999:
                    continue
                legs = [quotes.get((expiration, low, "C")),
                        quotes.get((expiration, high, "C")),
                        quotes.get((expiration, low, "P")),
                        quotes.get((expiration, high, "P"))]
                if any(leg is None for leg in legs):
                    continue
                c1, c2, p1, p2 = legs
                buy = width - c1.ask + c2.bid - p2.ask + p1.bid
                sell = c1.bid - c2.ask + p2.bid - p1.ask - width
                found.append(BoxCandidate(expiration, low, high,
                                          round(100 * buy, 2), round(100 * sell, 2)))
    return tuple(found)


def run_box_minute(
    root: str,
    minute: str,
    *,
    account_usage: Mapping,
    now: datetime,
    daily_budget: DailyReadBudget,
    execute_read: Callable[[QueryPlan], Mapping],
    limit: int = 390,
) -> BoxSnapshot:
    """Execute only an indexed, one-minute SELECT after fresh quota preflight.

    execute_read must unwrap D1's read-only .all() response to a dict containing
    success, results and meta.rows_read. Persist daily_budget outside D1 after
    every call; callers must prohibit concurrent uncoordinated budget updates.
    """
    plan = plan_box_minute(root, minute, limit=limit)
    require_account_headroom(account_usage, now)
    if daily_budget.day != now.date().isoformat() or not daily_budget.can_submit(daily_budget.day):
        raise QueryRejected("Research daily quota ledger missing or exhausted")
    response = execute_read(plan)
    if not isinstance(response, Mapping):
        raise QueryRejected("Missing metered D1 response")
    # Charge even a failed execution if Cloudflare returned a real meter.
    daily_budget.charge(response.get("meta"))
    if response.get("success") is not True:
        raise QueryRejected("D1 snapshot read failed")
    rows = response.get("results")
    if type(rows) is not list:
        raise QueryRejected("Malformed D1 row result")
    candidates = analyze_box_rows(plan, rows)
    return BoxSnapshot(
        root=root, observed_minute=plan.params[0], contracts=len(rows),
        rows_read=response["meta"]["rows_read"], candidates=candidates,
    )
