from datetime import datetime,timedelta,date
import pytest
from golden_goose_data import OptionQuote,utc
from golden_goose_candidates import screen_debit_spreads,PaperOutcome,evaluate_edge
D=utc('2026-11-05T16:45:00Z')


def q(k,side,bid,ask,oi=1000,minutes_ago=0):
    exp=date(2026,11,16)
    ident=f'IWM261116{side}{int(k*1000):08d}'
    t=D-timedelta(minutes=minutes_ago)
    return OptionQuote('IWM',ident,exp,k,side,t,bid,ask,t,t,oi,100,
                       'tradier_prod_rest_broad_options_v23_paper_only')


def test_debit_spread_conservative_bidask_and_risk_reward():
    r=screen_debit_spreads([q(280,'C',.37,.40),q(281,'C',.24,.25)],
                           side='C',decision=D,equity_usd=1000)
    assert r.considered==1 and r.evidence_verdict=='UNPROVEN_NO_PROSPECTIVE_EDGE'
    assert len(r.candidates)==1
    c=r.candidates[0]
    assert c.quoted_debit_usd==pytest.approx(16.0)
    assert c.conservative_max_loss_usd==pytest.approx(22.6)
    assert c.max_net_expiration_profit_usd==pytest.approx(77.4)
    assert c.max_reward_risk==pytest.approx(77.4/22.6)
    assert c.status=='RESEARCH_ONLY_NOT_VALIDATED'


def test_direction_and_cost_floor():
    r=screen_debit_spreads([q(280,'C',.37,.40),q(281,'C',.24,.25)],
                            side='P',decision=D,equity_usd=1000)
    assert not r.candidates
    with pytest.raises(ValueError):
        screen_debit_spreads([],side='C',decision=D,equity_usd=1000,modeled_extra_cost_usd=0)


def test_risk_cap_includes_existing_open_positions():
    r=screen_debit_spreads([q(280,'C',.37,.40),q(281,'C',.24,.25)],
                           side='C',decision=D,equity_usd=1000,existing_open_risk_usd=90)
    assert not r.candidates and r.rejections[0].code=='RISK_CAP'


def test_liquidity_and_stale_leg_fail_closed():
    r=screen_debit_spreads([q(280,'C',.37,.40,oi=50),q(281,'C',.24,.25)],
                           side='C',decision=D,equity_usd=1000)
    assert r.rejections[0].code=='INSUFFICIENT_OI'
    r=screen_debit_spreads([q(280,'C',.37,.40,minutes_ago=3),q(281,'C',.24,.25)],
                           side='C',decision=D,equity_usd=1000)
    assert r.rejections[0].code=='STALE_PAIR'


def outcomes(pnl):
    first=utc('2026-01-05T15:00:00Z')
    return [PaperOutcome(f'id{i}',first+timedelta(days=i),pnl,True,True,True,False,100)
            for i in range(105)]


def test_evidence_missing_or_too_short_never_green():
    assert evaluate_edge(outcomes(20)[:40]).status=='UNPROVEN_INCOMPLETE_OR_TOO_SHORT'
    o=outcomes(20)
    o[-1]=PaperOutcome('id104',o[-1].entry_at,None,False,True,True,False,100)
    assert evaluate_edge(o).status=='UNPROVEN_INCOMPLETE_OR_TOO_SHORT'


def test_positive_synthetic_and_negative_synthetic_cases():
    a=evaluate_edge(outcomes(20))
    assert a.status=='PAPER_PROMISING_REQUIRES_INDEPENDENT_FILLED_EXECUTION'
    assert a.lower_95_usd>0 and a.days>=90
    b=evaluate_edge(outcomes(-10))
    assert b.status=='REJECT_NO_POSITIVE_NET_EDGE' and b.lower_95_usd<0


def test_duplicates_and_timestamps_rejected():
    o=outcomes(20)
    with pytest.raises(ValueError):evaluate_edge([o[0],o[0]])
    with pytest.raises(ValueError):
        evaluate_edge([PaperOutcome('a',datetime(2026,1,1),5,True,True,True)])
