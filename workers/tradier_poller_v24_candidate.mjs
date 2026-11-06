/* V18: source-qualified Tradier market-data research. No orders, accounts, or trades.
 * Cloudflare secret TRADIER_TOKEN; D1 binding DB. Never publicly expose quotes or tokens.
 * GET only: /v1/markets/quotes and /v1/markets/options/expirations.
 * Free-tier minute CRON, NOT a continuous stream; quote-size fields are raw vendor units,
 * NOT proof of executable depth. Source timestamps are separate for bid and ask.
 */

const API = 'https://api.tradier.com';
const ROOTS = ['SPY', 'QQQ'];
const MAX_SIDE_AGE_MS = 60_000;
const MAX_SIDE_SKEW_MS = 45_000;
const MAX_STOCK_OPTION_SKEW_MS = 45_000;
const MAX_STOCK_OPTION_CAPTURE_MS = 75_000;
const MAX_SYMBOLS = 28;
const SOURCE = 'tradier_prod_rest_bidask_snapshot_v18_not_executable';
const RESEARCH_TAG = 'paper_only_no_execution_assertion';

// Checked against NYSE's official 2026–2028 trading calendar (closed and early closes).
const CLOSED = new Set([
  '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25',
  '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
  '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31',
  '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24',
  '2028-01-17', '2028-02-21', '2028-04-14', '2028-05-29', '2028-06-19',
  '2028-07-04', '2028-09-04', '2028-11-23', '2028-12-25',
]);
const SHORT_DAYS = new Set([
  '2026-11-27', '2026-12-24', '2027-11-26',
  '2028-07-03', '2028-11-24',
]);

function nyParts(date) {
  return Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
    weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).filter(p => p.type !== 'literal').map(p => [p.type, p.value]));
}
export function tradingDate(date) {
  const p = nyParts(date);
  return `${p.year}-${p.month}-${p.day}`;
}
export function isRegularSession(date) {
  const p = nyParts(date);
  if (!['2026', '2027', '2028'].includes(p.year)) return false; // fail closed after calendar horizon
  if (p.weekday === 'Sat' || p.weekday === 'Sun') return false;
  const day = `${p.year}-${p.month}-${p.day}`;
  if (CLOSED.has(day)) return false;
  const minutes = Number(p.hour) * 60 + Number(p.minute);
  return minutes >= 570 && minutes < (SHORT_DAYS.has(day) ? 780 : 960);
}

export function epochMs(n) {
  if (n === null || n === undefined || n === '') return null;
  if (typeof n === 'string' && /[-T:]/.test(n)) {
    const parsed = Date.parse(n);
    return Number.isFinite(parsed) ? parsed : null;
  }
  const v = Number(n);
  if (!Number.isFinite(v) || v <= 0) return null;
  return v < 1e11 ? v * 1000 : v;
}
export function validateQuote(q, receivedAtMs) {
  if (!q || typeof q.symbol !== 'string' || !/^[A-Z][A-Z0-9]{0,31}$/.test(q.symbol)) return null;
  const bid = Number(q.bid), ask = Number(q.ask);
  const bidSize = Number(q.bidsize ?? q.bid_size), askSize = Number(q.asksize ?? q.ask_size);
  if (![bid, ask, bidSize, askSize].every(Number.isFinite) || bid <= 0 || ask <= 0 ||
      bid > ask || !Number.isSafeInteger(bidSize) || !Number.isSafeInteger(askSize) ||
      bidSize < 1 || askSize < 1) return null;
  const bidTs = epochMs(q.bid_date), askTs = epochMs(q.ask_date);
  if (!bidTs || !askTs || bidTs > receivedAtMs + 5000 || askTs > receivedAtMs + 5000 ||
      receivedAtMs - bidTs > MAX_SIDE_AGE_MS || receivedAtMs - askTs > MAX_SIDE_AGE_MS ||
      Math.abs(bidTs - askTs) > MAX_SIDE_SKEW_MS) return null;
  return {
    symbol:q.symbol, bid, ask, bidSize, askSize,
    bidAt:new Date(bidTs).toISOString(), askAt:new Date(askTs).toISOString(),
    providerAt:Math.max(bidTs, askTs),
    bidExch:typeof q.bidexch==='string'?q.bidexch.slice(0,12):null,
    askExch:typeof q.askexch==='string'?q.askexch.slice(0,12):null,
    original:q,
  };
}

export function occ(root, expiration, right, strike) {
  if (!ROOTS.includes(root) || !/^20\d\d-\d\d-\d\d$/.test(expiration) ||
      !['C','P'].includes(right) || !Number.isInteger(strike) || strike < 1 || strike > 9999) return null;
  return root + expiration.slice(2,4) + expiration.slice(5,7) + expiration.slice(8,10) +
    right + Math.round(strike * 1000).toString().padStart(8, '0');
}
export function nearestExpirations(raw, today, limit=2) {
  if (!/^20\d\d-\d\d-\d\d$/.test(today)) return [];
  const dates = Array.isArray(raw)?raw:(typeof raw==='string'?[raw]:[]);
  const dayMs = Date.parse(`${today}T12:00:00Z`);
  return [...new Set(dates.filter(x=>typeof x==='string'&&/^20\d\d-\d\d-\d\d$/.test(x)))]
    .filter(x=>{const t=Date.parse(`${x}T12:00:00Z`);return Number.isFinite(t)&&t>=dayMs&&t-dayMs<=7*86400000;})
    .sort().slice(0,limit);
}
export function candidateContracts(spots, expiries) {
  const planned = new Map();
  for (const root of ROOTS) {
    const spot = spots[root], dates=expiries[root]||[];
    if (!Number.isFinite(spot)||spot<=0) continue;
    const center = Math.round(spot);
    for (const expiry of dates.slice(0,2)) {
      for (const strike of [center-1,center,center+1]) {
        for (const right of ['C','P']) {
          const sym=occ(root,expiry,right,strike);
          if (sym) planned.set(sym,{root,expiry,strike,right});
        }
      }
    }
  }
  return planned;
}
export function contractMetadataMatches(v, c) {
  if (!v || !c) return false;
  const q=v.original;
  if (q.type && q.type!=='option') return false;
  if (q.option_type && q.option_type!==(c.right==='C'?'call':'put')) return false;
  if (q.expiration_date && q.expiration_date!==c.expiry) return false;
  if (q.root_symbol && q.root_symbol!==c.root) return false;
  if (q.underlying && q.underlying!==c.root) return false;
  if (q.strike!==undefined && q.strike!==null && Number(q.strike)!==c.strike) return false;
  if (q.contract_size!==undefined && q.contract_size!==null && Number(q.contract_size)!==100) return false;
  return true;
}

async function getJson(token, path, query, fetcher=fetch, clock=Date.now) {
  if (!token) throw new Error('credential_missing');
  if (!['/v1/markets/quotes','/v1/markets/options/expirations','/v1/markets/options/strikes'].includes(path))
    throw new Error('route_not_allowed');
  const url=new URL(path,API);
  for(const [key,value] of Object.entries(query)) url.searchParams.set(key,String(value));
  const res=await fetcher(url.toString(),{
    method:'GET', headers:{Authorization:`Bearer ${token}`,Accept:'application/json'},
    signal:AbortSignal.timeout(10000),
  });
  const receivedAtMs=clock();
  if(res.status===401||res.status===403)throw new Error('authorization_denied');
  if(res.status===429)throw new Error('provider_rate_limited');
  if(res.status===400){
    const raw=String(await res.text()).slice(0,500);
    if(/quota violation|rate.?limit/i.test(raw))throw new Error('provider_rate_limited');
    throw new Error('provider_http_error');
  }
  if(!res.ok)throw new Error('provider_http_error');
  let data;try{data=await res.json();}catch{throw new Error('provider_invalid_json');}
  return {data,receivedAtMs};
}
export async function getQuotes(token, symbols, fetcher=fetch, clock=Date.now) {
  if(!Array.isArray(symbols)||!symbols.length||symbols.length>MAX_SYMBOLS||
     symbols.some(s=>typeof s!=='string'||!/^[A-Z][A-Z0-9]{0,31}$/.test(s)))
    throw new Error('invalid_symbols');
  const r=await getJson(token,'/v1/markets/quotes',{symbols:symbols.join(','),greeks:'false'},fetcher,clock);
  const raw=r.data?.quotes?.quote;
  return {quotes:raw?(Array.isArray(raw)?raw:[raw]):[],receivedAtMs:r.receivedAtMs};
}
export async function getExpirations(token,root,fetcher=fetch,clock=Date.now) {
  if(!ROOTS.includes(root))throw new Error('invalid_symbols');
  const r=await getJson(token,'/v1/markets/options/expirations',
    {symbol:root,includeAllRoots:'false',strikes:'false'},fetcher,clock);
  return r.data?.expirations?.date;
}
async function readStatus(db){
  return db.prepare('SELECT checked_at,state FROM collector_status WHERE id=1').first();
}
async function setStatus(db,state,at){
  await db.prepare('INSERT INTO collector_status(id,checked_at,state) VALUES(1,?,?) ON CONFLICT(id) '
    +'DO UPDATE SET checked_at=excluded.checked_at,state=excluded.state').bind(at.toISOString(),state).run();
}
export function isBackoff(row,when){
  if(!row)return null;
  const last=Date.parse(row.checked_at);
  if(!Number.isFinite(last)||last>when.getTime())return null;
  const duration=row.state==='authorization_denied'?3600_000:
    row.state==='provider_rate_limited'?900_000:0;
  return duration>0 && when.getTime()-last<duration ? 'provider_cooldown' : null;
}
async function expirationsForRoot(env, root, today, fetcher, clock){
  const cached=await env.DB.prepare('SELECT dates_json,loaded_at FROM expiration_cache_v17 WHERE symbol=? AND trading_day=?')
    .bind(root,today).first();
  if(cached){
    try{
      const dates=nearestExpirations(JSON.parse(cached.dates_json),today);
      const cachedAt=Date.parse(cached.loaded_at);
      // Cache validated dates for the day; transient empty responses expire in 15 minutes.
      if(dates.length || (Number.isFinite(cachedAt) && clock()-cachedAt<15*60_000))return dates;
    }catch{}
  }
  const raw=await getExpirations(env.TRADIER_TOKEN,root,fetcher,clock);
  const dates=nearestExpirations(raw,today);
  await env.DB.prepare('INSERT INTO expiration_cache_v17(symbol,trading_day,dates_json,loaded_at) VALUES(?,?,?,?) '
    +'ON CONFLICT(symbol,trading_day) DO UPDATE SET dates_json=excluded.dates_json,loaded_at=excluded.loaded_at')
    .bind(root,today,JSON.stringify(dates),new Date(clock()).toISOString()).run();
  return dates;
}
async function persist(db,quotes,now){
  const captured=now.toISOString(),minute=new Date(Math.floor(now.getTime()/60000)*60000).toISOString();
  if(quotes.length){
    const statements=quotes.map(({q,kind,root,expiry,strike,right})=>db.prepare(
      'INSERT OR IGNORE INTO quote_samples_v17 '
      +'(observed_minute,symbol,kind,underlying,expiration,strike,right,bid,ask,bid_size_raw,ask_size_raw,'
      +'bid_quote_at,ask_quote_at,bid_exch,ask_exch,captured_at,source,data_quality_tag) '
      +'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'
    ).bind(minute,q.symbol,kind,root,expiry,strike,right,q.bid,q.ask,q.bidSize,q.askSize,
      q.bidAt,q.askAt,q.bidExch,q.askExch,captured,SOURCE,RESEARCH_TAG));
    await db.batch(statements);
  }
}
// Durable per-minute coverage is essential to avoid cherry-picking successful market snapshots.
// Never equate vendor quote snapshots or raw bid/ask sizes with guaranteed fills.
export function coverageStatus(stats) {
  if (stats.stocksAccepted < 2) return 'partial_underlying_universe';
  if (stats.optionsPlanned === 0) return 'no_option_candidates_or_expirations';
  if (stats.optionsAligned === 0) return 'no_verified_options';
  if (stats.optionsAligned < stats.optionsPlanned) return 'partial_verified_options';
  return 'complete_verified_option_snapshot';
}
async function recordAttempt(db, fields) {
  const insert = 'INSERT INTO collector_runs_v18 '
    +'(observed_minute,started_at,completed_at,state,underlyings_expected,underlyings_returned,'
    +'underlyings_valid,options_planned,options_returned,options_valid,options_aligned,quotes_accepted,'
    +'coverage_state,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
    +'ON CONFLICT(observed_minute) DO UPDATE SET '
    +'completed_at=excluded.completed_at,state=excluded.state,underlyings_returned=excluded.underlyings_returned,'
    +'underlyings_valid=excluded.underlyings_valid,options_planned=excluded.options_planned,'
    +'options_returned=excluded.options_returned,options_valid=excluded.options_valid,'
    +'options_aligned=excluded.options_aligned,quotes_accepted=excluded.quotes_accepted,'
    +'coverage_state=excluded.coverage_state '
    +'WHERE excluded.options_aligned > collector_runs_v18.options_aligned '
    +'OR (excluded.options_aligned = collector_runs_v18.options_aligned '
    +'AND excluded.quotes_accepted > collector_runs_v18.quotes_accepted)';
  await db.prepare(insert).bind(fields.observedMinute,fields.startedAt,fields.completedAt,fields.state,
    2,fields.stocksReturned,fields.stocksAccepted,fields.optionsPlanned,fields.optionsReturned,
    fields.optionsValid,fields.optionsAligned,fields.quotesAccepted,fields.coverageState,SOURCE).run();
}
export async function collect(env, now=new Date(), fetcher=fetch, clock=Date.now){
  if(!env?.DB)return 'database_binding_missing';
  if(!isRegularSession(now))return 'market_closed';
  const startMs=clock(), observedMinute=new Date(Math.floor(startMs/60000)*60000).toISOString();
  const audit={observedMinute,startedAt:new Date(startMs).toISOString(),completedAt:null,
    state:'pending',stocksReturned:0,stocksAccepted:0,optionsPlanned:0,optionsReturned:0,
    optionsValid:0,optionsAligned:0,quotesAccepted:0,coverageState:'unavailable'};
  let result='collection_failed';
  try{
    if(!env.TRADIER_TOKEN){result='awaiting_tradier_token';}
    else if(isBackoff(await readStatus(env.DB),now)){result='provider_cooldown';}
    else {
      const stockResult=await getQuotes(env.TRADIER_TOKEN,ROOTS,fetcher,clock);
      audit.stocksReturned=stockResult.quotes.length;
      const stock=stockResult.quotes.map(x=>validateQuote(x,stockResult.receivedAtMs))
        .filter(x=>x && ROOTS.includes(x.symbol) && (!x.original.type||['etf','stock'].includes(x.original.type)));
      audit.stocksAccepted=stock.length;
      const stockMap=new Map(stock.map(x=>[x.symbol,x]));
      const spot=Object.fromEntries(stock.map(x=>[x.symbol,(x.bid+x.ask)/2]));
      const day=tradingDate(now), expiries={};
      for(const root of ROOTS){
        if(!spot[root])continue;
        expiries[root]=await expirationsForRoot(env,root,day,fetcher,clock);
      }
      const planned=candidateContracts(spot,expiries);
      audit.optionsPlanned=planned.size;
      let options=[];
      if(planned.size){
        const optionResult=await getQuotes(env.TRADIER_TOKEN,[...planned.keys()],fetcher,clock);
        audit.optionsReturned=optionResult.quotes.length;
        const clean=optionResult.quotes.map(x=>validateQuote(x,optionResult.receivedAtMs))
          .filter(v=>v && contractMetadataMatches(v,planned.get(v.symbol)));
        audit.optionsValid=clean.length;
        options=clean.filter(v=>{
          const c=planned.get(v.symbol), s=stockMap.get(c.root);
          return Boolean(s) && Math.abs(v.providerAt-s.providerAt)<=MAX_STOCK_OPTION_SKEW_MS &&
            Math.abs(optionResult.receivedAtMs-stockResult.receivedAtMs)<=MAX_STOCK_OPTION_CAPTURE_MS;
        });
        audit.optionsAligned=options.length;
      }
      const done=new Date(clock());
      // Match the audit minute to the same completion instant used for quote storage.
      audit.observedMinute=new Date(Math.floor(done.getTime()/60000)*60000).toISOString();
      if(!isRegularSession(done))result='session_ended_during_capture';
      else {
        const rows=[...stock.map(q=>({q,kind:'underlying',root:q.symbol,expiry:null,strike:null,right:null})),
          ...options.map(q=>({...planned.get(q.symbol),q,kind:'option'}))];
        await persist(env.DB,rows,done);
        audit.quotesAccepted=rows.length;
        audit.coverageState=coverageStatus(audit);
        result=options.length?`captured_${stock.length}_stocks_${options.length}_options`:
          stock.length?'underlyings_only_no_verified_options':'no_verified_quotes';
      }
    }
  }catch(error){
    const code=error instanceof Error?error.message:'unknown';
    result=classifyCollectorFailureV25(code);
    // collector_runs_v18 predates error_code. Keep a bounded, non-secret reason in
    // its existing coverage_state so production failures remain diagnosable.
    audit.coverageState='failure_'+result;
  }
  audit.state=result;
  audit.completedAt=new Date(clock()).toISOString();
  if(!audit.quotesAccepted) audit.observedMinute=new Date(Math.floor(Date.parse(audit.completedAt)/60000)*60000).toISOString();
  // Persist the audit even if the provider could not authorize us. No secrets or raw bodies.
  try{
    await recordAttempt(env.DB,audit);
    // The durable rate-limit/auth source state must survive every skipped minute.
    if(result!=='provider_cooldown')await setStatus(env.DB,result,new Date(clock()));
  }catch{return 'research_storage_failed';}
  return result;
}

/* V25: bounded primary-collector failure reasons. Never persist raw provider,
 * credential, network, or database error text. */
export function classifyCollectorFailureV25(msg) {
  const allowed=new Set(['authorization_denied','provider_rate_limited','provider_http_error',
    'provider_invalid_json','credential_missing','invalid_symbols','route_not_allowed']);
  if(allowed.has(msg))return msg;
  const s=typeof msg==='string'?msg.slice(0,400).toLowerCase():'';
  if(/(daily|quota|limit).*(read|row)|(read|row).*(daily|quota|limit)/.test(s))return 'd1_read_quota';
  if(/(daily|quota|limit).*(write)|(write).*(daily|quota|limit)/.test(s))return 'd1_write_quota';
  if(/timeout|timed out|aborterror|deadline/i.test(s))return 'provider_timeout';
  if(/sqlite|database|\.prepare|\.batch|d1\b/.test(s))return 'database_error';
  if(/fetch failed|networkerror|dns|connection refused/.test(s))return 'transport_error';
  return 'collector_unknown_failure';
}
export default {
  async fetch(req){
    const {pathname}=new URL(req.url);
    if(req.method!=='GET'||pathname!=='/health')return new Response('Not found',{status:404});
    return new Response(JSON.stringify({service:'options-tradier-paper-poller',version:'v25',
      data:'research_quote_snapshots_only',orders_enabled:false,licensed_market_data_required:true}),
      {headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  },
  async scheduled(_event,env,ctx){
    // Original 1-minute SPY/QQQ options and 7-21D research remain first.
    ctx.waitUntil((async()=>{
      const outcome=await collectV19(env,new Date());
      if(outcome==='market_closed'||outcome==='provider_cooldown')return;
      const snapshotSink={};
      const broad=await collectBroadV21(env,new Date(),fetch,Date.now,snapshotSink);
      if(broad!=='broad_complete'&&broad!=='broad_partial')
        throw new Error('TRADIER_BROAD_NOT_VERIFIED: '+String(broad).replace(/[^a-z0-9_]/gi,'').slice(0,48));
      const optionOutcome=await collectBroadOptionsV23(env,new Date(),fetch,Date.now,snapshotSink);
      if(!['option_complete','option_partial','option_no_eligible_expiry'].includes(optionOutcome))
        throw new Error('TRADIER_OPTION_TAPE_NOT_VERIFIED: '+String(optionOutcome).replace(/[^a-z0-9_]/gi,'').slice(0,48));
      if(typeof outcome==='string'&&/^captured_2_stocks_[1-9]\d*_options$/.test(outcome))return;
      throw new Error('TRADIER_COLLECTOR_NOT_VERIFIED: '+String(outcome).replace(/[^a-z0-9_]/gi,'').slice(0,48));
    })());
  },
};

/* v19 swing option observations: additive; original collect() stays unchanged.
   Quotes are research only. No orders, accounts or live execution paths. */
const SWING_SOURCE='tradier_prod_rest_bidask_7_21d_v19_not_executable';
const SWING_TAG='long_debit_at_most_1000_paper_only';
const SWING_OFFSETS=[.015,.025,.04];
const SWING_TARGETS=[7,14,21];
function swingDte(today,expiry){
  if(!/^20\d{2}-\d{2}-\d{2}$/.test(today)||!/^20\d{2}-\d{2}-\d{2}$/.test(expiry))return null;
  return Math.round((Date.parse(expiry+'T12:00:00Z')-Date.parse(today+'T12:00:00Z'))/86400000);
}
export function selectSwingCatalog(raw,today){
  const entries=Array.isArray(raw)?raw:(raw?[raw]:[]),available=[];
  for(const x of entries){
    if(!x||typeof x.date!=='string'||(x.contract_size!=null&&Number(x.contract_size)!==100))continue;
    const dte=swingDte(today,x.date),list=x.strikes?.strike;
    if(dte===null||dte<7||dte>21)continue;
    const strikes=[...new Set((Array.isArray(list)?list:(list==null?[]:[list]))
      .map(Number).filter(k=>Number.isInteger(k)&&k>0&&k<9999))].sort((a,b)=>a-b);
    if(strikes.length)available.push({date:x.date,dte,strikes});
  }
  const unique=[...new Map(available.map(x=>[x.date,x])).values()],selection=[];
  for(const t of SWING_TARGETS){
    unique.sort((a,b)=>Math.abs(a.dte-t)-Math.abs(b.dte-t)||a.dte-b.dte);
    if(unique.length)selection.push(unique.shift());
  }
  return selection.sort((a,b)=>a.dte-b.dte);
}
export function swingContracts(spots,catalogs){
  const out=new Map();
  for(const root of ROOTS){
    const spot=spots[root];
    if(!Number.isFinite(spot)||spot<=0)continue;
    for(const c of catalogs[root]||[]){
      for(const right of ['C','P'])for(const pct of SWING_OFFSETS){
        const threshold=spot*(right==='C'?1+pct:1-pct);
        const strike=right==='C'?c.strikes.find(k=>k>=threshold):
          [...c.strikes].reverse().find(k=>k<=threshold);
        if(!Number.isInteger(strike))continue;
        const symbol=occ(root,c.date,right,strike);
        if(symbol)out.set(symbol,{root,expiry:c.date,right,strike});
      }
    }
  }
  return out;
}
async function swingCatalog(env,root,today,fetcher,clock){
  const row=await env.DB.prepare('SELECT catalog_json,loaded_at FROM swing_expiration_cache_v19 WHERE root=? AND trading_day=?')
    .bind(root,today).first();
  if(row){try{
    const catalog=JSON.parse(row.catalog_json);
    if(Array.isArray(catalog)&&catalog.length)return catalog;
    if(clock()-Date.parse(row.loaded_at)<900000)return [];
  }catch{}}
  const response=await getJson(env.TRADIER_TOKEN,'/v1/markets/options/expirations',
    {symbol:root,includeAllRoots:'false',strikes:'true',contractSize:'true'},fetcher,clock);
  const catalog=selectSwingCatalog(response.data?.expirations?.expiration,today);
  await env.DB.prepare('INSERT INTO swing_expiration_cache_v19(root,trading_day,catalog_json,loaded_at) VALUES(?,?,?,?) '
    +'ON CONFLICT(root,trading_day) DO UPDATE SET catalog_json=excluded.catalog_json,loaded_at=excluded.loaded_at')
    .bind(root,today,JSON.stringify(catalog),new Date(clock()).toISOString()).run();
  return catalog;
}
async function swingPersist(env,minute,quotes,clock){
  if(!quotes.length)return;
  const time=new Date(clock()).toISOString();
  const commands=quotes.map(({q,c})=>env.DB.prepare('INSERT OR IGNORE INTO quote_samples_v17 '
    +'(observed_minute,symbol,kind,underlying,expiration,strike,right,bid,ask,bid_size_raw,ask_size_raw,'
    +'bid_quote_at,ask_quote_at,bid_exch,ask_exch,captured_at,source,data_quality_tag) '
    +'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)')
    .bind(minute,q.symbol,'option',c.root,c.expiry,c.strike,c.right,q.bid,q.ask,q.bidSize,q.askSize,
      q.bidAt,q.askAt,q.bidExch,q.askExch,time,SWING_SOURCE,SWING_TAG));
  await env.DB.batch(commands);
}
async function swingAudit(env,s){
  await env.DB.prepare('INSERT INTO swing_runs_v19 '
    +'(observed_minute,started_at,completed_at,state,roots,expirations_selected,options_planned,'
    +'options_returned,options_valid,options_aligned,options_affordable,options_saved,error_code,source) '
    +'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(observed_minute) DO UPDATE SET '
    +'completed_at=excluded.completed_at,state=excluded.state,roots=excluded.roots,'
    +'expirations_selected=excluded.expirations_selected,options_planned=excluded.options_planned,'
    +'options_returned=excluded.options_returned,options_valid=excluded.options_valid,'
    +'options_aligned=excluded.options_aligned,options_affordable=excluded.options_affordable,'
    +'options_saved=excluded.options_saved,error_code=excluded.error_code')
    .bind(s.minute,s.started,s.completed,s.state,s.roots,s.expirations,s.planned,s.returned,
      s.valid,s.aligned,s.affordable,s.saved,s.error,SWING_SOURCE).run();
}
export async function collectV19(env,now=new Date(),fetcher=fetch,clock=Date.now){
  // Unmodified original 0DTE/1DTE collection always runs and writes its own audit first.
  const legacy=await collect(env,now,fetcher,clock);
  if(typeof legacy!=='string'||!/^captured_\d+_stocks_\d+_options$/.test(legacy))return legacy;
  const start=new Date(clock()).toISOString();
  const s={minute:new Date(Math.floor(clock()/60000)*60000).toISOString(),
    started:start,completed:start,state:'pending',roots:0,expirations:0,planned:0,
    returned:0,valid:0,aligned:0,affordable:0,saved:0,error:null};
  try{
    const receipt=await env.DB.prepare('SELECT observed_minute,completed_at,state FROM collector_runs_v18 WHERE observed_minute>=? AND observed_minute<=? ORDER BY observed_minute DESC LIMIT 1')
      .bind(new Date(Date.parse(s.minute)-60000).toISOString(),s.minute).first();
    if(!receipt||receipt.state!==legacy||clock()-Date.parse(receipt.completed_at)>60000)
      throw new Error('legacy_receipt_missing');
    s.minute=receipt.observed_minute;
    const prior=await env.DB.prepare('SELECT state,completed_at FROM swing_runs_v19 ORDER BY observed_minute DESC LIMIT 1').first();
    const age=prior?clock()-Date.parse(prior.completed_at):Infinity;
    if(prior&&age>=0&&((prior.state==='provider_rate_limited'&&age<900000)||
      (prior.state==='authorization_denied'&&age<3600000))){s.state='swing_cooldown';}
    else{
      const stocks=await env.DB.prepare("SELECT underlying,bid,ask,bid_quote_at,ask_quote_at,captured_at FROM quote_samples_v17 WHERE observed_minute=? AND kind='underlying'")
        .bind(s.minute).all();
      if((stocks.results||[]).length!==2)throw new Error('legacy_stock_quotes_missing');
      const stockMap=new Map(stocks.results.map(x=>[x.underlying,x]));
      const spot=Object.fromEntries(stocks.results.map(x=>[x.underlying,(x.bid+x.ask)/2]));
      const day=tradingDate(now),cats={};
      for(const root of ROOTS){
        cats[root]=await swingCatalog(env,root,day,fetcher,clock);
        s.expirations+=cats[root].length;
      }
      s.roots=ROOTS.length;
      const planned=swingContracts(spot,cats);s.planned=planned.size;
      if(!planned.size)s.state='no_swing_contracts';
      else{
        const all=[...planned.keys()],accepted=[];
        for(let offset=0;offset<all.length;offset+=18){
          const snapshot=await getQuotes(env.TRADIER_TOKEN,all.slice(offset,offset+18),fetcher,clock);
          s.returned+=snapshot.quotes.length;
          for(const original of snapshot.quotes){
            const meta=planned.get(original.symbol);if(!meta)continue;
            const q=validateQuote(original,snapshot.receivedAtMs);
            if(!q||!contractMetadataMatches(q,meta))continue;
            s.valid++;
            const st=stockMap.get(meta.root),ts=Math.max(Date.parse(st.bid_quote_at),Date.parse(st.ask_quote_at));
            if(Math.abs(q.providerAt-ts)>MAX_STOCK_OPTION_SKEW_MS ||
              Math.abs(snapshot.receivedAtMs-Date.parse(st.captured_at))>MAX_STOCK_OPTION_CAPTURE_MS)continue;
            s.aligned++;
            if(100*(q.ask+.01)+.65>1000)continue; // one standard long option including slippage and fee
            s.affordable++;
            accepted.push({q,c:meta});
          }
        }
        if(!isRegularSession(new Date(clock())))throw new Error('swing_session_ended');
        await swingPersist(env,s.minute,accepted,clock);s.saved=accepted.length;
        s.state=s.aligned===s.planned?'swing_complete':
          s.saved?'swing_partial_coverage':'no_fresh_affordable_swing_quotes';
      }
    }
  }catch(e){
    const code=e instanceof Error?e.message:'unknown';
    s.error=['authorization_denied','provider_rate_limited','provider_http_error','provider_invalid_json',
      'legacy_receipt_missing','legacy_stock_quotes_missing','swing_session_ended'].includes(code)?code:'swing_collection_failed';
    s.state=s.error;
  }
  s.completed=new Date(clock()).toISOString();
  try{await swingAudit(env,s);}catch{return 'swing_storage_failed';}
  if(s.error)return s.error;
  return legacy;
}


/* V21 additive broad-market monitor. Personal read-only research; no order routes.
 * Keep legacy SPY/QQQ minute and swing collectors unchanged.
 */
const BROAD_SYMBOLS_V21 = ["IWM","TLT","GLD","XLF","XLE","SMH","AAPL","NVDA","AMD","MSFT","BAC","SOFI","F","PFE","XBI","XLI","XLK","XLP","XLU","HYG","GDX","TQQQ","SQQQ","DIA","META","TSLA"];
const BROAD_SOURCE_V21 = 'tradier_prod_rest_broad_level1_v22_paper_only';
function quoteNumberV21(value) {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
function quoteIntV21(value) {
  const n = quoteNumberV21(value);
  return n !== null && Number.isSafeInteger(n) && n >= 0 ? n : null;
}
export async function collectBroadV21(env, now = new Date(), fetcher = fetch, clock = Date.now, snapshotSink = null) {
  if (!env?.DB) return 'broad_database_missing';
  if (!isRegularSession(now)) return 'broad_market_closed';
  const started = new Date(clock()).toISOString();
  const minute = new Date(Math.floor(clock() / 60000) * 60000).toISOString();
  let returned = 0, accepted = 0, code = null, state = 'error';
  try {
    if (!env.TRADIER_TOKEN) throw new Error('credential_missing');
    const result = await getQuotes(env.TRADIER_TOKEN, BROAD_SYMBOLS_V21, fetcher, clock);
    returned = result.quotes.length;
    const chosen = new Map();
    for (const original of result.quotes) {
      const q = validateQuote(original, result.receivedAtMs);
      if (!q || !BROAD_SYMBOLS_V21.includes(q.symbol) ||
          (original.type && !['stock', 'etf'].includes(original.type))) continue;
      chosen.set(q.symbol, q);
    }
    const entries = [...chosen.values()];
    accepted = entries.length;
    if (entries.length > 0) {
      const sql = 'INSERT INTO broad_quotes_v21 (observed_minute,symbol,bid,ask,bid_size_raw,ask_size_raw,bid_at,ask_at,captured_at,last,open,high,low,volume,prevclose,change,change_percentage,trade_at,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(observed_minute,symbol) DO NOTHING';
      const capture = new Date(result.receivedAtMs).toISOString();
      await env.DB.batch(entries.map(q => {
        const raw = q.original;
        const tradeMs = epochMs(raw.trade_date);
        return env.DB.prepare(sql).bind(
          minute, q.symbol, q.bid, q.ask, q.bidSize, q.askSize, q.bidAt, q.askAt, capture,
          quoteNumberV21(raw.last), quoteNumberV21(raw.open), quoteNumberV21(raw.high),
          quoteNumberV21(raw.low), quoteIntV21(raw.volume), quoteNumberV21(raw.prevclose),
          quoteNumberV21(raw.change), quoteNumberV21(raw.change_percentage),
          tradeMs ? new Date(tradeMs).toISOString() : null, BROAD_SOURCE_V21
        );
      }));
    }
    if (snapshotSink && typeof snapshotSink === 'object' && !Array.isArray(snapshotSink)) {
      // Reuse the same validated market-data quotes for the option pass.
      snapshotSink.minute = minute;
      snapshotSink.spots = Object.fromEntries(entries.map(q => [q.symbol, {bid:q.bid,ask:q.ask}]));
    }
    state = accepted === BROAD_SYMBOLS_V21.length ? 'complete' : accepted ? 'partial' : 'empty';
  } catch (error) {
    const key = error instanceof Error ? error.message : '';
    code = ['credential_missing','authorization_denied','provider_rate_limited','provider_http_error','provider_invalid_json'].includes(key) ? key : 'broad_collection_failed';
    state = 'error';
  }
  try {
    await env.DB.prepare('INSERT INTO broad_runs_v21 (observed_minute,started_at,completed_at,state,symbols_requested,symbols_returned,symbols_valid,error_code,source) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(observed_minute) DO UPDATE SET completed_at=excluded.completed_at,state=excluded.state,symbols_returned=excluded.symbols_returned,symbols_valid=excluded.symbols_valid,error_code=excluded.error_code')
      .bind(minute, started, new Date(clock()).toISOString(), state, BROAD_SYMBOLS_V21.length, returned, accepted, code, BROAD_SOURCE_V21).run();
  } catch {
    return 'broad_storage_failed';
  }
  return state === 'error' ? 'broad_' + code : 'broad_' + state;
}


/* v23: rotating near-the-money option snapshots across the 26-symbol broad universe.
 * Uses only read-only Tradier expiration/strikes/quotes GET endpoints. All quotes
 * are non-executable research evidence. Vendor Greeks are not tick-real-time.
 */
const BROAD_OPTION_SOURCE_V23='tradier_prod_rest_broad_options_v23_paper_only';
function occBroadV23(root,expiration,right,strike){
  if(!BROAD_SYMBOLS_V21.includes(root)||!/^20\d{2}-\d\d-\d\d$/.test(expiration)
     ||!['C','P'].includes(right)||!Number.isFinite(strike)||strike<=0||strike>9999)return null;
  const padded=Math.round(strike*1000).toString().padStart(8,'0');
  if(padded.length!==8)return null;
  return root+expiration.slice(2,4)+expiration.slice(5,7)+expiration.slice(8,10)+right+padded;
}
export async function collectBroadOptionsV23(env,now=new Date(),fetcher=fetch,clock=Date.now,snapshot=null){
  if(!env?.DB)return 'option_database_missing';
  if(!isRegularSession(now))return 'option_market_closed';
  // Pin option snapshot to underlying collection minute to avoid minute rollover.
  const ms=snapshot && typeof snapshot.minute==='string' && Number.isFinite(Date.parse(snapshot.minute))
    ? Date.parse(snapshot.minute) : clock();
  const minute=new Date(Math.floor(ms/60000)*60000).toISOString();
  const idx=Math.floor(ms/60000)%BROAD_SYMBOLS_V21.length;
  const root=BROAD_SYMBOLS_V21[idx],started=new Date(ms).toISOString();
  const audit={state:'error',expiry:null,dte:null,requested:0,returned:0,valid:0,saved:0,error:null};
  try{
    if(!env.TRADIER_TOKEN)throw new Error('credential_missing');
    // No redundant D1 SELECT: account-wide free-tier read exhaustion must not
    // break an option scan when this minute's validated spot is in memory.
    const spotRow=snapshot?.minute===minute?snapshot?.spots?.[root]:null;
    if(!spotRow)throw new Error('underlying_spot_missing');
    const spot=(Number(spotRow.bid)+Number(spotRow.ask))/2;
    if(!Number.isFinite(spot)||spot<=0)throw new Error('underlying_spot_invalid');
    const d=tradingDate(now),dayMs=Date.parse(d+'T12:00:00Z');
    const expiryResult=await getJson(env.TRADIER_TOKEN,'/v1/markets/options/expirations',
      {symbol:root,includeAllRoots:'false',strikes:'true'},fetcher,clock);
    const node=expiryResult.data?.expirations||{};
    const rawDates=node.expiration??node.date??[];
    const allDates=Array.isArray(rawDates)?rawDates:[rawDates];
    const dates=allDates.map(x=>{
      const date=typeof x==='string'?x:x?.date;
      const strikes=x&&typeof x==='object'?x.strikes?.strike:null;
      const days=typeof date==='string'&&/^20\d\d-\d\d-\d\d$/.test(date)?
        Math.round((Date.parse(date+'T12:00:00Z')-dayMs)/86400000):NaN;
      return {date,days,strikes};
    }).filter(x=>Number.isInteger(x.days)&&x.days>=0&&x.days<=30);
    if(!dates.length){audit.state='no_eligible_expiry';}
    else{
      const group=Math.floor(Math.floor(ms/60000)/BROAD_SYMBOLS_V21.length)%4;
      const target=[0,1,10,20][group];
      dates.sort((a,b)=>Math.abs(a.days-target)-Math.abs(b.days-target)||a.days-b.days);
      const chosen=dates[0];
      audit.expiry=chosen.date;audit.dte=chosen.days;
      let rawStrikes=chosen.strikes;
      if(rawStrikes==null){
        const strikeResult=await getJson(env.TRADIER_TOKEN,'/v1/markets/options/strikes',
          {symbol:root,expiration:chosen.date},fetcher,clock);
        rawStrikes=strikeResult.data?.strikes?.strike;
      }
      const allStrikes=Array.isArray(rawStrikes)?rawStrikes:(rawStrikes==null?[]:[rawStrikes]);
      const strikes=[...new Set(allStrikes.map(Number).filter(x=>Number.isFinite(x)&&x>0&&x<9999))]
        .sort((a,b)=>Math.abs(a-spot)-Math.abs(b-spot)||a-b).slice(0,12);
      const plan=new Map();
      for(const strike of strikes)for(const right of ['C','P']){
        const symbol=occBroadV23(root,chosen.date,right,strike);
        if(symbol)plan.set(symbol,{strike,right});
      }
      audit.requested=plan.size;
      if(!plan.size){audit.state='no_eligible_strikes';}
      else{
        const response=await getJson(env.TRADIER_TOKEN,'/v1/markets/quotes',
          {symbols:[...plan.keys()].join(','),greeks:'true'},fetcher,clock);
        const items=response.data?.quotes?.quote;
        const rawOptions=Array.isArray(items)?items:(items?[items]:[]);
        audit.returned=rawOptions.length;
        const valid=new Map();
        for(const original of rawOptions){
          const q=validateQuote(original,response.receivedAtMs);
          if(!q||!plan.has(q.symbol))continue;
          const target=plan.get(q.symbol);
          const right=original.option_type==='call'?'C':original.option_type==='put'?'P':null;
          if((original.type&&original.type!=='option')||
            right!==target.right||Number(original.strike)!==target.strike||
            (original.expiration_date&&original.expiration_date!==chosen.date)||
            (original.root_symbol&&original.root_symbol!==root)||
            (original.underlying&&original.underlying!==root)||
            (original.contract_size!=null&&Number(original.contract_size)!==100))continue;
          valid.set(q.symbol,{q,strike:target.strike,right});
        }
        audit.valid=valid.size;
        if(valid.size){
          const sql='INSERT INTO broad_options_v23 (observed_minute,root,symbol,expiration,dte,right,strike,bid,ask,bid_size_raw,ask_size_raw,bid_at,ask_at,captured_at,last,volume,open_interest,delta,gamma,theta,vega,rho,mid_iv,smv_vol,greeks_at,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(observed_minute,symbol) DO NOTHING';
          const captured=new Date(response.receivedAtMs).toISOString();
          await env.DB.batch([...valid.values()].map(({q,strike,right})=>{
            const x=q.original,g=x.greeks&&typeof x.greeks==='object'?x.greeks:{};
            return env.DB.prepare(sql).bind(
              minute,root,q.symbol,chosen.date,chosen.days,right,strike,q.bid,q.ask,
              q.bidSize,q.askSize,q.bidAt,q.askAt,captured,quoteNumberV21(x.last),
              quoteIntV21(x.volume),quoteIntV21(x.open_interest),quoteNumberV21(g.delta),
              quoteNumberV21(g.gamma),quoteNumberV21(g.theta),quoteNumberV21(g.vega),
              quoteNumberV21(g.rho),quoteNumberV21(g.mid_iv),quoteNumberV21(g.smv_vol),
              typeof g.updated_at==='string'?g.updated_at.slice(0,40):null,
              BROAD_OPTION_SOURCE_V23);
          }));
        }
        audit.saved=valid.size;
        audit.state=valid.size===plan.size?'complete':valid.size?'partial':'no_valid_quotes';
      }
    }
  }catch(e){
    const msg=e instanceof Error?e.message:'';
    audit.error=classifyOptionFailureV24(msg);
    audit.state='error';
  }
  try{
    await env.DB.prepare('INSERT INTO broad_option_runs_v23 (observed_minute,started_at,completed_at,state,root,expiration,dte,contracts_requested,contracts_returned,contracts_valid,contracts_saved,error_code,source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(observed_minute) DO UPDATE SET completed_at=excluded.completed_at,state=excluded.state,contracts_returned=excluded.contracts_returned,contracts_valid=excluded.contracts_valid,contracts_saved=excluded.contracts_saved,error_code=excluded.error_code')
      .bind(minute,started,new Date(clock()).toISOString(),audit.state,root,audit.expiry,
        audit.dte,audit.requested,audit.returned,audit.valid,audit.saved,audit.error,
        BROAD_OPTION_SOURCE_V23).run();
  }catch{return 'option_audit_storage_failed';}
  return 'option_'+audit.state+(audit.error?'_'+audit.error:'');
}

/* V24: fail-visible, bounded error classes; never persist raw provider/DB errors. */
export function classifyOptionFailureV24(msg) {
  const allowed=new Set(['credential_missing','authorization_denied','provider_rate_limited',
    'provider_http_error','provider_invalid_json','underlying_spot_missing','underlying_spot_invalid']);
  if(allowed.has(msg))return msg;
  const s=typeof msg==='string'?msg.slice(0,400).toLowerCase():'';
  if(/(daily|quota|limit).*(read|row)|(read|row).*(daily|quota|limit)/.test(s))return 'd1_read_quota';
  if(/(daily|quota|limit).*(write)|(write).*(daily|quota|limit)/.test(s))return 'd1_write_quota';
  if(/timeout|timed out|aborterror|deadline/i.test(s))return 'provider_timeout';
  if(/sqlite|database|\.prepare|\.batch|d1\b/.test(s))return 'database_error';
  if(/fetch failed|networkerror|dns|connection refused/.test(s))return 'transport_error';
  return 'option_unknown_failure';
}
