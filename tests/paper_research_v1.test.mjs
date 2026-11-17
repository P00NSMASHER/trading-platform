import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,writeFileSync} from 'node:fs';
import {DESIGN,EXTRA_COST,digest,signalAt,frozenContracts,validatePaperBatch,qualifiedGreekTime,runPaperResearch} from '../workers/paper_research_v1.mjs';
import {validateQuote,isRegularSession,classifyCollectorFailureV25} from '../workers/tradier_poller_v24_candidate.mjs';

// All prices and observations in this file are synthetic, isolated in SQLite memory.
class D1 {
  constructor(db=new DatabaseSync(':memory:')){this.db=db;this.crashAfterReservation=false;}
  prepare(sql){const self=this;return {bind(...args){return {sql,args,async all(){return self.execute(sql,args);},async run(){return self.execute(sql,args);}};}};}
  execute(sql,args){const st=this.db.prepare(sql);const results=st.all(...args),changes=/^(INSERT|UPDATE|DELETE)/.test(sql)?this.db.prepare('SELECT changes() n').get().n:0;return {success:true,results,meta:{changes,rows_read:Math.max(results.length,1),rows_written:changes}};}
  async batch(statements){this.db.exec('BEGIN');try{const r=statements.map(s=>this.execute(s.sql,s.args));this.db.exec('COMMIT');if(this.crashAfterReservation){this.crashAfterReservation=false;throw Error('synthetic_crash_after_commit');}return r;}catch(e){if(this.db.isTransaction)this.db.exec('ROLLBACK');throw e;}}
}
const START=Date.parse('2026-11-17T15:05:10Z');
const catalog=[{date:'2026-11-23',contract_size:100,strikes:{strike:Array.from({length:30},(_,i)=>490+i)}}];
function raw(c,t,bid=3,ask=3.02){return {symbol:c.symbol,underlying:c.root,root_symbol:c.root,expiration_date:c.expiry,option_type:c.right==='C'?'call':'put',strike:c.strike,contract_size:100,bid,ask,bidsize:10,asksize:10,bid_date:t-1000,ask_date:t-2000,open_interest:200};}
async function setup(){const d1=new D1();d1.db.exec(readFileSync(new URL('../workers/migrations/0001_paper_research.sql',import.meta.url),'utf8'));
  d1.db.exec('CREATE TABLE quote_samples_v17 (observed_minute TEXT,symbol TEXT,bid REAL,ask REAL,bid_quote_at TEXT,ask_quote_at TEXT,captured_at TEXT,source TEXT,PRIMARY KEY(symbol,observed_minute));');
  const config=JSON.stringify(DESIGN);d1.db.prepare('INSERT INTO paper_designs_v1 VALUES (?,?,?,?,?,?)').run(DESIGN.id,'2026-11-17T13:00:00Z','2026-11-17T14:30:00Z','2027-01-16T14:30:00Z',config,await digest(config));
  for(const root of DESIGN.roots)for(let i=0;i<35;i++){const t=Date.parse('2026-11-17T14:30:00Z')+i*60000,mid=i<30?500+(i%2):502;d1.db.prepare('INSERT INTO quote_samples_v17 VALUES (?,?,?,?,?,?,?,?)').run(new Date(t).toISOString(),root,mid-.01,mid+.01,new Date(t+1000).toISOString(),new Date(t+2000).toISOString(),new Date(t+3000).toISOString(),'tradier_synthetic_test');}
  // Deliberately make provenance realistic only inside this synthetic test DB. Never exported to production.
  d1.db.exec("UPDATE quote_samples_v17 SET source='tradier_prod_rest_bidask_snapshot_v18_not_executable'");
  let now=START;const requests=[];const env={DB:d1,TRADIER_TOKEN:'synthetic_token',PAPER_RESEARCH_ENABLED:'true'};
  const deps={isSession:isRegularSession,validateQuote,allowNew:true,classify:classifyCollectorFailureV25,cooldown:async()=>{},getCatalog:async()=>catalog,getQuotes:async(_token,ids)=>{
    requests.push([...ids]);const cs=frozenContracts('SPY','C',502,catalog,'2026-11-17');return {receivedAtMs:now,quotes:cs.filter(c=>ids.includes(c.symbol)).map(c=>raw(c,now,c.leg==='buy'?3:2.8,c.leg==='buy'?3.02:2.82))};}};
  return {d1,env,deps,requests,clock:()=>now,setNow:t=>now=t};}
function rows(s,table){return s.d1.db.prepare('SELECT * FROM '+table).all();}

test('SQL selection, freeze, restart, duplicate and exact contract exit with high premiums',async()=>{
 const s=await setup();assert.equal(await runPaperResearch(s.env,s.deps,s.clock),'paper_complete');
 assert.equal(rows(s,'paper_decisions_v1').length,4);assert.equal(rows(s,'paper_open_v1').length,1);assert.equal(rows(s,'paper_entries_v1')[0].state,'QUOTE_MODEL');
 const d=rows(s,'paper_decisions_v1').find(d=>d.selected),frozen=JSON.parse(d.contracts_json);assert.equal(frozen.length,4);assert.equal(new Set(frozen.map(x=>x.symbol)).size,4);
 assert.equal(rows(s,'paper_decisions_v1').find(d=>d.root==='QQQ'&&d.strategy==='opening_range_continuation').reason,'OVERLAPPING_EXPOSURE_REJECTED');
 assert.equal(await runPaperResearch(s.env,s.deps,s.clock),'paper_duplicate_minute');assert.equal(s.requests.length,1);
 s.env.DB=new D1(s.d1.db);s.setNow(START+60000);await runPaperResearch(s.env,s.deps,s.clock);assert.deepEqual(s.requests[1],s.requests[0]);
 s.setNow(Date.parse(d.exit_at)+5000);s.deps.allowNew=false;
 s.deps.getQuotes=async(_token,ids)=>{assert.deepEqual(ids,frozen.map(x=>x.symbol));return {receivedAtMs:s.clock(),quotes:frozen.map(c=>raw(c,s.clock(),c.leg==='buy'?25.5:25,c.leg==='buy'?25.52:25.02))};};
 await runPaperResearch(s.env,s.deps,s.clock);const o=rows(s,'paper_outcomes_v1')[0];assert.equal(o.state,'COMPLETE_QUOTE_MODEL');assert.equal(o.target_net,19.4);assert.equal(o.stress_net,9.4);assert.equal(rows(s,'paper_open_v1').length,0);
 await runPaperResearch(s.env,s.deps,s.clock);assert.equal(rows(s,'paper_outcomes_v1').length,1);
 assert.throws(()=>s.d1.db.prepare('UPDATE paper_decisions_v1 SET exit_at=?').run('2027-01-01'),/immutable/);
 assert.throws(()=>s.d1.db.exec('DELETE FROM paper_outcomes_v1'),/immutable/);
 if(process.env.PAPER_TEST_EXPORT)writeFileSync(process.env.PAPER_TEST_EXPORT,JSON.stringify({design:rows(s,'paper_designs_v1')[0],decisions:rows(s,'paper_decisions_v1'),entries:rows(s,'paper_entries_v1'),marks:rows(s,'paper_marks_v1'),outcomes:rows(s,'paper_outcomes_v1')}),{mode:0o600});
});
test('missing exits and partial entry become explicit outcomes, never substituted',async()=>{
 const s=await setup();await runPaperResearch(s.env,s.deps,s.clock);const d=rows(s,'paper_decisions_v1').find(x=>x.selected);s.setNow(Date.parse(d.exit_at)+10000);s.deps.allowNew=false;s.deps.getQuotes=async()=>({quotes:[],receivedAtMs:s.clock()});
 await runPaperResearch(s.env,s.deps,s.clock);assert.equal(rows(s,'paper_outcomes_v1')[0].state,'MISSING_EXIT');assert.equal(JSON.parse(rows(s,'paper_marks_v1')[0].missing_json).length,4);
 const z=await setup();z.deps.getQuotes=async()=>({quotes:[],receivedAtMs:z.clock()});await runPaperResearch(z.env,z.deps,z.clock);assert(rows(z,'paper_outcomes_v1').every(x=>x.state==='NO_FILL'));assert.equal(rows(z,'paper_open_v1').length,0);
});
test('restart after durable reservation recovers entry without rewriting intent',async()=>{
 const s=await setup();s.d1.crashAfterReservation=true;await runPaperResearch(s.env,s.deps,s.clock);assert.equal(rows(s,'paper_open_v1').length,1);
 s.setNow(START+60000);s.deps.allowNew=false;await runPaperResearch(s.env,s.deps,s.clock);assert.equal(rows(s,'paper_entries_v1').length,1);assert.equal(rows(s,'paper_entries_v1')[0].state,'QUOTE_MODEL');
});
test('outage past exit and past entry window fails closed and drains queue',async()=>{
 const s=await setup();await runPaperResearch(s.env,s.deps,s.clock);s.deps.allowNew=false;s.setNow(START+32*60000);await runPaperResearch(s.env,s.deps,s.clock);assert.equal(rows(s,'paper_outcomes_v1')[0].reason,'PLANNED_EXIT_WINDOW_MISSED');
 const z=await setup();z.d1.crashAfterReservation=true;await runPaperResearch(z.env,z.deps,z.clock);z.deps.allowNew=false;z.setNow(START+3*60000);await runPaperResearch(z.env,z.deps,z.clock);assert.equal(rows(z,'paper_outcomes_v1')[0].reason,'ENTRY_CAPTURE_INTERRUPTED');
});
test('side clocks, identity, expiration, duplicate and skew validation',()=>{
 const cs=frozenContracts('SPY','C',502,catalog,'2026-11-17'),qs=cs.map(c=>raw(c,START));const batch=()=>({quotes:structuredClone(qs),receivedAtMs:START});
 assert.equal(validatePaperBatch(batch(),cs,validateQuote,{entry:true}).missing.length,0);
 for(const mutate of [q=>q.symbol='QQQ000000C00000000',q=>q.strike++,q=>q.expiration_date='2026-11-24',q=>q.bid_date=START+1000,q=>q.ask_date=START-61000,q=>q.bid_date='2026-11-17 15:05:09',q=>q.contract_size=10,q=>q.open_interest=0]){const b=batch();mutate(b.quotes[0]);assert(validatePaperBatch(b,cs,validateQuote,{entry:true}).missing.length>0);}
 const b=batch();b.quotes.push(b.quotes[0]);assert(validatePaperBatch(b,cs,validateQuote).missing.length>0);
 assert.equal(validatePaperBatch({...batch(),receivedAtMs:Date.parse('2026-11-24T15:05:00Z')},cs,validateQuote).missing.length,4);
 assert.equal(qualifiedGreekTime('2026-11-17 15:00:00',START).state,'UNKNOWN_TIMEZONE');assert.equal(qualifiedGreekTime('2026-11-17T15:00:00Z',START).state,'HOURLY_PROVIDER_VALUE');assert.equal(qualifiedGreekTime('2026-11-17T13:00:00Z',START).state,'STALE_OR_FUTURE');
});
test('rules reject unregistered designs, disabled, closed, unknown calendar and budget',async()=>{
 const s=await setup();s.env.PAPER_RESEARCH_ENABLED='false';assert.equal(await runPaperResearch(s.env,s.deps,s.clock),'paper_disabled_or_closed');s.env.PAPER_RESEARCH_ENABLED='true';
 s.setNow(Date.parse('2026-11-26T15:05:10Z'));assert.equal(await runPaperResearch(s.env,s.deps,s.clock),'paper_disabled_or_closed');assert.equal(isRegularSession(new Date('2026-11-27T18:01:00Z')),false);assert.equal(isRegularSession(new Date('2029-01-03T15:00:00Z')),false);
 s.setNow(START);s.d1.db.prepare('INSERT INTO paper_budget_v1 VALUES (?,?,?,?)').run('2026-11-17',24999,0,0);assert.equal(await runPaperResearch(s.env,s.deps,s.clock),'paper_daily_budget');assert.equal(s.requests.length,0);
 const z=await setup();z.d1.db.exec('DROP TRIGGER paper_designs_no_update');z.d1.db.exec("UPDATE paper_designs_v1 SET holdout_start='invalid'");assert.equal(await runPaperResearch(z.env,z.deps,z.clock),'paper_design_not_registered');
});
test('source history excludes future information, synthetic provenance, missing minutes',async()=>{
 const s=await setup(),r=rows(s,'quote_samples_v17').filter(x=>x.symbol==='SPY');const good=signalAt(r,START);assert.equal(good.signals.opening_range_continuation,'C');
 assert.deepEqual(signalAt([...r,{...r[0],observed_minute:new Date(START+60000).toISOString(),captured_at:new Date(START+62000).toISOString(),bid:900,ask:901}],START),good);
 assert.equal(signalAt(r.slice(1),START).ready,false);assert.equal(signalAt(r.map(x=>({...x,source:'synthetic_fixture'})),START).ready,false);
 const reversal=r.map((x,i)=>{const p=i===34?500.5:x.bid+.01;return {...x,bid:p-.01,ask:p+.01};});assert.equal(signalAt(reversal,START).signals.failed_breakout_reversal,'P');
});
test('authorization/quota failure makes one request and explicitly no-fills without same-run retry',async()=>{
 const s=await setup();let attempts=0,cooldowns=0;s.deps.getQuotes=async()=>{attempts++;throw Error('tradier_http_429');};s.deps.classify=()=> 'provider_rate_limited';s.deps.cooldown=async()=>{cooldowns++;};await runPaperResearch(s.env,s.deps,s.clock);assert.equal(attempts,1);assert(cooldowns>=1);assert(rows(s,'paper_outcomes_v1').every(x=>x.state==='NO_FILL'));
});
