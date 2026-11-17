/* Private prospective quote research. No broker/account/order routes or public data API.
 * This is a separate, explicitly frozen PRICE-ONLY study, not the older catalyst/IV H1.
 * One global active position prevents overlapping paper exposure. All four contracts
 * are retained until the fixed exit; no strike or affordability reselection at exit.
 */
export const DESIGN = Object.freeze({
  id:'price-action-v2-20261117', roots:['SPY','QQQ'],
  strategies:['opening_range_continuation','failed_breakout_reversal'],
  decision_minutes_et:[605,635,665,785,845], holding_minutes:30,
  range_minutes:30, min_range_bps:5, breakout_buffer_bps:2,
  continuation_points:3, failed_breakout_lookback:10,
  dte_min:5,dte_max:14,width:1,control_strike_offset:2,
  max_risk_usd:100,fee_per_contract_side_usd:0.65,
  adverse_round_trip_usd:4,stress_extra_usd:10,
  min_open_interest:100,max_relative_spread:0.10,
  max_side_age_ms:60000,max_side_skew_ms:45000,max_exit_delay_ms:60000,
  max_reads_day:25000,max_writes_day:6000,max_provider_requests_day:250,
  min_outcomes:100,min_calendar_span_days:90,min_entry_weeks:12,
  holdout_after_calendar_days:60,min_holdout_outcomes:30,
  max_collection_calendar_days:180,min_completion_rate:0.95,
  missing_exit_policy:'target_max_loss_control_max_gain_in_holdout_sensitivity',
  evaluation_policy:'independent_strategy_locked_evaluation_no_holdout_tuning',
  benchmark:'same-root-expiry-side-width-two-strikes-further-OTM-risk-scaled',
  price_field:'one-minute-underlying-midquote-not-trade-OHLC',
  greeks_used:false, evidence_mode:'prospective', execution:'quote_model_only'
});
export const EXTRA_COST=4*DESIGN.fee_per_contract_side_usd+DESIGN.adverse_round_trip_usd;
const ET=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
export const stamp=ms=>new Date(ms).toISOString();
export function etParts(ms){const p=Object.fromEntries(ET.formatToParts(new Date(ms)).map(x=>[x.type,x.value]));return {day:`${p.year}-${p.month}-${p.day}`,minute:Number(p.hour)*60+Number(p.minute)};}
export async function digest(text){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))].map(x=>x.toString(16).padStart(2,'0')).join('');}
const money=x=>Math.round((x+Number.EPSILON)*100)/100;
const finitePositive=x=>typeof x==='number'&&Number.isFinite(x)&&x>0;
const qualifiedTime=x=>typeof x==='number'||(typeof x==='string'&&(/^\d+$/.test(x)||/(Z|[+-]\d\d:\d\d)$/.test(x)));
export function qualifiedGreekTime(raw,receivedMs){
  if(typeof raw!=='string'||!/(Z|[+-]\d\d:\d\d)$/.test(raw))return {state:'UNKNOWN_TIMEZONE',at:null};
  const t=Date.parse(raw);return Number.isFinite(t)&&t<=receivedMs&&receivedMs-t<=70*60000?{state:'HOURLY_PROVIDER_VALUE',at:stamp(t)}:{state:'STALE_OR_FUTURE',at:null};
}
export function signalAt(rows,decisionMs){
  const {day,minute}=etParts(decisionMs),valid=[];
  for(const r of rows){
    const t=Date.parse(r.observed_minute),c=Date.parse(r.captured_at),b=Date.parse(r.bid_quote_at),a=Date.parse(r.ask_quote_at);
    if(!r.source?.startsWith('tradier_')||/synthetic/i.test(r.source)||!finitePositive(r.bid)||r.ask<r.bid||!finitePositive(r.ask)||
      ![t,c,b,a].every(Number.isFinite)||c>decisionMs||c<t||c-t>=60000||c<b||c<a||c-b>60000||c-a>60000||Math.abs(a-b)>45000||
      etParts(t).day!==day||t>=decisionMs)continue;
    valid.push({t,minute:etParts(t).minute,mid:(r.bid+r.ask)/2});
  }
  valid.sort((a,b)=>a.t-b.t);
  const opening=valid.filter(x=>x.minute>=570&&x.minute<600),latest=valid.filter(x=>x.minute>=minute-10&&x.minute<minute);
  const unique=new Set(valid.map(x=>x.t));
  if(unique.size!==valid.length||opening.length!==30||latest.length!==10||latest.at(-1).minute!==minute-1||latest.some((x,i)=>i&&x.t-latest[i-1].t!==60000))
    return {ready:false,reason:'MISSING_UNDERLYING_HISTORY',signals:{}};
  const high=Math.max(...opening.map(x=>x.mid)),low=Math.min(...opening.map(x=>x.mid)),last=latest.at(-1).mid;
  const widthBps=(high-low)/opening[0].mid*10000,buffer=opening[0].mid*DESIGN.breakout_buffer_bps/10000;
  if(widthBps<DESIGN.min_range_bps)return {ready:false,reason:'RANGE_TOO_SMALL',signals:{}};
  const tail=latest.slice(-3),prior=latest.slice(0,-1);
  const continuation=tail.every(x=>x.mid>high+buffer)?'C':tail.every(x=>x.mid<low-buffer)?'P':null;
  const failedUp=prior.some(x=>x.mid>high+buffer)&&last<high-buffer&&last>low;
  const failedDown=prior.some(x=>x.mid<low-buffer)&&last>low+buffer&&last<high;
  return {ready:true,reason:'PRICE_HISTORY_VALID',spot:last,range_high:high,range_low:low,range_bps:widthBps,
    regime:last>high?'above_opening_range':last<low?'below_opening_range':'inside_opening_range',
    signals:{opening_range_continuation:continuation,failed_breakout_reversal:failedUp&&!failedDown?'P':failedDown&&!failedUp?'C':null}};
}
export function frozenContracts(root,side,spot,catalog,day){
  const list=(Array.isArray(catalog)?catalog:[catalog]).filter(Boolean).map(x=>({...x,dte:(Date.parse(x.date+'T12:00:00Z')-Date.parse(day+'T12:00:00Z'))/86400000}));
  const candidates=list.filter(x=>x.dte>=5&&x.dte<=14&&(x.contract_size==null||x.contract_size===100)).sort((a,b)=>a.dte-b.dte);
  for(const item of candidates){
    const available=new Set((Array.isArray(item.strikes?.strike)?item.strikes.strike:[item.strikes?.strike]).map(Number));
    const center=Math.round(spot),direction=side==='C'?1:-1;
    const strikes=[center,center+direction,center+direction*2,center+direction*3];
    if(!strikes.every(k=>k>0&&available.has(k)))continue;
    return strikes.map((strike,i)=>({symbol:root+item.date.slice(2).replaceAll('-','')+side+String(Math.round(strike*1000)).padStart(8,'0'),root,expiry:item.date,right:side,strike,role:i<2?'target':'control',leg:i%2?'sell':'buy'}));
  }return [];
}
export function validatePaperBatch(batch,contracts,validateQuote,{entry=false}={}){
  const quotes=[],missing=[],seen=new Set();
  for(const c of contracts){
    const raw=batch.quotes.filter(q=>q.symbol===c.symbol);
    let q=raw.length===1?validateQuote(raw[0],batch.receivedAtMs):null;
    const x=raw[0];
    if(q&&(!qualifiedTime(x.bid_date)||!qualifiedTime(x.ask_date)||Date.parse(q.bidAt)>batch.receivedAtMs||Date.parse(q.askAt)>batch.receivedAtMs||c.expiry<etParts(batch.receivedAtMs).day||x.contract_size!==100||x.expiration_date!==c.expiry||
      Number(x.strike)!==c.strike||x.option_type!==(c.right==='C'?'call':'put')||
      (x.root_symbol&&x.root_symbol!==c.root)||(x.underlying&&x.underlying!==c.root)))q=null;
    if(q&&entry&&(!Number.isInteger(x.open_interest)||x.open_interest<DESIGN.min_open_interest||(q.ask-q.bid)/((q.ask+q.bid)/2)>DESIGN.max_relative_spread))q=null;
    if(!q||seen.has(c.symbol)){missing.push(c.symbol);continue;}
    seen.add(c.symbol);quotes.push({...c,bid:q.bid,ask:q.ask,bid_size:q.bidSize,ask_size:q.askSize,bid_at:q.bidAt,ask_at:q.askAt,
      captured_at:stamp(batch.receivedAtMs),source:'tradier_prod_rest_fixed_contract_paper_v1',open_interest:x.open_interest??null,
      greeks_time:qualifiedGreekTime(x.greeks?.updated_at,batch.receivedAtMs)});
  }
  const times=quotes.flatMap(x=>[Date.parse(x.bid_at),Date.parse(x.ask_at)]);
  if(times.length&&Math.max(...times)-Math.min(...times)>45000)return {quotes:[],missing:contracts.map(x=>x.symbol),reason:'CROSS_LEG_CLOCK_SKEW'};
  return {quotes,missing,reason:missing.length?'MISSING_OR_INVALID_LEGS':'ALL_FOUR_QUOTE_MARKS'};
}
export function pairValues(quotes){
  const result={};for(const role of ['target','control']){const buy=quotes.find(q=>q.role===role&&q.leg==='buy'),sell=quotes.find(q=>q.role===role&&q.leg==='sell');
    if(!buy||!sell)throw Error('incomplete_pair');result[role]={debit:money((buy.ask-sell.bid)*100),credit:money((buy.bid-sell.ask)*100)};}return result;
}
class Meter {
  constructor(db){this.db=db;this.reads=0;this.writes=0;this.requests=0;}
  request(){if(this.blockProvider||this.requests>=this.requestLimit)throw Error('paper_provider_budget');this.requests++;}
  async sql(sql,args=[]){const r=await this.db.prepare(sql).bind(...args).all();if(!r.success||!Number.isInteger(r.meta?.rows_read)||!Number.isInteger(r.meta?.rows_written))throw Error('paper_unmetered_database');
    this.reads+=r.meta.rows_read;this.writes+=r.meta.rows_written;if(r.meta.rows_read>25000||this.reads>12000)throw Error('paper_query_budget');return r;}
  async rows(sql,args=[]){return (await this.sql(sql,args)).results;}
  async batch(statements){
    const results=await this.db.batch(statements.map(([sql,args])=>this.db.prepare(sql).bind(...args)));
    for(const r of results){if(!r.success||!Number.isInteger(r.meta?.rows_read)||!Number.isInteger(r.meta?.rows_written))throw Error('paper_unmetered_database');this.reads+=r.meta.rows_read;this.writes+=r.meta.rows_written;}
    if(this.reads>12000)throw Error('paper_query_budget');return results;
  }
}
async function outcome(m,d,state,now,reason,values={}){
  await m.sql('INSERT OR IGNORE INTO paper_outcomes_v1 VALUES (?,?,?,?,?,?,?,?,?)',[d.id,state,stamp(now),values.target??null,values.control??null,values.excess??null,values.stress??null,reason,'prospective']);
  await m.sql('DELETE FROM paper_open_v1 WHERE decision_id=?',[d.id]);
}
async function track(m,d,deps,env,clock){
  const now=clock(),deadline=Date.parse(d.exit_at),contracts=JSON.parse(d.contracts_json);
  const entries=await m.rows('SELECT * FROM paper_entries_v1 WHERE decision_id=?',[d.id]);
  const entry=entries[0];
  if(!entry&&now-Date.parse(d.decision_at)>120000){await outcome(m,d,'NO_FILL',now,'ENTRY_CAPTURE_INTERRUPTED');return;}
  if(now>deadline+DESIGN.max_exit_delay_ms){await outcome(m,d,'MISSING_EXIT',now,'PLANNED_EXIT_WINDOW_MISSED');return;}
  if(entry?.state==='NO_FILL'){await outcome(m,d,'NO_FILL',now,entry.reason);return;}
  if(now%60000>=45000){
    await m.sql('INSERT OR IGNORE INTO paper_marks_v1 VALUES (?,?,?,?,?,?,?)',[d.id,stamp(Math.floor(now/60000)*60000),stamp(now),'CAPTURE_DEADLINE','[]',JSON.stringify(contracts.map(c=>c.symbol)),await digest('[]')]);
    return; // durable missing observation; never fabricate an exit
  }
  let batch;
  try{m.request();batch=await deps.getQuotes(env.TRADIER_TOKEN,contracts.map(x=>x.symbol),deps.fetcher,clock);}
  catch(e){const reason=deps.classify(e instanceof Error?e.message:'');
    if(['authorization_denied','provider_rate_limited'].includes(reason)){m.blockProvider=true;await deps.cooldown(reason);}
    batch={quotes:[],receivedAtMs:clock(),failure:reason};}
  const received=batch.receivedAtMs;
  if(received<Date.parse(d.decision_at)||!deps.isSession(new Date(received)))return;
  const checked=validatePaperBatch(batch,contracts,deps.validateQuote,{entry:!entry});
  const payload=JSON.stringify(checked.quotes),hash=await digest(payload),minute=stamp(Math.floor(received/60000)*60000);
  if(!entry){
    let reason=batch.failure??checked.reason,values=null;
    if(checked.missing.length===0){values=pairValues(checked.quotes);
      if(['target','control'].some(r=>values[r].debit<=0||values[r].debit+EXTRA_COST>100||values[r].debit>=100)){reason='RISK_OR_DEBIT_REJECTED';values=null;}}
    if(received-Date.parse(d.decision_at)>120000){reason='ENTRY_CAPTURE_TOO_LATE';values=null;}
    const state=values?'QUOTE_MODEL':'NO_FILL';
    await m.sql('INSERT OR IGNORE INTO paper_entries_v1 VALUES (?,?,?,?,?,?,?,?,?,?)',[d.id,state,stamp(received),payload,hash,values?.target.debit??null,values?.control.debit??null,values?money(values.target.debit+EXTRA_COST):null,values?money(values.control.debit+EXTRA_COST):null,reason]);
    if(!values)await outcome(m,d,'NO_FILL',received,reason);
    return;
  }
  await m.sql('INSERT OR IGNORE INTO paper_marks_v1 VALUES (?,?,?,?,?,?,?)',[d.id,minute,stamp(received),checked.missing.length?'MISSING':'QUOTE_MARK',payload,JSON.stringify(checked.missing),hash]);
  if(received>=deadline){
    if(received>deadline+60000||checked.missing.length||checked.quotes.some(q=>Date.parse(q.bid_at)<deadline-60000||Date.parse(q.ask_at)<deadline-60000)){
      await outcome(m,d,'MISSING_EXIT',received,batch.failure??'MISSING_FRESH_FROZEN_EXIT_LEGS');return;}
    const values=pairValues(checked.quotes);
    if(['target','control'].some(r=>values[r].credit<0||values[r].credit>DESIGN.width*100)){
      await outcome(m,d,'MISSING_EXIT',received,'INVALID_VERTICAL_CLOSE_MARK');return;
    }
    const target=money(values.target.credit-entry.target_debit-EXTRA_COST),control=money(values.control.credit-entry.control_debit-EXTRA_COST);
    await outcome(m,d,'COMPLETE_QUOTE_MODEL',received,'NOT_A_BROKER_FILL',{target,control,excess:money(target-control*entry.target_risk/entry.control_risk),stress:money(target-DESIGN.stress_extra_usd)});
  }
}
export function descriptiveScorecard(rows,now){
  return {as_of:stamp(now),evidence:'prospective_quote_models_not_fills',strategies:DESIGN.strategies.map(strategy=>{
    const all=rows.filter(x=>x.strategy===strategy),selected=all.filter(x=>x.selected),filled=selected.filter(x=>x.entry_state==='QUOTE_MODEL'),complete=filled.filter(x=>x.outcome_state==='COMPLETE_QUOTE_MODEL');
    const mean=key=>complete.length?money(complete.reduce((s,x)=>s+x[key],0)/complete.length):null;
    let equity=0,peak=0,drawdown=0;for(const r of complete){equity+=r.target_net;peak=Math.max(peak,equity);drawdown=Math.max(drawdown,peak-equity);}
    return {strategy,considered:all.length,selected:selected.length,rejected:all.length-selected.length,no_fill:selected.filter(x=>x.outcome_state==='NO_FILL').length,
      quote_model_entries:filled.length,complete:complete.length,missing_exit:selected.filter(x=>x.outcome_state==='MISSING_EXIT').length,pending:selected.filter(x=>!x.outcome_state).length,
      completeness:filled.length?complete.length/filled.length:null,mean_net_observed_only:mean('target_net'),mean_control_excess_observed_only:mean('excess_net'),mean_stress_net_observed_only:mean('stress_net'),
      realized_quote_model_drawdown_usd:complete.length?money(drawdown):null,verdict:'CONTINUE_COLLECTING',qualification:'OFFLINE_UNTOUCHED_HOLDOUT_AND_WEEK_CLUSTER_VALIDATION_REQUIRED'};})};
}
// Run on the existing minute trigger after either a normal or early market close.
// These retries use D1 only. No quote or catalog requests are made after hours.
export function maintenanceWindow(now,isSession){
  const {minute}=etParts(now),atMinute=n=>new Date(now+(n-minute)*60000);
  const close=isSession(atMinute(959))?960:isSession(atMinute(779))?780:null;
  return close!==null&&minute>=close&&minute<=close+30&&minute%5===0;
}
const week=t=>{const d=new Date(etParts(Date.parse(t)).day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()-(d.getUTCDay()+6)%7);return d.toISOString().slice(0,10);};
export function evidenceProgress(rows,design,now){
  const filled=rows.filter(r=>r.entry_state==='QUOTE_MODEL'),complete=filled.filter(r=>r.outcome_state==='COMPLETE_QUOTE_MODEL');
  const times=complete.map(r=>Date.parse(r.decision_at)),span=times.length?Math.floor((Math.max(...times)-Math.min(...times))/86400000):0;
  const weeks=new Set(complete.map(r=>week(r.decision_at))).size,held=complete.filter(r=>r.decision_at>=design.holdout_start).length;
  const pending=rows.filter(r=>!r.outcome_state).length,completion=filled.length?complete.length/filled.length:null;
  const ready=complete.length>=DESIGN.min_outcomes&&span>=DESIGN.min_calendar_span_days&&weeks>=DESIGN.min_entry_weeks&&held>=DESIGN.min_holdout_outcomes&&completion>=DESIGN.min_completion_rate&&pending===0;
  const expired=now>=Date.parse(design.forward_start)+DESIGN.max_collection_calendar_days*86400000;
  return {selected:rows.length,quote_model_entries:filled.length,complete:complete.length,
    no_fills:rows.filter(r=>r.outcome_state==='NO_FILL').length,missing_exits:rows.filter(r=>r.outcome_state==='MISSING_EXIT').length,
    pending,completion_rate:completion,calendar_span_days:span,entry_weeks:weeks,untouched_holdout_complete:held,
    minima_pass:ready,state:ready?'PAUSED_READY_FOR_LOCKED_REVIEW':expired?'PAUSED_TIME_LIMIT':'COLLECTING'};
}
async function registeredDesign(m,now){
  const d=(await m.rows('SELECT * FROM paper_designs_v1 WHERE id=?',[DESIGN.id]))[0],config=JSON.stringify(DESIGN),hash=await digest(config);
  return d&&d.config_json===config&&d.config_sha256===hash&&[d.registered_at,d.forward_start,d.holdout_start].every(t=>Number.isFinite(Date.parse(t))&&/(Z|[+-]\d\d:\d\d)$/.test(t))&&Date.parse(d.registered_at)<Date.parse(d.forward_start)&&Date.parse(d.holdout_start)-Date.parse(d.forward_start)===DESIGN.holdout_after_calendar_days*86400000&&now>=Date.parse(d.forward_start)?d:null;
}
async function recordUsage(env,m,utcday){
  await env.DB.prepare('INSERT INTO paper_budget_v1 VALUES (?,?,?,?) ON CONFLICT(day) DO UPDATE SET rows_read=rows_read+excluded.rows_read,rows_written=rows_written+excluded.rows_written,provider_requests=provider_requests+excluded.provider_requests').bind(utcday,m.reads+4,m.writes+6,m.requests).run();
}
export async function runPaperMaintenance(env,deps,clock=Date.now){
  const now=clock();if(env.PAPER_RESEARCH_ENABLED!=='true'||!maintenanceWindow(now,deps.isSession))return 'paper_maintenance_not_due';
  const m=new Meter(env.DB),et=etParts(now),day=stamp(now).slice(0,10);
  // Unique daily key is the durable retry guard; a lost final market minute cannot lose the report.
  if((await m.rows('SELECT day FROM paper_scorecards_v1 WHERE day=?',[et.day])).length)return 'paper_report_already_saved';
  const design=await registeredDesign(m,now);if(!design)return 'paper_design_not_registered';
  const budget=(await m.rows('SELECT * FROM paper_budget_v1 WHERE day=?',[day]))[0]??{rows_read:0,rows_written:0,provider_requests:0};
  if(budget.rows_read+12000>DESIGN.max_reads_day||budget.rows_written+30>DESIGN.max_writes_day)return 'paper_report_budget';
  try{
    const open=await m.rows('SELECT d.* FROM paper_open_v1 o JOIN paper_decisions_v1 d ON d.id=o.decision_id WHERE o.slot=1 LIMIT 1');
    if(open[0]&&Date.parse(open[0].exit_at)+60000<now){
      const entry=(await m.rows('SELECT state FROM paper_entries_v1 WHERE decision_id=?',[open[0].id]))[0];
      await outcome(m,open[0],entry?.state==='QUOTE_MODEL'?'MISSING_EXIT':'NO_FILL',now,'RECOVERED_AFTER_SESSION_NO_EXIT_INVENTED');
    }
    const rows=await m.rows('SELECT d.strategy,d.selected,d.decision_at,d.exit_at,e.state entry_state,e.reason entry_reason,o.state outcome_state,o.target_net,o.excess_net,o.stress_net FROM paper_decisions_v1 d LEFT JOIN paper_entries_v1 e ON e.decision_id=d.id LEFT JOIN paper_outcomes_v1 o ON o.decision_id=d.id WHERE d.design_id=? AND d.selected=1 ORDER BY d.decision_at LIMIT 1801',[DESIGN.id]);
    if(rows.length>1800)throw Error('paper_selected_report_bound');
    const today=await m.rows('SELECT strategy,selected,reason FROM paper_decisions_v1 WHERE design_id=? AND decision_at>=? AND decision_at<? ORDER BY decision_at LIMIT 21',[DESIGN.id,stamp(now-et.minute*60000-now%60000),stamp(now+(1440-et.minute)*60000-now%60000)]);
    if(today.length>20)throw Error('paper_candidate_report_bound');
    const development=rows.filter(r=>r.decision_at<design.holdout_start),descriptive=descriptiveScorecard(development,now);
    const states=await m.rows('SELECT strategy,state FROM paper_strategy_state_v2 WHERE design_id=?',[DESIGN.id]);
    const prior=new Map(states.map(x=>[x.strategy,x.state]));
    const available=DESIGN.decision_minutes_et.filter(minute=>deps.isSession(new Date(now+(minute-et.minute+DESIGN.holding_minutes)*60000))).length*DESIGN.roots.length;
    const strategies=DESIGN.strategies.map(strategy=>{
      const life=evidenceProgress(rows.filter(r=>r.strategy===strategy),design,now),ds=today.filter(r=>r.strategy===strategy),reasons={};
      for(const r of ds)if(!r.selected)reasons[r.reason]=(reasons[r.reason]??0)+1;
      const todaysSelected=rows.filter(r=>r.strategy===strategy&&etParts(Date.parse(r.decision_at)).day===et.day);
      const missingToday=todaysSelected.filter(r=>r.outcome_state==='MISSING_EXIT').length,noFills=todaysSelected.filter(r=>r.outcome_state==='NO_FILL');
      for(const r of noFills){const key='ENTRY_'+(r.entry_reason??'INTERRUPTED');reasons[key]=(reasons[key]??0)+1;}
      const expected=prior.has(strategy)||now>=Date.parse(design.forward_start)+DESIGN.max_collection_calendar_days*86400000?0:available,missing=Math.max(0,expected-ds.length);
      const action=life.state==='PAUSED_READY_FOR_LOCKED_REVIEW'?'RUN_ONE_LOCKED_PRIVATE_HOLDOUT_REVIEW':life.state==='PAUSED_TIME_LIMIT'?'REVIEW_OR_RETIRE_PROTOCOL_BEFORE_ANY_RESTART':missing||missingToday||reasons.MISSING_UNDERLYING_HISTORY?'REPAIR_COLLECTION':noFills.length&&!todaysSelected.some(r=>r.outcome_state==='COMPLETE_QUOTE_MODEL')?'REVIEW_ENTRY_LIQUIDITY_AND_COST_LIMITS':life.selected===0?'REVIEW_SIGNAL_AND_REJECTION_COUNTS':'CONTINUE_COLLECTING';
      return {strategy,lifetime:life,today:{considered:ds.length,expected_candidates:expected,missing_candidates:missing,missing_exits:missingToday,no_fills:noFills.length,rejected:ds.filter(r=>!r.selected).length,reasons},
        development:descriptive.strategies.find(r=>r.strategy===strategy),holdout_returns:'EMBARGOED',next_action:action,verdict:life.state==='PAUSED_TIME_LIMIT'?'reject':life.state==='PAUSED_READY_FOR_LOCKED_REVIEW'?'pending locked review':'continue collecting',verdict_basis:life.state==='PAUSED_TIME_LIMIT'?'INSUFFICIENT_EVIDENCE_WITHIN_FROZEN_WINDOW_NOT_A_PROFITABILITY_FINDING':'MINIMUM_COUNTS_DO_NOT_PROVE_PROFITABILITY'};
    });
    const usage={rows_read:budget.rows_read+m.reads,rows_written:budget.rows_written+m.writes,provider_requests:budget.provider_requests+m.requests};
    const completeToday=rows.filter(r=>etParts(Date.parse(r.decision_at)).day===et.day&&r.outcome_state==='COMPLETE_QUOTE_MODEL').length;
    const payload=JSON.stringify({as_of:stamp(now),design_id:DESIGN.id,design_sha256:design.config_sha256,forward_start:design.forward_start,holdout_start:design.holdout_start,
      collection_deadline:stamp(Date.parse(design.forward_start)+DESIGN.max_collection_calendar_days*86400000),strategies,
      performance_scope:'development_only_holdout_embargoed',resource_scope:'paper_research_only_excludes_other_collectors',resource_usage_today:usage,
      complete_outcomes_today:completeToday,complete_outcomes_per_1000_reads:usage.rows_read?completeToday*1000/usage.rows_read:null,
      complete_outcomes_per_provider_request:usage.provider_requests?completeToday/usage.provider_requests:null,
      full_selected_history:true,selected_limit:1800});
    // Report and stop states commit together; repeats are idempotent and cannot reopen a paused study.
    const statements=strategies.filter(s=>s.lifetime.state!=='COLLECTING').map(s=>['INSERT OR IGNORE INTO paper_strategy_state_v2 VALUES (?,?,?,?)',[DESIGN.id,s.strategy,s.lifetime.state,stamp(now)]]);
    statements.push(['INSERT OR IGNORE INTO paper_scorecards_v1 VALUES (?,?,?,?)',[et.day,stamp(now),payload,await digest(payload)]]);
    await m.batch(statements);return 'paper_report_saved';
  }finally{await recordUsage(env,m,day);}
}
export async function runPaperResearch(env,deps,clock=Date.now){
  if(env.PAPER_RESEARCH_ENABLED!=='true'||!deps.isSession(new Date(clock())))return 'paper_disabled_or_closed';
  const start=clock(),minute=stamp(Math.floor(start/60000)*60000),utcday=minute.slice(0,10),et=etParts(start),m=new Meter(env.DB);
  let claimed=false,state='paper_failed';
  try{
    const design=await registeredDesign(m,start);if(!design)return 'paper_design_not_registered';
    const hash=design.config_sha256;
    const budget=(await m.rows('SELECT * FROM paper_budget_v1 WHERE day=?',[utcday]))[0]??{rows_read:0,rows_written:0,provider_requests:0};
    if(budget.rows_read+1200>DESIGN.max_reads_day||budget.rows_written+80>DESIGN.max_writes_day||budget.provider_requests+6>DESIGN.max_provider_requests_day)return 'paper_daily_budget';
    m.requestLimit=DESIGN.max_provider_requests_day-budget.provider_requests;
    const claim=await m.sql('INSERT OR IGNORE INTO paper_runs_v1(observed_minute,started_at,state) VALUES (?,?,?)',[minute,stamp(start),'RUNNING']);
    if(!claim.meta.changes)return 'paper_duplicate_minute';claimed=true;
    const open=await m.rows('SELECT d.* FROM paper_open_v1 o JOIN paper_decisions_v1 d ON d.id=o.decision_id WHERE o.slot=1 LIMIT 1');
    if(open[0])await track(m,open[0],deps,env,clock);
    if(DESIGN.decision_minutes_et.includes(et.minute)&&deps.allowNew&&clock()%60000<40000&&start<Date.parse(design.forward_start)+DESIGN.max_collection_calendar_days*86400000){
      const stopped=new Set((await m.rows('SELECT strategy FROM paper_strategy_state_v2 WHERE design_id=?',[DESIGN.id])).map(x=>x.strategy));
      for(const root of DESIGN.roots){
        const opening=start-(et.minute-570)*60000;
        const history=await m.rows('SELECT observed_minute,bid,ask,bid_quote_at,ask_quote_at,captured_at,source FROM quote_samples_v17 WHERE symbol=? AND observed_minute>=? AND observed_minute<? ORDER BY observed_minute LIMIT 390',[root,stamp(Math.floor(opening/60000)*60000),minute]);
        const signal=signalAt(history,start),context=JSON.stringify(signal),exitAt=stamp(Math.floor(start/60000)*60000+DESIGN.holding_minutes*60000);
        for(const strategy of DESIGN.strategies){
          if(stopped.has(strategy))continue;
          const id=DESIGN.id+':'+minute+':'+root+':'+strategy,side=signal.signals[strategy];
          if((await m.rows('SELECT id FROM paper_decisions_v1 WHERE id=?',[id])).length)continue;
          let reason=!signal.ready?signal.reason:!side?'NO_SIGNAL':'TRACK_REQUESTED',contracts=[];
          if(reason==='TRACK_REQUESTED'&&(await m.rows('SELECT decision_id FROM paper_open_v1 WHERE slot=1')).length)reason='OVERLAPPING_EXPOSURE_REJECTED';
          if(reason==='TRACK_REQUESTED'){
            try{m.request();const catalog=await deps.getCatalog(env.TRADIER_TOKEN,root,deps.fetcher,clock);contracts=frozenContracts(root,side,signal.spot,catalog,et.day);if(contracts.length!==4)reason='NO_ADJACENT_STANDARD_CONTRACTS';}
            catch(e){reason='CATALOG_UNAVAILABLE';const code=deps.classify(e instanceof Error?e.message:'');if(['authorization_denied','provider_rate_limited'].includes(code)){m.blockProvider=true;await deps.cooldown(code);}}
          }
          if(!deps.isSession(new Date(exitAt)))reason='EXIT_OUTSIDE_SESSION';
          if(clock()%60000>=45000||clock()-start>30000)reason='DECISION_CAPTURE_DEADLINE';
          const selected=reason==='TRACK_REQUESTED'?1:0,decisionAt=stamp(clock());
          const decisionSql='INSERT OR IGNORE INTO paper_decisions_v1 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)';
          const decisionArgs=[id,DESIGN.id,strategy,root,decisionAt,exitAt,selected,reason,JSON.stringify(contracts),context,hash,'prospective'];
          if(selected){
            // D1 batch is transactional: a crash cannot leave a selected intent without its tracking queue.
            try{await m.batch([[decisionSql,decisionArgs],['INSERT INTO paper_open_v1 VALUES (1,?,?)',[id,exitAt]]]);}
            catch(e){if(!(await m.rows('SELECT decision_id FROM paper_open_v1 WHERE slot=1')).length)throw e;
              decisionArgs[6]=0;decisionArgs[7]='CONCURRENT_EXPOSURE_REJECTED';await m.sql(decisionSql,decisionArgs);continue;}
            const d={id,decision_at:decisionAt,exit_at:exitAt,contracts_json:JSON.stringify(contracts)};
            await track(m,d,deps,env,clock);
          }else await m.sql(decisionSql,decisionArgs);
        }
      }
    }
    state='paper_complete';return state;
  }catch(e){const allowed=new Set(['paper_unmetered_database','paper_query_budget','paper_provider_budget']);state=allowed.has(e.message)?e.message:'paper_database_or_provider_failure';throw Error(state);}
  finally{if(claimed){await env.DB.prepare('UPDATE paper_runs_v1 SET completed_at=?,state=?,rows_read=?,rows_written=?,provider_requests=? WHERE observed_minute=?').bind(stamp(clock()),state,m.reads,m.writes,m.requests,minute).run();
    await recordUsage(env,m,utcday);}}
}
