"""No-network D1 read-budget and box-math regression tests (synthetic only)."""
from datetime import datetime, timezone
import sqlite3

import pytest

from golden_goose_box_research import (
    ACCOUNT_RESERVED_ROWS, RESEARCH_ONLY, analyze_box_rows,
    require_account_headroom, run_box_minute,
)
from golden_goose_query_guard import (
    DailyReadBudget, QueryRejected, plan_box_minute,
)

MINUTE = "2026-11-05T17:14:00.000Z"
NOW = datetime(2026, 11, 6, 11, 30, tzinfo=timezone.utc)
USAGE = {"rows_read": 100000, "day": "2026-11-06",
         "as_of": "2026-11-06T11:29:45Z"}
SOURCE = "tradier_prod_rest_bidask_snapshot_v18_not_executable"


def option(strike, right, bid, ask, *, root="SPY", minute=MINUTE):
    occ = f"{root}261106{right}{round(strike * 1000):08d}"
    return {"observed_minute": minute, "symbol": occ, "underlying": root,
            "expiration": "2026-11-06", "strike": strike, "right": right,
            "bid": bid, "ask": ask, "bid_quote_at": "2026-11-05T17:14:20Z",
            "ask_quote_at": "2026-11-05T17:14:20Z", "source": SOURCE,
            "bid_size_raw": 20, "ask_size_raw": 20}


def four_legs():
    return [option(660, "C", 1.9, 2.0),
            option(661, "C", 0.7, 0.8),
            option(660, "P", 0.7, 0.8),
            option(661, "P", 1.9, 2.0)]


def test_plan_uses_existing_observed_minute_index_without_joins():
    plan = plan_box_minute("SPY", MINUTE, limit=60)
    assert "WHERE observed_minute=?" in plan.sql
    assert "AND underlying=?" in plan.sql
    assert "JOIN" not in plan.sql.upper()
    assert "LIMIT ?" in plan.sql
    assert "ORDER BY" not in plan.sql
    assert plan.params == (MINUTE, "SPY", SOURCE, 60)


def test_real_sqlite_index_plan_and_deterministic_box_arithmetic():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE quote_samples_v17 (
      observed_minute TEXT, symbol TEXT, underlying TEXT, expiration TEXT,
      strike REAL, right TEXT, bid REAL, ask REAL, bid_quote_at TEXT,
      ask_quote_at TEXT, kind TEXT, source TEXT, bid_size_raw INT, ask_size_raw INT,
      PRIMARY KEY (observed_minute,symbol))""")
    fields = ["observed_minute", "symbol", "underlying", "expiration", "strike",
              "right", "bid", "ask", "bid_quote_at", "ask_quote_at", "kind",
              "source", "bid_size_raw", "ask_size_raw"]
    def insert(row):
        r = dict(row, kind="option")
        db.execute(f"INSERT INTO quote_samples_v17({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
                   [r.get(f) for f in fields])
    for row in four_legs():
        insert(row)
    extra = option(660, "C", 0.5, 0.6, root="QQQ")
    insert(extra)
    # Another minute must be excluded rather than cross-joined into results.
    insert(option(660, "C", 0.8, 0.9, minute="2026-11-05T17:15:00.000Z"))
    plan = plan_box_minute("SPY", MINUTE)
    rows = [dict(x) for x in db.execute(plan.sql, plan.params).fetchall()]
    explain = db.execute("EXPLAIN QUERY PLAN " + plan.sql, plan.params).fetchall()
    assert len(rows) == 4
    assert any("SEARCH quote_samples_v17 USING INDEX" in x["detail"] for x in explain)
    candidates = analyze_box_rows(plan, rows)
    assert len(candidates) == 1
    box = candidates[0]
    assert (box.lower_strike, box.upper_strike) == (660, 661)
    assert box.buy_discount_usd == pytest.approx(-160)
    assert box.sell_premium_usd == pytest.approx(120)
    assert box.status == RESEARCH_ONLY
    db.close()


def test_read_only_executor_runs_once_and_charges_actual_meter():
    budget = DailyReadBudget(day="2026-11-06")
    submissions = []
    def execute(plan):
        submissions.append(plan)
        return {"success": True, "results": four_legs(), "meta": {"rows_read": 54}}
    snapshot = run_box_minute("SPY", MINUTE, account_usage=USAGE, now=NOW,
                              daily_budget=budget, execute_read=execute)
    assert len(submissions) == 1
    assert snapshot.contracts == 4 and snapshot.rows_read == 54
    assert not snapshot.complete_chain
    assert budget.requests == 1 and budget.rows_read == 54
    assert len(snapshot.candidates) == 1


@pytest.mark.parametrize("usage", [
    None,
    {},
    {"rows_read": 4_600_000, "day": "2026-11-06",
     "as_of": "2026-11-06T11:29:45Z"},
    {"rows_read": True, "day": "2026-11-06",
     "as_of": "2026-11-06T11:29:45Z"},
    {"rows_read": 1, "day": "2026-11-05",
     "as_of": "2026-11-05T11:29:45Z"},
    {"rows_read": 1, "day": "2026-11-06",
     "as_of": "2026-11-06T11:00:00Z"},
    {"rows_read": 1, "day": "2026-11-06",
     "as_of": "2026-11-06T11:40:00Z"},
])
def test_bad_quota_observation_prevents_any_d1_call(usage):
    called = []
    with pytest.raises(QueryRejected):
        run_box_minute("SPY", MINUTE, account_usage=usage, now=NOW,
                       daily_budget=DailyReadBudget(day="2026-11-06"),
                       execute_read=lambda _: called.append(True))
    assert called == []


def test_daily_budget_and_cross_day_prevent_any_submission():
    for budget in (DailyReadBudget(day="2026-11-05"),
                   DailyReadBudget(day="2026-11-06", rows_read=99999)):
        called = []
        with pytest.raises(QueryRejected):
            run_box_minute("SPY", MINUTE, account_usage=USAGE, now=NOW,
                           daily_budget=budget,
                           execute_read=lambda _: called.append(True))
        assert called == []


def test_missing_or_over_budget_meter_fails_closed():
    for meta in ({}, {"rows_read": 25001}, {"rows_read": -1}):
        budget = DailyReadBudget(day="2026-11-06")
        with pytest.raises(QueryRejected):
            run_box_minute("SPY", MINUTE, account_usage=USAGE, now=NOW,
                           daily_budget=budget,
                           execute_read=lambda _: {
                               "success": True, "meta": meta, "results": four_legs()
                           })


@pytest.mark.parametrize("bad", [
    "SPY;", "", "SPY1", "SEVENAA", "spy",
])
def test_invalid_root_never_reaches_database(bad):
    with pytest.raises(QueryRejected):
        plan_box_minute(bad, MINUTE)


def test_limited_or_corrupted_quote_sets_fail_instead_of_false_zero():
    plan = plan_box_minute("SPY", MINUTE, limit=4)
    for rows in (four_legs(), four_legs()[:2] + four_legs()[:1],
                 [dict(four_legs()[0], underlying="QQQ")],
                 [dict(four_legs()[0], bid_quote_at="2026-11-05T17:00:00Z")],
                 [dict(four_legs()[0], symbol="SPY_BAD")]):
        with pytest.raises(QueryRejected):
            analyze_box_rows(plan, rows)
    assert analyze_box_rows(plan, four_legs()[:2]) == ()


def test_missing_leg_does_not_claim_full_chain_or_executable_edge():
    plan = plan_box_minute("SPY", MINUTE)
    rows = four_legs()[:3]
    got = analyze_box_rows(plan, rows)
    assert got == ()
    assert ACCOUNT_RESERVED_ROWS >= 25000
