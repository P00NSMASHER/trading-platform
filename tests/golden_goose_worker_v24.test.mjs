import test from 'node:test';
import assert from 'node:assert/strict';
import {collectBroadV21, collectBroadOptionsV23, classifyCollectorFailureV25,
  classifyOptionFailureV24}
  from '../workers/tradier_poller_v24_candidate.mjs';

const NOW='2026-11-05T17:14:00.000Z';
const TIME=Date.parse(NOW);
const ROOTS=['IWM','TLT','GLD','XLF','XLE','SMH','AAPL','NVDA','AMD','MSFT','BAC',
'SOFI','F','PFE','XBI','XLI','XLK','XLP','XLU','HYG','GDX','TQQQ','SQQQ','DIA','META','TSLA'];

function makeEnv() {
  const records=[];
  const DB={
    prepare(sql) {
      if (/^\s*select/i.test(sql)) throw new Error('TEST_FORBIDDEN_D1_SELECT');
      return {
        bind(...args) {return {run:async()=>{records.push({sql,args});return {success:true};}}}
      };
    },
    async batch(statements) {
      return Promise.all(statements.map(x=>x.run()));
    }
  };
  return {env:{DB,TRADIER_TOKEN:'SYNTHETIC_NO_REAL_SECRET'},records};
}
function mockQuote(symbol,bid=100,ask=100.01) {
  return {symbol,bid,ask,bidsize:50,asksize:50,
    bid_date:NOW,ask_date:NOW,type:'etf'};
}
function vendor(url,request) {
  const u=new URL(url);
  assert.equal(request.method,'GET');
  assert.match(request.headers.Authorization,/^Bearer SYNTHETIC/);
  let response;
  if (u.pathname.endsWith('/options/expirations')) {
    response={expirations:{expiration:[{date:'2026-11-06',
      strikes:{strike:[100,101]}}]}};
  } else if (u.pathname.endsWith('/markets/quotes')) {
    const symbols=u.searchParams.get('symbols').split(',');
    const fullChain=u.searchParams.get('greeks')==='true';
    response={quotes:{quote:symbols.map(sym=>{
      if(!fullChain)return mockQuote(sym);
      const match=/^([A-Z]+)(\d{6})([CP])(\d{8})$/.exec(sym);
      assert.ok(match,'must use standard OCC option symbols');
      return {symbol:sym,type:'option',root_symbol:match[1],
        option_type:match[3]==='C'?'call':'put',
        expiration_date:'2026-11-06',strike:Number(match[4])/1000,
        contract_size:100,bid:0.5,ask:0.6,bidsize:20,asksize:20,
        bid_date:NOW,ask_date:NOW,
        greeks:{mid_iv:0.25,delta:0.3,updated_at:NOW},open_interest:250};
    })}};
  } else {
    throw new Error('Unexpected market-data route: '+u.pathname);
  }
  return Promise.resolve({status:200,ok:true,json:async()=>response});
}

test('broad and rotating option collectors reuse validated spot; zero D1 SELECTs',async()=>{
  const {env,records}=makeEnv();
  const sink={};
  const clock=()=>TIME;
  const broad=await collectBroadV21(env,new Date(NOW),vendor,clock,sink);
  assert.equal(broad,'broad_complete');
  assert.equal(sink.minute,NOW);
  assert.equal(Object.keys(sink.spots).length,ROOTS.length);
  for (const root of ROOTS) {
    assert.deepEqual(sink.spots[root],{bid:100,ask:100.01});
  }
  const option=await collectBroadOptionsV23(env,new Date(NOW),vendor,clock,sink);
  assert.equal(option,'option_complete');
  const optionEntries=records.filter(x=>x.sql.includes('INSERT INTO broad_options_v23'));
  const optionAudit=records.filter(x=>x.sql.includes('INSERT INTO broad_option_runs_v23'));
  assert.equal(optionEntries.length,4);
  assert.equal(optionAudit.length,1);
  assert.equal(optionAudit[0].args[3],'complete');
});

test('missing previous spot fails visibly rather than querying unbounded D1',async()=>{
  const {env,records}=makeEnv();
  const result=await collectBroadOptionsV23(env,new Date(NOW),vendor,()=>TIME,{
    minute:NOW,spots:{}
  });
  assert.equal(result,'option_error_underlying_spot_missing');
  assert.equal(records.filter(x=>x.sql.includes('INSERT INTO broad_option_runs_v23')).length,1);
  assert.equal(records.some(x=>/^\s*SELECT/i.test(x.sql)),false);
});

test('quota error classes are sanitized and do not embed provider secrets',()=>{
  assert.equal(classifyCollectorFailureV25("Your account exceeded the D1 daily row read quota"),
    'd1_read_quota');
  assert.equal(classifyCollectorFailureV25('D1 SQL database is unavailable'),'database_error');
  assert.equal(classifyCollectorFailureV25('an arbitrary secret token: REDACT_ME'),
    'collector_unknown_failure');
  assert.equal(classifyOptionFailureV24("Your account has exceeded D1's free tier daily row read limit"),
    'd1_read_quota');
  assert.equal(classifyOptionFailureV24('D1 SQL database is unavailable'),'database_error');
  assert.equal(classifyOptionFailureV24('provider_rate_limited'),'provider_rate_limited');
  assert.equal(classifyOptionFailureV24('an arbitrary secret token: REDACT_ME'),'option_unknown_failure');
});
