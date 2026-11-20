import test from 'node:test';
import assert from 'node:assert/strict';
import {collect} from '../workers/tradier_poller_v24_candidate.mjs';

// Isolated synthetic fixtures. Never contact Tradier, write production D1 or place orders.
class FakeDB {
  constructor(){this.quoteRows=[];this.audits=[];this.statuses=[];}
  prepare(sql){
    const db=this;
    const statement=args=>({
      sql,args,
      async first(){return null;},
      async run(){
        if(sql.startsWith('INSERT INTO collector_runs_v18'))db.audits.push(args);
        if(sql.startsWith('INSERT INTO collector_status'))db.statuses.push(args);
        return {success:true,meta:{rows_read:0,rows_written:1}};
      }
    });
    // Production's readStatus() calls prepare().first() without bind().
    return {bind(...args){return statement(args);},async first(){return null;},
      async run(){return statement([]).run();}};
  }
  async batch(statements){
    for(const statement of statements){
      if(statement.sql.startsWith('INSERT OR IGNORE INTO quote_samples_v17'))
        this.quoteRows.push(statement.args);
    }
    return statements.map(()=>({success:true,meta:{rows_read:0,rows_written:1}}));
  }
}
const MS=s=>Date.parse(s);
function quote(symbol,receivedAtMs){
  return {symbol,type:'etf',bid:symbol==='SPY'?550:500,ask:symbol==='SPY'?550.03:500.03,
    bidsize:25,asksize:25,bid_date:receivedAtMs-1000,ask_date:receivedAtMs-1200};
}
function response(payload){return {ok:true,status:200,headers:{get:()=>null},json:async()=>payload};}
function stocks(receivedAtMs,staleMs=0){return response({quotes:{quote:['SPY','QQQ'].map(s=>{const q=quote(s,receivedAtMs);if(staleMs){q.bid_date=receivedAtMs-staleMs;q.ask_date=receivedAtMs-staleMs;}return q;})}});}
const run=async ({start,stocksAt,expirationResponses,stockAgesMs=[]})=>{
  const db=new FakeDB(),now=new Date(start),env={DB:db,TRADIER_TOKEN:'unit-test-placeholder'};
  let t=MS(start),expirations=0,stockCalls=0;
  const fetcher=async url=>{
    const u=new URL(url);
    if(u.pathname==='/v1/markets/quotes'){
      assert.equal(u.searchParams.get('symbols'),'SPY,QQQ');
      t=MS(stocksAt);return stocks(t,stockAgesMs[stockCalls++]||0);
    }
    assert.equal(u.pathname,'/v1/markets/options/expirations');
    const next=expirationResponses[expirations++];
    t=MS(next.at);
    if(next.http_error)return {ok:false,status:503,headers:{get:()=>null}};
    return response({expirations:{date:[]}});
  };
  const result=await collect(env,now,fetcher,()=>t);
  return {db,result,expirations,stockCalls};
};

test('a later options/expiration provider failure cannot discard valid stock minute history',async()=>{
  const s=await run({start:'2026-11-19T15:03:05.000Z',
    stocksAt:'2026-11-19T15:03:08.000Z',
    expirationResponses:[{at:'2026-11-19T15:03:35.000Z',http_error:true}]});
  assert.equal(s.result,'provider_server_error');
  assert.equal(s.db.quoteRows.length,2);
  assert.deepEqual(s.db.quoteRows.map(x=>x[1]).sort(),['QQQ','SPY']);
  assert(s.db.quoteRows.every(x=>x[0]==='2026-11-19T15:03:00.000Z'));
  assert(s.db.quoteRows.every(x=>x[15]==='2026-11-19T15:03:08.000Z'));
  assert.equal(s.db.audits.length,1);
  assert.equal(s.db.audits[0][0],'2026-11-19T15:03:00.000Z');
  assert.equal(s.db.audits[0][11],2); // persisted quotes, not merely returned quotes
  assert.equal(s.db.statuses.length,1);
});

test('cross-minute expiration latency never relabels old underlying quotes as fresh next-minute data',async()=>{
  const s=await run({start:'2026-11-19T15:03:55.000Z',
    stocksAt:'2026-11-19T15:03:58.000Z',
    expirationResponses:[{at:'2026-11-19T15:04:01.000Z'},{at:'2026-11-19T15:04:03.000Z'}]});
  assert.equal(s.result,'underlyings_only_cross_minute');
  assert.equal(s.db.quoteRows.length,2);
  assert(s.db.quoteRows.every(x=>x[0]==='2026-11-19T15:03:00.000Z'));
  assert(s.db.quoteRows.every(x=>x[15]==='2026-11-19T15:03:58.000Z'));
  assert.equal(s.db.audits[0][0],'2026-11-19T15:03:00.000Z');
  assert.equal(s.db.audits[0][12],'cross_minute_underlying_only');
});

test('same-minute underlying-only attempt remains correctly attributed and never claims options',async()=>{
  const s=await run({start:'2026-11-19T15:03:03.000Z',
    stocksAt:'2026-11-19T15:03:05.000Z',
    expirationResponses:[{at:'2026-11-19T15:03:06.000Z'},{at:'2026-11-19T15:03:07.000Z'}]});
  assert.equal(s.result,'underlyings_only_no_verified_options');
  assert.equal(s.db.quoteRows.length,2);
  assert.equal(s.db.audits[0][8],0); // zero options returned
  assert.equal(s.db.audits[0][11],2); // two genuine underlyings persisted
});

test('collector itself uses a bounded third fresh stock probe before downstream option failure',async()=>{
  const s=await run({start:'2026-11-19T15:03:05.000Z',
    stocksAt:'2026-11-19T15:03:08.000Z',
    stockAgesMs:[180000,180000,0],
    expirationResponses:[{at:'2026-11-19T15:03:35.000Z',http_error:true}]});
  assert.equal(s.stockCalls,3);
  assert.equal(s.result,'provider_server_error');
  assert.equal(s.db.quoteRows.length,2);
  assert(s.db.quoteRows.every(x=>x[0]==='2026-11-19T15:03:00.000Z'));
  assert(s.db.quoteRows.every(x=>x[15]==='2026-11-19T15:03:08.000Z'));
});
