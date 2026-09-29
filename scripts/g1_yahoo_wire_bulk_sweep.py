from __future__ import annotations

import csv, html, json, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
ANN=ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv"
G3=ROOT/"data/public/metadata/g3_primary_listing_history.csv"
OUT=ROOT/"private_runtime/audit/g1-yahoo-wire-sweep"
UA="Mozilla/5.0 (compatible; G1ResearchSweep/2.0; +https://github.com/P00NSMASHER/trading-platform)"
WIRE_NAMES=("marketwired","marketwire","business wire","pr newswire","globenewswire","global newswire")
BAD_NAMES=("associated press","reuters","zacks","benzinga","motley fool","thestreet","marketbeat","seeking alpha")
FIN_WORDS={"earnings","results","reports","reported","announces","announced","financial","quarter","quarterly","fiscal","revenue","revenues","eps","profit","loss"}

DROP=set("""the and inc corp corporation company co ltd plc holdings holding nyse nasdaq mkt global select market
business wire marketwired marketwire prnewswire pr newswire globenewswire global newswire release news immediate
first second third fourth quarter results reports reported financial fiscal year today january february march april
may june july august september october november december calif california conn connecticut mass massachusetts
pennsylvania colorado texas york illinois rhode island florida virginia washington ohio michigan minnesota new north
south east west announces announced revenue revenues million provides provider leading""".split())

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.href=None; self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=="a":
            self.href=dict(attrs).get("href"); self.text=[]
    def handle_data(self,data):
        if self.href is not None:self.text.append(data)
    def handle_endtag(self,tag):
        if tag.lower()=="a" and self.href is not None:
            self.links.append((self.href,html.unescape(" ".join("".join(self.text).split()))))
            self.href=None; self.text=[]

def rows(p):
    with p.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))
def norm(s):return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9 ]+"," ",(s or "").lower())).strip()
def toks(s):return [x for x in norm(s).split() if len(x)>2 and x not in DROP and not x.isdigit()]

def issuer_tokens(excerpt,symbol):
    t=toks(excerpt)
    # tokens before exchange marker are best company-name signal
    raw=norm(excerpt).split()
    cut=None
    for i,x in enumerate(raw):
        if x in {"nyse","nasdaq"}: cut=i; break
    if cut is not None:
        pre=[x for x in raw[max(0,cut-10):cut] if len(x)>2 and x not in DROP and not x.isdigit()]
        if pre:t=pre
    out=[]
    for x in t[-6:]:
        if x not in out:out.append(x)
    if not out:out=[symbol.lower()]
    return out

def fingerprint(excerpt):
    out=[]
    for x in toks(excerpt):
        if x not in out:out.append(x)
    return out[:18]

def get(url,timeout=18):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.read().decode("utf-8","replace")

def sitemap_url(day,cursor):
    return f"https://finance.yahoo.com/sitemap/{day:%Y_%m_%d}_start{int(cursor.timestamp()*1000)}/"

def parse_next(links,day):
    rx=re.compile(rf"/sitemap/{day:%Y_%m_%d}_start(\d+)/")
    vals=[]
    for u,_ in links:
        m=rx.search(u or "")
        if m:vals.append((int(m.group(1)),u))
    return max(vals,default=(None,None))[1]

def url_clock(url,article_date):
    m=re.search(r"-(\d{6})\d{0,6}(?:--[^/?]+)?\.html(?:\?|$)",url or "")
    if not m:return None
    hh,mm,ss=map(int,(m.group(1)[:2],m.group(1)[2:4],m.group(1)[4:6]))
    if hh>23 or mm>59 or ss>59:return None
    d=article_date
    return datetime(d.year,d.month,d.day,hh,mm,ss,tzinfo=timezone.utc)

def score_title(title,event):
    tt=set(toks(title)); aliases=set(event["aliases"]); fp=set(event["fingerprint"])
    alias_hits=tt&aliases; fp_hits=tt&fp
    fin=bool(tt&FIN_WORDS)
    # issuer/company token + at least two content-fingerprint hits is strong
    score=5*len(alias_hits)+len(fp_hits)+(2 if fin else 0)
    return score,sorted(alias_hits),sorted(fp_hits)

def article_meta(body):
    low=body.lower()
    vals=[]
    patterns=[
      r'<meta[^>]+(?:property|name)=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
      r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']article:published_time["\']',
      r'"datePublished"\s*:\s*"([^"]+)"',
      r'"pubDate"\s*:\s*"([^"]+)"',
    ]
    for pat in patterns:
        vals+=re.findall(pat,body,re.I)
    provider=[]
    for pat in [
      r'"provider_name"\s*:\s*"([^"]+)"',
      r'"publisher"\s*:\s*\{[^{}]{0,500}?"name"\s*:\s*"([^"]+)"',
      r'"author"\s*:\s*\{[^{}]{0,500}?"name"\s*:\s*"([^"]+)"',
      r'<meta[^>]+name=["\']author["\'][^>]+content=["\']([^"\']+)',
    ]:
        provider+=re.findall(pat,body,re.I)
    wire=[]
    for w in WIRE_NAMES:
        if w in low:wire.append(w)
    bad=[]
    for b in BAD_NAMES:
        if b in low:bad.append(b)
    return {"published_values":vals[:10],"providers":provider[:10],"wire_mentions":wire,"bad_mentions":bad}

def scan_day(day_s,events):
    day=datetime.fromisoformat(day_s).replace(tzinfo=timezone.utc)
    earliest=min(e["trade_utc"] for e in events)
    # begin slightly before earliest compromised trade and traverse through next-day 16:00 UTC
    cursor=max(day,earliest-timedelta(minutes=10))
    stop=day+timedelta(days=1,hours=16)
    seen=set(); articles=[]; failures=[]; pages=0
    while cursor<stop and pages<80:
        url=sitemap_url(cursor,cursor)
        if url in seen:break
        seen.add(url);pages+=1
        try:
            body=get(url); p=Parser();p.feed(body)
        except Exception as exc:
            failures.append({"url":url,"error":repr(exc)});break
        page_date=cursor.date()
        for href,title in p.links:
            if "finance.yahoo.com/" not in (href or "") or "/news/" not in href:continue
            ts=url_clock(href,page_date)
            articles.append({"url":href,"title":title,"clock":ts})
        nxt=parse_next(p.links,cursor)
        if not nxt:break
        m=re.search(r"_start(\d+)/",nxt)
        if not m:break
        nxtdt=datetime.fromtimestamp(int(m.group(1))/1000,tz=timezone.utc)
        if nxtdt<=cursor:break
        cursor=nxtdt
        time.sleep(0.03)
    return {"date":day_s,"pages":pages,"articles":articles,"failures":failures}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    ann=[r for r in rows(ANN) if r["resolution_status"]=="excluded_fail_closed"]
    g3={r["event_id"]:r for r in rows(G3)}
    assert len(ann)==125
    events=[];by_date={}
    for r in ann:
        t=datetime.fromisoformat(r["first_documented_illicit_trade_ts"].replace("Z","+00:00"))
        if t.tzinfo is None:t=t.replace(tzinfo=ZoneInfo("America/New_York"))
        t=t.astimezone(timezone.utc)
        gr=g3.get(r["event_id"],{})
        e={**r,"trade_utc":t,"aliases":issuer_tokens(gr.get("evidence_excerpt",""),r["historical_symbol"]),
           "fingerprint":fingerprint(gr.get("evidence_excerpt","")),"g3_excerpt":gr.get("evidence_excerpt",""),
           "g3_source":gr.get("source_reference","")}
        events.append(e);by_date.setdefault(r["event_date"],[]).append(e)

    scans=[]
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs={ex.submit(scan_day,d,g):d for d,g in by_date.items()}
        for fut in as_completed(futs):
            scans.append(fut.result())

    candidates=[]
    for scan in scans:
        group=by_date[scan["date"]]
        for art in scan["articles"]:
            if art["clock"] is None:continue
            for e in group:
                if not (e["trade_utc"]<art["clock"]<=e["trade_utc"]+timedelta(days=7)):continue
                score,ah,fh=score_title(art["title"],e)
                if score<9 or not ah:continue
                candidates.append({**art,"event_id":e["event_id"],"historical_symbol":e["historical_symbol"],
                  "event_date":e["event_date"],"trade_utc":e["trade_utc"].isoformat().replace("+00:00","Z"),
                  "score":score,"alias_hits":ah,"fingerprint_hits":fh,"aliases":e["aliases"],"g3_source":e["g3_source"],
                  "seconds_after_trade":int((art["clock"]-e["trade_utc"]).total_seconds())})

    # Fetch only strong candidate articles to confirm exact page timestamp + wire provider.
    dedup={}
    for c in sorted(candidates,key=lambda x:-x["score"]):
        dedup.setdefault((c["event_id"],c["url"]),c)
    candidates=list(dedup.values())
    def inspect(c):
        out=dict(c);out["clock"]=c["clock"].isoformat().replace("+00:00","Z")
        try:
            body=get(c["url"]); meta=article_meta(body);out["meta"]=meta
            serialized=" ".join(meta["providers"]).lower()+" "+" ".join(meta["wire_mentions"])
            out["wire_provider_confirmed"]=any(w in serialized for w in WIRE_NAMES)
            out["bad_provider_detected"]=bool(meta["bad_mentions"])
            # Confirm page timestamp if parseable; URL clock alone never qualifies.
            parsed=[]
            for v in meta["published_values"]:
                try:
                    p=datetime.fromisoformat(v.replace("Z","+00:00"))
                    if p.tzinfo is None:p=p.replace(tzinfo=timezone.utc)
                    parsed.append(p.astimezone(timezone.utc))
                except Exception:pass
            out["page_timestamps"]=[p.isoformat().replace("+00:00","Z") for p in parsed]
            out["page_clock_matches_url"]=any(abs((p-c["clock"]).total_seconds())<=1 for p in parsed)
            out["high_confidence"]=out["wire_provider_confirmed"] and out["page_clock_matches_url"] and not out["bad_provider_detected"]
        except Exception as exc:
            out["error"]=repr(exc);out["high_confidence"]=False
        return out
    inspected=[]
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs=[ex.submit(inspect,c) for c in candidates]
        for fut in as_completed(futs):inspected.append(fut.result())
    inspected.sort(key=lambda x:(not x.get("high_confidence",False),-x["score"],x["event_date"],x["historical_symbol"]))
    high=[x for x in inspected if x.get("high_confidence")]
    summary={"schema_version":"2","research_use_only":True,"unresolved_events_scanned":len(events),"unique_event_dates":len(by_date),
      "sitemap_pages_scanned":sum(x["pages"] for x in scans),"sitemap_failures":sum(len(x["failures"]) for x in scans),
      "title_candidates":len(candidates),"high_confidence_wire_candidates":len(high),
      "high_confidence_event_count":len({x["event_id"] for x in high}),
      "method":"Full Yahoo sitemap pagination from post-trade through next-day morning; title/excerpt fingerprint scoring; article page timestamp and original-wire provider confirmation. Candidate status only until normal G1 corroboration/promotion."}
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    (OUT/"candidates.json").write_text(json.dumps(inspected,indent=2,default=str)+"\n")
    (OUT/"high_confidence.json").write_text(json.dumps(high,indent=2,default=str)+"\n")
    print(json.dumps(summary,indent=2))
    for x in high:print(json.dumps({k:x.get(k) for k in ["event_id","historical_symbol","event_date","title","url","clock","score","seconds_after_trade"]}))

if __name__=="__main__":main()
