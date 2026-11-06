"""Private, point-in-time data model for Golden Goose research; no broker actions.

Rows from Tradier/D1 are normalized in memory. Store the accepted signal
manifest and its outcomes in private storage, not GitHub logs or artifacts.
Missing positions remain pending/unknown; they are never dropped as losers.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Mapping
import math
import re
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
SYMBOL_RE = re.compile(r'^[A-Z][A-Z0-9]{0,9}$')
OPTION_RE = re.compile(r'^([A-Z]{1,6})(\d{6})([CP])(\d{8})$')

class InvalidEvidence(ValueError):
    """The data must not be included as a sensitive value in this error."""


def utc(raw: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except (TypeError, ValueError, AttributeError) as e:
        raise InvalidEvidence('Invalid evidence timestamp') from e
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidEvidence('Missing timestamp timezone')
    return value.astimezone(timezone.utc)


def number(v, *, allow_zero=False) -> float:
    if isinstance(v, bool):
        raise InvalidEvidence('Boolean is not a market price')
    try:
        f = float(v)
    except (TypeError, ValueError) as e:
        raise InvalidEvidence('Invalid market number') from e
    if not math.isfinite(f) or (f < 0 if allow_zero else f <= 0):
        raise InvalidEvidence('Nonpositive or nonfinite market number')
    return f


@dataclass(frozen=True)
class StockQuote:
    symbol: str
    observed: datetime
    bid: float
    ask: float
    quote_at: datetime
    volume: int | None
    source: str
    @property
    def mid(self) -> float:
        return (self.bid+self.ask)/2


@dataclass(frozen=True)
class OptionQuote:
    root: str
    contract: str
    expiration: date
    strike: float
    right: str
    observed: datetime
    bid: float
    ask: float
    bid_at: datetime
    ask_at: datetime
    open_interest: int
    multiplier: int
    source: str
    @property
    def mid(self) -> float:
        return (self.bid+self.ask)/2


def market_session(t: datetime) -> bool:
    # Market holiday screening must be supplied by an exchange calendar upstream.
    v=t.astimezone(ET)
    return v.weekday()<5 and (9,30) <= (v.hour,v.minute) < (16,0)


def _fresh(t: datetime, q: datetime, max_age=120) -> bool:
    return 0 <= (t-q).total_seconds() <= max_age


def normalize_stock(row: Mapping, decision: datetime) -> StockQuote:
    symbol=row.get('symbol')
    if not isinstance(symbol,str) or not SYMBOL_RE.fullmatch(symbol):
        raise InvalidEvidence('Invalid underlying symbol')
    t=utc(row['observed_minute']); bid=number(row['bid']); ask=number(row['ask'])
    bt=utc(row['bid_at']); at=utc(row['ask_at'])
    if ask < bid or not (t<=decision and _fresh(decision,bt) and _fresh(decision,at)):
        raise InvalidEvidence('Stale, future, or crossed stock quote')
    vol=row.get('volume'); vol=None if vol is None else int(number(vol,allow_zero=True))
    source=row.get('source')
    if not isinstance(source,str) or 'tradier_' not in source.lower():
        raise InvalidEvidence('Missing authorized source identity')
    return StockQuote(symbol,t,bid,ask,max(bt,at),vol,source)


def normalize_option(row: Mapping, decision: datetime) -> OptionQuote:
    root=row.get('root') or row.get('underlying')
    contract=row.get('symbol')
    if not isinstance(root,str) or not SYMBOL_RE.fullmatch(root):
        raise InvalidEvidence('Invalid root')
    match=OPTION_RE.fullmatch(contract or '')
    if not match or match.group(1)!=root:
        raise InvalidEvidence('Adjusted or unknown option contract')
    expiration=date.fromisoformat(row['expiration'])
    if datetime.strptime(match.group(2),'%y%m%d').date()!=expiration:
        raise InvalidEvidence('Contract expiry mismatch')
    strike=number(row['strike']);right=row['right']
    if right not in ('C','P') or match.group(3)!=right or round(strike*1000)!=int(match.group(4)):
        raise InvalidEvidence('Contract side/strike mismatch')
    t=utc(row['observed_minute']); bid=number(row['bid']);ask=number(row['ask'])
    bt=utc(row['bid_at'] if 'bid_at' in row else row['bid_quote_at'])
    at=utc(row['ask_at'] if 'ask_at' in row else row['ask_quote_at'])
    if not(t<=decision and ask>=bid and _fresh(decision,bt) and _fresh(decision,at)):
        raise InvalidEvidence('Stale, future, or crossed option quote')
    oi=row.get('open_interest')
    oi=0 if oi is None else int(number(oi,allow_zero=True))
    if oi<0 or int(row.get('multiplier',100))!=100:
        raise InvalidEvidence('Nonstandard option deliverable')
    source=row.get('source')
    if not isinstance(source,str) or 'tradier_' not in source.lower():
        raise InvalidEvidence('Missing authorized quote provenance')
    return OptionQuote(root,contract,expiration,strike,right,t,bid,ask,bt,at,oi,100,source)


def compute_incremental_stock_volume(records: list[StockQuote]) -> tuple[tuple[datetime,int], ...]:
    if not records:
        return ()
    observed=sorted(records,key=lambda x:x.observed)
    out=[]; seen=set(); prev=None
    for q in observed:
        if q.observed in seen:
            raise InvalidEvidence('Duplicate stock quote minute')
        seen.add(q.observed)
        if q.volume is None or prev is None or q.symbol!=prev.symbol or q.observed.date()!=prev.observed.date():
            out.append((q.observed,None)) # unknown, NOT a zero-volume observation
        else:
            delta=q.volume-(prev.volume or 0)
            if delta<0:
                raise InvalidEvidence('Cumulative volume went backward')
            out.append((q.observed,delta))
        prev=q
    return tuple(out)


def check_minute_coverage(records: list[StockQuote]) -> dict:
    if not records:return {'count':0,'gaps':0,'duplicate':0,'first':None,'last':None}
    data=sorted(records,key=lambda x:(x.symbol,x.observed))
    gaps=0;dup=0
    for a,b in zip(data,data[1:]):
        if a.symbol!=b.symbol:continue
        dt=(b.observed-a.observed).total_seconds()
        if dt==0:dup+=1
        elif 60<dt and a.observed.astimezone(ET).date()==b.observed.astimezone(ET).date():gaps+=int(dt//60)-1
    return {'count':len(data),'gaps':gaps,'duplicate':dup,'first':data[0].observed.isoformat(),'last':data[-1].observed.isoformat()}


@dataclass
class PaperDecision:
    decision_id: str
    recorded_at: datetime
    root: str
    side: str
    status: str
    reason: str
    contracts: tuple[str,...]
    exit_quote_observed: bool = False
    exit_at: datetime | None = None


class PrivateDecisionLedger:
    """Separate selected, rejected, missing-entry and missing-exit cases."""
    def __init__(self):
        self._rows:dict[str,PaperDecision]={}

    def admit(self, entry:PaperDecision):
        if entry.decision_id in self._rows:
            raise InvalidEvidence('Duplicate decision id')
        if entry.status not in ('SELECTED','REJECTED','NO_FILL'):
            raise InvalidEvidence('Unknown decision disposition')
        if entry.status=='SELECTED' and len(entry.contracts)!=2:
            raise InvalidEvidence('Selected spread requires two contracts')
        self._rows[entry.decision_id]=entry

    def record_exit(self,decision_id:str,exit_at:datetime,quotes:tuple[OptionQuote,...]):
        item=self._rows[decision_id]
        if item.status!='SELECTED' or item.exit_quote_observed or exit_at<=item.recorded_at:
            raise InvalidEvidence('Exit cannot be matched to open paper position')
        if {q.contract for q in quotes}!={*item.contracts} or len(quotes)!=2:
            raise InvalidEvidence('Exit missing a contract')
        if any(not(_fresh(exit_at,q.bid_at) and _fresh(exit_at,q.ask_at)) for q in quotes):
            raise InvalidEvidence('Stale paper exit')
        item.exit_at=exit_at;item.exit_quote_observed=True

    def summary(self):
        rows=list(self._rows.values())
        return {'all':len(rows),'selected':sum(x.status=='SELECTED' for x in rows),
                'rejected':sum(x.status=='REJECTED' for x in rows),
                'nonfills':sum(x.status=='NO_FILL' for x in rows),
                'completed_selected':sum(x.status=='SELECTED' and x.exit_quote_observed for x in rows),
                'missing_selected_exit':sum(x.status=='SELECTED' and not x.exit_quote_observed for x in rows)}
