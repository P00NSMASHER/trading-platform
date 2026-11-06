"""Predeclared, read-only signal rules for prospective options research.

No win-rate inference, broker calls, orders, or account-dependent output.
All price/volume inputs must be as-of the decision time. Baselines must use
prior completed sessions; the same event must not be tuned on its own outcome.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo
import math

ET = ZoneInfo('America/New_York')

class SignalRejected(ValueError):
    pass

@dataclass(frozen=True)
class Bar:
    at: datetime
    open: float
    high: float
    low: float
    close: float
    minute_volume: int

@dataclass(frozen=True)
class Catalyst:
    event_id: str
    publicly_available_at: datetime
    source_verified: bool
    kind: str

@dataclass(frozen=True)
class SignalResult:
    state: str
    reason: str
    side: str | None
    decision_at: datetime
    relative_volume: float | None
    opening_range_high: float | None
    opening_range_low: float | None


def _check_bar(bar:Bar, decision:datetime):
    if bar.at.tzinfo is None or decision.tzinfo is None or bar.at > decision:
        raise SignalRejected('Future or untimed bar')
    if not all(math.isfinite(x) and x>0 for x in (bar.open,bar.high,bar.low,bar.close)):
        raise SignalRejected('Invalid prices')
    if bar.low>min(bar.open,bar.close) or bar.high<max(bar.open,bar.close):
        raise SignalRejected('Invalid OHLC bounds')
    if type(bar.minute_volume) is not int or bar.minute_volume<0:
        raise SignalRejected('Missing or invalid minute volume')


def evaluate_post_catalyst(
    bars:list[Bar], historical_minute_volumes:list[int], catalyst:Catalyst,
    decision:datetime, market_direction:int, sector_direction:int,
    *, volume_multiple:float=1.5, retest_tolerance:float=0.0015,
) -> SignalResult:
    """Return a screened hypothesis, not a trade order.

    Opening range: 09:30-09:59 ET. Decision from 10:05 onward, after a
    post-range retest with an earlier bar's touch of the boundary.
    Returns explicit rejection for unavailable history, unknown event, bad
    data or market disagreement rather than a fabricated signal.
    """
    reject=lambda reason:SignalResult('REJECTED',reason,None,decision,None,None,None)
    if decision.tzinfo is None:
        raise SignalRejected('Decision timestamp must have timezone')
    now_et=decision.astimezone(ET)
    if now_et.weekday()>4 or not (10,5)<=(now_et.hour,now_et.minute)<(15,30):
        return reject('OUT_OF_SESSION_OR_OPENING_RANGE')
    if not catalyst.source_verified or not catalyst.event_id or not catalyst.kind:
        return reject('CATALYST_UNVERIFIED')
    if catalyst.publicly_available_at.tzinfo is None or not (
        decision - timedelta(hours=4) <= catalyst.publicly_available_at <= decision
    ):
        return reject('CATALYST_NOT_KNOWN_AS_OF_DECISION')
    if len(historical_minute_volumes)<20 or any(type(x) is not int or x<0 for x in historical_minute_volumes):
        return reject('MISSING_PRIOR_COMPLETED_SESSION_BASELINE')
    if market_direction not in (-1,1) or sector_direction not in (-1,1):
        return reject('MARKET_OR_SECTOR_UNKNOWN')
    if len(bars)<30:
        return reject('OPENING_RANGE_INCOMPLETE')
    times=[b.at for b in bars]
    if times!=sorted(times) or len(set(times))!=len(times):
        return reject('DUPLICATE_OR_NONMONOTONIC_BARS')
    for b in bars:
        _check_bar(b,decision)
    today=now_et.date()
    intraday=[b for b in bars if b.at.astimezone(ET).date()==today]
    range_bars=[b for b in intraday if b.at.astimezone(ET).hour==9 and 30<=b.at.astimezone(ET).minute<60]
    if len(range_bars)!=30 or len({(b.at.astimezone(ET).hour,b.at.astimezone(ET).minute) for b in range_bars})!=30:
        return reject('OPENING_RANGE_INCOMPLETE')
    r_hi=max(b.high for b in range_bars); r_lo=min(b.low for b in range_bars)
    confirm=[b for b in intraday if (10,0)<=(b.at.astimezone(ET).hour,b.at.astimezone(ET).minute)
             and b.at<=decision]
    if len(confirm)<2:return reject('MISSING_POST_EVENT_BARS')
    last=confirm[-1]; trailing=confirm[:-1]
    bline=median(historical_minute_volumes)
    if bline<=0:return reject('EMPTY_PRIOR_VOLUME_BASELINE')
    rvol=last.minute_volume/bline
    direction=1 if last.close>r_hi else -1 if last.close<r_lo else 0
    if direction==0:return SignalResult('REJECTED','NO_BREAKOUT',None,decision,rvol,r_hi,r_lo)
    if direction!=market_direction or direction!=sector_direction:
        return SignalResult('REJECTED','DIRECTION_NOT_CONFIRMED',None,decision,rvol,r_hi,r_lo)
    if rvol<volume_multiple:
        return SignalResult('REJECTED','RELATIVE_VOLUME_LOW',None,decision,rvol,r_hi,r_lo)
    touched=any((b.low<=r_hi*(1+retest_tolerance) and b.close>=r_hi)
                if direction==1 else (b.high>=r_lo*(1-retest_tolerance) and b.close<=r_lo)
                for b in trailing)
    if not touched:return SignalResult('REJECTED','NO_CONFIRMED_RETEST',None,decision,rvol,r_hi,r_lo)
    return SignalResult('RESEARCH_SIGNAL','PREREGISTERED_SCREEN_PASSED',
                        'C' if direction==1 else 'P',decision,rvol,r_hi,r_lo)


def chronological_split(dates:list,holdout_fraction=0.25):
    """No random shuffle or within-day splitting; reject tiny discovery sets."""
    ordered=sorted(set(dates))
    if len(ordered)<20 or not 0.1<=holdout_fraction<=0.5:
        raise SignalRejected('Need >=20 distinct sessions and declared split')
    cut=int(len(ordered)*(1-holdout_fraction))
    return frozenset(ordered[:cut]),frozenset(ordered[cut:])
