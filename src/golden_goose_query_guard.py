"""Bounded, read-only D1 query plans for private Golden Goose research.

No network, no secret access, no account/order endpoint, no raw data logging.
Callers MUST bind params as SQL parameters and charge Cloudflare's returned
rows_read to a persistent per-UTC-day budget before the next query.
This guard cannot prevent reads made by other Cloudflare applications.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
import re

MAX_ROWS_PER_QUERY = 390
MAX_INTERVAL_MINUTES = 390
MAX_ROWS_READ_PER_REQUEST = 25000
RESEARCH_DAILY_READ_BUDGET = 100000

_TABLES = {
    'legacy': ('quote_samples_v17', 'symbol', 'observed_minute',
               'observed_minute,symbol,kind,underlying,expiration,strike,right,bid,ask,bid_size_raw,ask_size_raw,bid_quote_at,ask_quote_at,captured_at,source'),
    'stock': ('broad_quotes_v21', 'symbol', 'observed_minute',
              'observed_minute,symbol,bid,ask,bid_size_raw,ask_size_raw,bid_at,ask_at,captured_at,volume,change_percentage,source'),
    'option': ('broad_options_v23', 'symbol', 'observed_minute',
               'observed_minute,root,symbol,expiration,dte,right,strike,bid,ask,bid_size_raw,ask_size_raw,bid_at,ask_at,captured_at,open_interest,delta,mid_iv,source'),
}
_SYMBOL = re.compile(r'^[A-Z][A-Z0-9]{0,31}$')

_OCC = re.compile(r'^([A-Z]{1,6})[0-9]{6}[CP][0-9]{8}$')

class QueryRejected(ValueError):
    pass


def _utc_iso(raw: str) -> datetime:
    if not isinstance(raw, str):
        raise QueryRejected('range needs UTC ISO timestamps')
    try:
        t = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError as e:
        raise QueryRejected('invalid UTC ISO timestamp') from e
    if t.utcoffset() != timedelta(0):
        raise QueryRejected('UTC required')
    return t

@dataclass(frozen=True)
class QueryPlan:
    sql: str
    params: tuple
    allowed_rows: int
    kind: str


def plan_range(kind: str, symbol: str, start: str, end: str, *, limit: int = MAX_ROWS_PER_QUERY) -> QueryPlan:
    if kind not in _TABLES:
        raise QueryRejected('unapproved table')
    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
        raise QueryRejected('unapproved symbol')
    s, e = _utc_iso(start), _utc_iso(end)
    if s >= e or e - s > timedelta(minutes=MAX_INTERVAL_MINUTES):
        raise QueryRejected('range must be positive and <= 390 minutes')
    if type(limit) is not int or not (1 <= limit <= MAX_ROWS_PER_QUERY):
        raise QueryRejected('query row limit outside budget')
    tab, col, time_col, fields = _TABLES[kind]
    # D1 stores minute timestamps as .000Z. Bare Z compares later lexically.
    lo=s.isoformat(timespec='milliseconds').replace('+00:00','Z')
    hi=e.isoformat(timespec='milliseconds').replace('+00:00','Z')
    if kind == 'option':
        # Existing index: ix_broad_options_v23_root_time (root,observed_minute).
        match=_OCC.fullmatch(symbol)
        if match is None:
            raise QueryRejected('standard unadjusted OCC contract required')
        sql=(f'SELECT {fields} FROM {tab} WHERE root=? '
             f'AND {time_col}>=? AND {time_col}<? AND symbol=? '
             f'ORDER BY {time_col} LIMIT ?')
        params=(match.group(1),lo,hi,symbol,limit)
    else:
        sql=(f'SELECT {fields} FROM {tab} WHERE {col}=? '
             f'AND {time_col}>=? AND {time_col}<? '
             f'ORDER BY {time_col} LIMIT ?')
        params=(symbol,lo,hi,limit)
    return QueryPlan(sql,params,limit,kind)


def plan_status(table: str, *, limit: int = 5) -> QueryPlan:
    if table not in ('collector_runs_v18', 'broad_runs_v21', 'broad_option_runs_v23', 'swing_runs_v19'):
        raise QueryRejected('unapproved run table')
    if type(limit) is not int or not (1 <= limit <= 5):
        raise QueryRejected('status limit outside budget')
    fields = ('observed_minute,state,error_code' if table != 'collector_runs_v18'
              else 'observed_minute,state')
    return QueryPlan(f'SELECT {fields} FROM {table} ORDER BY observed_minute DESC LIMIT ?',
                     (limit,), limit, 'status')


@dataclass
class DailyReadBudget:
    """Persist aggregate counters outside the shared D1 account between invocations."""
    day: str
    rows_read: int = 0
    requests: int = 0
    ceiling: int = RESEARCH_DAILY_READ_BUDGET

    def can_submit(self, current_day: str) -> bool:
        if current_day != self.day:
            return False  # explicit rollover only, no silent reset or clock travel
        return self.rows_read + MAX_ROWS_READ_PER_REQUEST <= self.ceiling

    def charge(self, meta: dict) -> None:
        if not isinstance(meta, dict):
            raise QueryRejected('D1 response lacks metered rows_read')
        n = meta.get('rows_read')
        if type(n) is not int or n < 0:
            raise QueryRejected('unmetered D1 response')
        self.rows_read += n
        self.requests += 1
        if n > MAX_ROWS_READ_PER_REQUEST:
            raise QueryRejected('single query exceeded permitted read budget')
        if self.rows_read > self.ceiling:
            raise QueryRejected('research read budget exhausted')

# The 2026-11-05 D1 quota incident was dominated by repeated full-history
# multi-way quote_samples_v17 self-joins. The existing primary-key index starts
# with observed_minute; an exact-minute read avoids that history-wide fan-out.
# This is a research snapshot only: it does not reconstruct a full option chain.
BOX_SOURCE = 'tradier_prod_rest_bidask_snapshot_v18_not_executable'


def plan_box_minute(root: str, observed_minute: str, *, limit: int = MAX_ROWS_PER_QUERY) -> QueryPlan:
    """One indexed minute of one root, never a D1 join or a full-table scan.

    The caller must inspect the returned D1 meta.rows_read and fail closed if
    the LIMIT is reached; a row limit does not itself cap database rows scanned.
    """
    if not isinstance(root, str) or not re.fullmatch(r'[A-Z]{1,6}', root):
        raise QueryRejected('standard underlying root required')
    minute = _utc_iso(observed_minute)
    if minute.second != 0 or minute.microsecond != 0:
        raise QueryRejected('exact UTC minute boundary required')
    if type(limit) is not int or not (1 <= limit <= MAX_ROWS_PER_QUERY):
        raise QueryRejected('box snapshot limit outside budget')
    iso = minute.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    sql = (
        'SELECT observed_minute,symbol,underlying,expiration,strike,right,'
        'bid,ask,bid_size_raw,ask_size_raw,bid_quote_at,ask_quote_at,source '
        'FROM quote_samples_v17 '
        "WHERE observed_minute=? AND underlying=? AND kind='option' AND source=? "
        'ORDER BY expiration,right,strike LIMIT ?'
    )
    return QueryPlan(sql, (iso, root, BOX_SOURCE, limit), limit, 'box_minute')
