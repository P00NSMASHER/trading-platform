"""Pure, non-executing defined-risk debit-spread research and evidence gate.

An attractive theoretical payoff is never a positive-expectancy claim. The
module has no network, credentials, account inspection, or trading functions.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date,datetime
from collections import defaultdict
from statistics import mean
from zoneinfo import ZoneInfo
import math
import random

from golden_goose_data import OptionQuote

ET = ZoneInfo('America/New_York')
MODELED_TOTAL_FEES_SLIPPAGE_USD = 6.60
MAX_POSITION_LOSS_USD = 100.0
MAX_CONCURRENT_LOSS_USD = 100.0
MIN_REWARD_RISK = 3.0

@dataclass(frozen=True)
class DebitSpread:
    root: str
    expiry: date
    side: str
    buy_contract: str
    sell_contract: str
    buy_strike: float
    sell_strike: float
    quoted_debit_usd: float
    conservative_max_loss_usd: float
    max_net_expiration_profit_usd: float
    max_reward_risk: float
    status: str = 'RESEARCH_ONLY_NOT_VALIDATED'

@dataclass(frozen=True)
class Reject:
    buy_contract: str
    sell_contract: str
    code: str

@dataclass(frozen=True)
class SelectionReport:
    candidates: tuple[DebitSpread,...]
    rejections: tuple[Reject,...]
    considered: int
    evidence_verdict: str

@dataclass(frozen=True)
class PaperOutcome:
    decision_id: str
    entry_at: datetime
    pnl_after_fees_and_slippage_usd: float | None
    observed_exit: bool
    in_holdout: bool
    source_is_bidask: bool
    overlapping_exposure: bool = False
    modeled_risk_usd: float = 100.0

@dataclass(frozen=True)
class EdgeVerdict:
    status: str
    total_selected: int
    complete: int
    days: int
    weeks: int
    lower_95_usd: float | None
    mean_net_usd: float | None


def evaluate_edge(outcomes:list[PaperOutcome], *, seed=20261105, resamples=1500) -> EdgeVerdict:
    if not outcomes:
        return EdgeVerdict('UNPROVEN_NO_DATA',0,0,0,0,None,None)
    ids=[x.decision_id for x in outcomes]
    if len(ids)!=len(set(ids)):
        raise ValueError('Duplicate paper decision id')
    if any(x.entry_at.tzinfo is None for x in outcomes):
        raise ValueError('Untimed paper outcomes are invalid')
    days={x.entry_at.astimezone(ET).date() for x in outcomes}
    weeks={d.isocalendar()[:2] for d in days}
    complete=[x for x in outcomes if x.observed_exit and x.pnl_after_fees_and_slippage_usd is not None
              and x.source_is_bidask and not x.overlapping_exposure and x.in_holdout]
    if any(not math.isfinite(x.modeled_risk_usd) or x.modeled_risk_usd<=0 or x.modeled_risk_usd>100 for x in outcomes):
        raise ValueError('Invalid modeled risk')
    if any(x.pnl_after_fees_and_slippage_usd is not None and not math.isfinite(x.pnl_after_fees_and_slippage_usd) for x in outcomes):
        raise ValueError('Nonfinite paper P/L')
    if len(outcomes)<100 or len(complete)!=len(outcomes) or len(weeks)<12 or (max(days)-min(days)).days<90:
        return EdgeVerdict('UNPROVEN_INCOMPLETE_OR_TOO_SHORT',len(outcomes),len(complete),len(days),len(weeks),None,None)
    by_week=defaultdict(list)
    for x in complete:
        d=x.entry_at.astimezone(ET).date()
        by_week[d.isocalendar()[:2]].append(x.pnl_after_fees_and_slippage_usd)
    groups=list(by_week.values())
    rng=random.Random(seed)
    means=[]
    for _ in range(resamples):
        sample=[]
        for _ in groups:
            sample.extend(rng.choice(groups))
        means.append(mean(sample))
    means.sort()
    lower=means[int(.025*len(means))]
    observed=mean(x.pnl_after_fees_and_slippage_usd for x in complete)
    status='PAPER_PROMISING_REQUIRES_INDEPENDENT_FILLED_EXECUTION' if lower>0 and observed>0 else 'REJECT_NO_POSITIVE_NET_EDGE'
    return EdgeVerdict(status,len(outcomes),len(complete),len(days),len(weeks),lower,observed)


def screen_debit_spreads(
    quotes:list[OptionQuote], *, side:str, decision:datetime, equity_usd:float,
    existing_open_risk_usd:float=0, edge:EdgeVerdict|None=None,
    modeled_extra_cost_usd:float=MODELED_TOTAL_FEES_SLIPPAGE_USD,
) -> SelectionReport:
    if side not in ('C','P') or decision.tzinfo is None or not math.isfinite(equity_usd) or equity_usd<=0:
        raise ValueError('Invalid screen inputs')
    if not math.isfinite(existing_open_risk_usd) or existing_open_risk_usd<0:
        raise ValueError('Invalid existing exposure')
    if modeled_extra_cost_usd<MODELED_TOTAL_FEES_SLIPPAGE_USD or not math.isfinite(modeled_extra_cost_usd):
        raise ValueError('Cost assumption below conservative research floor')
    max_available=max(0,min(MAX_POSITION_LOSS_USD,0.1*equity_usd,
                            MAX_CONCURRENT_LOSS_USD-existing_open_risk_usd))
    filtered=[q for q in quotes if q.right==side]
    rejects=[];accept=[];seen=set();considered=0
    for buy in filtered:
        for sell in filtered:
            if buy.contract==sell.contract:continue
            if buy.root!=sell.root or buy.expiration!=sell.expiration:continue
            if ((side=='C' and buy.strike>=sell.strike) or
                (side=='P' and buy.strike<=sell.strike)):
                continue
            pair=(buy.contract,sell.contract)
            if pair in seen:continue
            seen.add(pair);considered+=1
            def reject(reason):rejects.append(Reject(buy.contract,sell.contract,reason))
            dte=(buy.expiration-decision.astimezone(ET).date()).days
            if not 5<=dte<=14:reject('DTE_OUT_OF_RANGE');continue
            if buy.observed>decision or sell.observed>decision or (decision-min(buy.observed,sell.observed)).total_seconds()>120:
                reject('STALE_PAIR');continue
            if min(buy.open_interest,sell.open_interest)<100:reject('INSUFFICIENT_OI');continue
            if (buy.ask-buy.bid)/buy.mid>0.10 or (sell.ask-sell.bid)/sell.mid>0.10:
                reject('WIDE_MARKET');continue
            width=abs(sell.strike-buy.strike)
            if not 0.5<=width<=3:reject('WIDTH_OUT_OF_RANGE');continue
            debit=(buy.ask-sell.bid)*100
            if debit<=0:reject('INVALID_DEBIT');continue
            risk=debit+modeled_extra_cost_usd
            max_profit=width*100-debit-modeled_extra_cost_usd
            if risk>max_available+1e-9:reject('RISK_CAP');continue
            if max_profit<=0 or max_profit/risk<MIN_REWARD_RISK:
                reject('INSUFFICIENT_REWARD_TO_RISK');continue
            accept.append(DebitSpread(buy.root,buy.expiration,side,buy.contract,sell.contract,
                         buy.strike,sell.strike,round(debit,2),round(risk,2),
                         round(max_profit,2),max_profit/risk))
    accept.sort(key=lambda x:(-x.max_reward_risk,x.conservative_max_loss_usd,x.buy_contract,x.sell_contract))
    # Research candidates exist independently of validated edge: never emit orders.
    return SelectionReport(tuple(accept),tuple(rejects),considered,
                           edge.status if edge else 'UNPROVEN_NO_PROSPECTIVE_EDGE')
