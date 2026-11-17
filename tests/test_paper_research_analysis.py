"""Synthetic tests only; never import the user's private archive into CI."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import subprocess
import pytest
from paper_research_analysis import (canonical, sha, private_write, seal_archive, load_archive,
    summarize_costs, cluster_interval, prospective_scorecard, valid_quote)


def quote():
    return dict(observed_minute='2026-11-17T15:30:00Z',captured_at='2026-11-17T15:30:05Z',bid_quote_at='2026-11-17T15:30:03Z',ask_quote_at='2026-11-17T15:30:04Z',source='tradier_test_fixture',kind='option',symbol='SPY261123C00500000',underlying='SPY',expiration='2026-11-23',right='C',strike=500,bid=1.,ask=1.10)


def test_spread_fees_adverse_fill_and_possible_no_fill_arithmetic():
    out=summarize_costs([quote()])
    r=out['by_symbol_expiration'][0]
    assert r['median_spread_usd']==10
    assert r['median_cost_usd']==15.30
    assert r['median_stress_cost_usd']==25.30
    assert r['share_cost_above_10pct_premium']==1
    assert r['share_cost_above_25pct_premium']==0
    assert r['hypothetical_10usd_gross_expected_net_per_attempt']['0.5']==-2.65


def test_bad_identity_future_timestamp_and_ambiguous_clock_excluded():
    for changed in [{'strike':501},{'expiration':'2026-11-24'},{'ask_quote_at':'2026-11-17T15:30:08Z'},{'bid_quote_at':'2026-11-17T15:30:03'},{'source':'synthetic'}]:
        assert valid_quote({**quote(),**changed}) is not None


def test_incremental_archive_integrity_idempotency_and_duplicate_conflict(tmp_path):
    q=quote();payload={'day':'2026-11-17','evidence_mode':'historical_research','extracts':[{'query':{'sql':'SELECT indexed bounded'},'result':{'success':True,'result':[{'success':True,'meta':{'rows_read':1,'rows_written':0},'results':[q]}]}}]}
    p=tmp_path/'2026-11-17.json';p.write_bytes(canonical(payload))
    first=seal_archive(tmp_path);assert seal_archive(tmp_path)==first
    rows,manifest=load_archive(tmp_path);assert rows==[q]
    p.write_bytes(canonical({**payload,'evidence_mode':'synthetic'}))
    with pytest.raises(ValueError,match='changed'):seal_archive(tmp_path)
    with pytest.raises(ValueError,match='hash'):load_archive(tmp_path)


def test_private_lock_refuses_rewrite(tmp_path):
    p=tmp_path/'evaluation.json';private_write(p,b'first',immutable=True);private_write(p,b'first',immutable=True)
    with pytest.raises(ValueError,match='immutable'):private_write(p,b'second',immutable=True)
    assert p.stat().st_mode&0o077==0


def test_week_cluster_bootstrap_does_not_inflate_dependent_repetitions():
    base=[('2026-10-05T15:00:00Z',-10),('2026-10-12T15:00:00Z',10)]
    assert cluster_interval(base)==cluster_interval(base*50)
    ci=cluster_interval(base)
    assert ci['weeks']==2 and ci['lower']==-10 and ci['upper']==10


def design():
    conf={'id':'test','strategies':['opening_range_continuation','failed_breakout_reversal'],'holdout_after_calendar_days':60,'min_outcomes':100,'min_calendar_span_days':90,'min_entry_weeks':12,'min_holdout_outcomes':30}
    s=json.dumps(conf)
    return {'registered_at':'2026-11-16T12:00:00Z','forward_start':'2026-11-17T14:30:00Z','holdout_start':'2027-01-16T14:30:00Z','config_json':s,'config_sha256':sha(s.encode())}


def test_minimum_evidence_and_holdout_are_required_not_automatic_success(tmp_path):
    d=design();r=prospective_scorecard(d,[],[],[],now='2026-11-17T15:00:00Z',lock_path=tmp_path/'eval.json')
    assert all(s['verdict']=='continue collecting' for s in r['strategies'])
    assert all(s['holdout_returns']=='EMBARGOED' for s in r['strategies'])
    assert not (tmp_path/'eval.json').exists()
    d['holdout_start']='2026-11-16T11:00:00Z'
    with pytest.raises(ValueError,match='Retroactive'):prospective_scorecard(d,[],[],[],now='2026-11-17T15:00:00Z')


def test_overlapping_or_synthetic_outcomes_cannot_inflate_count():
    d=design();a={'id':'a','selected':1,'strategy':'opening_range_continuation','evidence_mode':'prospective','config_sha256':d['config_sha256'],'design_id':'test','decision_at':'2026-11-17T15:00:00Z','exit_at':'2026-11-17T15:30:00Z'}
    b={**a,'id':'b','decision_at':'2026-11-17T15:15:00Z'}
    entries=[{'decision_id':x,'state':'QUOTE_MODEL'} for x in ('a','b')]
    with pytest.raises(ValueError,match='Overlapping'):prospective_scorecard(d,[a,b],entries,[],now='2026-11-18T00:00:00Z')
    with pytest.raises(ValueError,match='Nonprospective'):prospective_scorecard(d,[{**a,'evidence_mode':'synthetic'}],[],[],now='2026-11-18T00:00:00Z')


def test_python_independently_recomputes_javascript_sqlite_receipts(tmp_path):
    artifact=tmp_path/'synthetic-ledger.json'
    run=subprocess.run(['node','--test','tests/paper_research_v1.test.mjs'],cwd=Path(__file__).resolve().parents[1],env={**os.environ,'PAPER_TEST_EXPORT':str(artifact)},capture_output=True,text=True,timeout=30,check=False)
    assert run.returncode==0,run.stdout+run.stderr
    ledger=json.loads(artifact.read_text())
    result=prospective_scorecard(**ledger,now='2026-11-17T18:00:00Z')
    assert result['strategies'][0]['complete']==1
    assert result['strategies'][0]['development_mean_net']==19.4
    ledger['outcomes'][0]['target_net']+=1
    with pytest.raises(ValueError,match='Net arithmetic'):prospective_scorecard(**ledger,now='2026-11-17T18:00:00Z')


def test_independent_evaluation_accounts_for_missing_exits_and_locks_without_waiting_for_other_strategy(tmp_path):
    # Expand an actual SQLite-produced synthetic receipt across distinct business days.
    # These are fixtures, never prospective production evidence.
    from copy import deepcopy
    artifact=tmp_path/'fixture.json'
    subprocess.run(['node','--test','tests/paper_research_v1.test.mjs'],cwd=Path(__file__).resolve().parents[1],env={**os.environ,'PAPER_TEST_EXPORT':str(artifact)},capture_output=True,text=True,check=True)
    base=json.loads(artifact.read_text());original=next(d for d in base['decisions'] if d['selected'])
    conf=json.loads(base['design']['config_json']);ledger={**base,'decisions':[],'entries':[],'outcomes':[],'marks':[]}
    start=datetime(2026,11,17,15,5,10,tzinfo=timezone.utc);day=start
    for i in range(121):
        while day.weekday()>4:day+=timedelta(days=1)
        delta=day-start;d=deepcopy(original);d['id']=str(i)
        for k in ('decision_at','exit_at'):d[k]=(datetime.fromisoformat(d[k].replace('Z','+00:00'))+delta).isoformat()
        contracts=json.loads(d['contracts_json']);mapping={}
        for c in contracts:
            old=c['symbol'];expiry=datetime.fromisoformat(c['expiry'])+delta
            c['expiry']=expiry.date().isoformat();c['symbol']=c['root']+expiry.strftime('%y%m%d')+c['right']+f"{round(c['strike']*1000):08d}";mapping[old]=c
        d['contracts_json']=json.dumps(contracts);ledger['decisions'].append(d)
        e=deepcopy(base['entries'][0]);o=deepcopy(base['outcomes'][0]);m=deepcopy(next(m for m in base['marks'] if m['received_at']==o['received_at']))
        for r in (e,m):
            r['decision_id']=str(i);r['received_at']=(datetime.fromisoformat(r['received_at'].replace('Z','+00:00'))+delta).isoformat()
            quotes=json.loads(r['quotes_json'])
            for q in quotes:
                q.update(mapping[q['symbol']])
                for k in ('captured_at','bid_at','ask_at'):q[k]=(datetime.fromisoformat(q[k].replace('Z','+00:00'))+delta).isoformat()
            r['quotes_json']=json.dumps(quotes);r['quote_sha256']=sha(r['quotes_json'].encode())
        o['decision_id']=str(i);o['received_at']=m['received_at']
        if i==120:
            o.update(state='MISSING_EXIT',target_net=None,control_net=None,excess_net=None,stress_net=None)
        else:ledger['marks'].append(m)
        ledger['entries'].append(e);ledger['outcomes'].append(o);day+=timedelta(days=1)
    now=day.isoformat();lock=tmp_path/'evaluation.json'
    embargoed=prospective_scorecard(**ledger,now=now)
    assert embargoed['strategies'][0]['minima_pass']
    assert embargoed['strategies'][0]['holdout_returns']=='EMBARGOED'
    result=prospective_scorecard(**ledger,now=now,lock_path=lock)
    first,second=result['strategies']
    assert first['evaluation']=='FIRST_LOCKED_STRATEGY_EVALUATION'
    assert first['missing_exit_sensitivity_count']==1
    assert first['verdict']=='reject'  # Matched control performs identically; no excess edge.
    assert first['holdout_returns']['excess_net']['lower']<0
    assert second['holdout_returns']=='EMBARGOED' and not second['minima_pass']
    files=list(tmp_path.glob('evaluation-*.json'));assert len(files)==1
    saved=files[0].read_bytes()
    assert prospective_scorecard(**ledger,now=(day+timedelta(days=3)).isoformat(),lock_path=lock)['strategies'][0]==first
    assert files[0].read_bytes()==saved
    # A missing exit must retain a valid hashed entry; no invented maximum-loss basis.
    ledger['entries'][-1]['target_risk']=0
    with pytest.raises(ValueError,match='Entry arithmetic'):prospective_scorecard(**ledger,now=now,lock_path=lock)


def test_time_limit_rejects_an_unproductive_protocol_without_peeking_at_holdout():
    d=design();config=json.loads(d['config_json']);config.update(max_collection_calendar_days=180,min_completion_rate=.95,evaluation_policy='independent_strategy_locked_evaluation_no_holdout_tuning')
    d['config_json']=json.dumps(config);d['config_sha256']=sha(d['config_json'].encode())
    report=prospective_scorecard(d,[],[],[],now='2027-05-17T20:05:00Z')
    assert all(r['verdict']=='reject' and r['operating_state']=='PAUSED_TIME_LIMIT' and r['holdout_returns']=='EMBARGOED' for r in report['strategies'])
