"""Phase-6 preparation only: block bootstrap complete PAPER outcomes.

No real capital, brokerage connectivity, orders, or scheduled execution.
Never run projections without a separate positive, independently validated
prospective paper outcome population and complete position follow-through.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
from statistics import median
import math
import random
from zoneinfo import ZoneInfo
from golden_goose_candidates import PaperOutcome,EdgeVerdict
ET=ZoneInfo('America/New_York')

@dataclass(frozen=True)
class ProbabilityReport:
    status: str
    paths: int
    simulated_trades_per_path: int
    chance_double_at_end: float | None
    chance_touch_half: float | None
    median_end_equity: float | None


def simulate_paper_paths(outcomes:list[PaperOutcome], edge:EdgeVerdict, *,
                         initial_equity:float=1000.0, trades_per_month:int=12,
                         paths:int=5000, seed:int=20261105) -> ProbabilityReport:
    if edge.status!='PAPER_PROMISING_REQUIRES_INDEPENDENT_FILLED_EXECUTION':
        return ProbabilityReport('BLOCKED_NO_VERIFIED_PROSPECTIVE_EDGE',0,0,None,None,None)
    if (len(outcomes)!=edge.total_selected or len(outcomes)!=edge.complete
        or len(outcomes)<100 or edge.weeks<12 or edge.lower_95_usd is None
        or edge.lower_95_usd<=0):
        return ProbabilityReport('BLOCKED_INCONSISTENT_EDGE_LEDGER',0,0,None,None,None)
    if not(500<=initial_equity<=100000) or not(1<=trades_per_month<=40) or not(100<=paths<=100000):
        raise ValueError('Invalid simulation bounds')
    if any(x.pnl_after_fees_and_slippage_usd is None or not x.observed_exit
           or not x.in_holdout or not x.source_is_bidask or x.overlapping_exposure
           or not(0<x.modeled_risk_usd<=100) for x in outcomes):
        return ProbabilityReport('BLOCKED_MISSING_OR_UNVERIFIED_OUTCOMES',0,0,None,None,None)
    weeks=defaultdict(list)
    for x in outcomes:
        weeks[x.entry_at.astimezone(ET).date().isocalendar()[:2]].append(x)
    clusters=[sorted(v,key=lambda x:x.entry_at) for _,v in sorted(weeks.items())]
    rng=random.Random(seed);ends=[];doubles=0;halves=0
    for _ in range(paths):
        equity=initial_equity;hit_half=False;count=0
        while count<trades_per_month:
            cluster=rng.choice(clusters)
            for x in cluster:
                if count>=trades_per_month:break
                stake=min(100.0,0.1*equity)
                mult=x.pnl_after_fees_and_slippage_usd/x.modeled_risk_usd
                # Debit loss bounded by upfront premium in this model; no live fills.
                outcome=max(-1.0,mult)*stake
                equity=max(0.0,equity+outcome)
                if equity<=0.5*initial_equity:hit_half=True
                count+=1
        ends.append(equity)
        doubles+=equity>=2*initial_equity
        halves+=hit_half
    return ProbabilityReport('HYPOTHETICAL_PAPER_SCENARIOS_NOT_REAL_WORLD_FORECAST',paths,
       trades_per_month,doubles/paths,halves/paths,median(ends))
