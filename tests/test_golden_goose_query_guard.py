import pytest
from golden_goose_query_guard import (
    DailyReadBudget, QueryRejected, plan_range, plan_status,
)


def test_range_only_indexed_bound_symbol_and_period():
    q = plan_range('option','QQQ261116C00650000','2026-11-05T14:00:00Z','2026-11-05T15:00:00Z',limit=61)
    assert 'FROM broad_options_v23 WHERE root=?' in q.sql
    assert 'AND symbol=?' in q.sql and 'LIMIT ?' in q.sql
    assert q.params == ('QQQ','2026-11-05T14:00:00.000Z','2026-11-05T15:00:00.000Z','QQQ261116C00650000',61)
    assert 'QQQ261116' not in q.sql


@pytest.mark.parametrize('kind,symbol,start,end,limit', [
    ('bad','SPY','2026-11-05T14:00:00Z','2026-11-05T15:00:00Z',50),
    ('legacy',"SPY'; DROP TABLE x",'2026-11-05T14:00:00Z','2026-11-05T15:00:00Z',50),
    ('stock','SPY','2026-11-05T14:00:00Z','2026-11-05T21:00:00Z',50),
    ('option','SPY','2026-11-05T16:00:00Z','2026-11-05T15:00:00Z',50),
    ('option','SPY','2026-11-05T16:00:00Z','2026-11-05T17:00:00Z',10000),
    ('stock','SPY','2026-11-05T16:00:00-05:00','2026-11-05T17:00:00-05:00',50),
])
def test_invalid_ranges_fail(kind,symbol,start,end,limit):
    with pytest.raises(QueryRejected):
        plan_range(kind,symbol,start,end,limit=limit)


def test_status_whitelist():
    assert plan_status('broad_option_runs_v23').allowed_rows == 5
    with pytest.raises(QueryRejected):
        plan_status('sqlite_master')


def test_daily_ledger_metered_and_fail_closed():
    b=DailyReadBudget(day='2026-11-05')
    assert b.can_submit('2026-11-05')
    assert not b.can_submit('2026-11-06')
    b.charge({'rows_read':500})
    assert b.rows_read == 500 and b.requests==1
    with pytest.raises(QueryRejected):
        b.charge({'rows_read':30000})
    assert b.rows_read == 30500
    with pytest.raises(QueryRejected):
        b.charge({'changes':1})


def test_int_only_limit():
    with pytest.raises(QueryRejected):
        plan_range('stock','SPY','2026-11-05T14:00:00Z','2026-11-05T14:03:00Z',limit=True)

def test_exact_start_minute_and_index_path():
    q=plan_range('stock','SPY','2026-11-05T14:00:00Z','2026-11-05T14:03:00Z')
    assert q.params[1] == '2026-11-05T14:00:00.000Z'
    assert q.params[2] == '2026-11-05T14:03:00.000Z'
    assert 'FROM broad_quotes_v21 WHERE symbol=?' in q.sql
    with pytest.raises(QueryRejected):
        plan_range('option','NOT_A_STANDARD_CONTRACT','2026-11-05T14:00:00Z','2026-11-05T14:03:00Z')
