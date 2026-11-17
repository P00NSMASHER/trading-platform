/** Historical underlying diagnostic only. Exact same screen as deployed Worker. */
import {readFileSync,writeFileSync} from 'node:fs';
import {DESIGN,signalAt,etParts,digest} from '../workers/paper_research_v1.mjs';
const input=JSON.parse(readFileSync(process.argv[2],'utf8')),rows=input.rows;
const days=[...new Set(rows.map(r=>etParts(Date.parse(r.observed_minute)).day))].sort();
const cut=days[Math.floor(days.length*.7)],decisions=[];
let busyUntil=0;
for(const day of days){
 const sample=rows.find(r=>etParts(Date.parse(r.observed_minute)).day===day);
 const offset=Number(sample.observed_minute.slice(11,13))-Math.floor(etParts(Date.parse(sample.observed_minute)).minute/60);
 for(const minute of DESIGN.decision_minutes_et){
  const at=Date.parse(day+'T00:00:00Z')+(minute+offset*60)*60000+10000;
  for(const root of DESIGN.roots){
   const history=rows.filter(r=>r.symbol===root&&etParts(Date.parse(r.observed_minute)).day===day),signal=signalAt(history,at);
   for(const strategy of DESIGN.strategies){
    const side=signal.signals[strategy];let state=!signal.ready?signal.reason:!side?'NO_SIGNAL':at<busyUntil?'OVERLAP_REJECTED':'SELECTED';
    const row={day,root,strategy,decision_at:new Date(at).toISOString(),side:side??null,state,split:day<cut?'earlier_retrospective':'later_retrospective',evidence:'HISTORICAL_DIAGNOSTIC_NOT_PROSPECTIVE',regime:signal.regime??null};
    if(state==='SELECTED'){
     busyUntil=Math.floor(at/60000)*60000+30*60000;
     const exit=history.find(r=>Date.parse(r.observed_minute)===busyUntil),captured=exit?Date.parse(exit.captured_at):NaN;
     const valid=exit&&[exit.bid_quote_at,exit.ask_quote_at].every(t=>captured-Date.parse(t)>=0&&captured-Date.parse(t)<=60000)&&captured>=busyUntil&&captured<busyUntil+60000;
     row.exit_state=valid?'OBSERVED_UNDERLYING_ONLY':'MISSING_UNDERLYING_EXIT';
     row.signed_mid_return_bps=valid?((exit.bid+exit.ask)/2/signal.spot-1)*10000*(side==='C'?1:-1):null;
     row.option_outcome='UNAVAILABLE_NO_HISTORIC_FROZEN_FOUR_LEG_SELECTION';
    }
    decisions.push(row);
   }
  }
 }
}
const out={design:DESIGN,design_sha256:await digest(JSON.stringify(DESIGN)),chronological_cut:cut,decisions};
writeFileSync(process.argv[3],JSON.stringify(out),{mode:0o600});
console.log(JSON.stringify({days:days.length,cut,decisions:decisions.length,selected:decisions.filter(x=>x.state==='SELECTED').length}));
