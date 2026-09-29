from __future__ import annotations

import csv
import html
import json
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ANNOUNCEMENTS = ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv"
G3 = ROOT / "data/public/metadata/g3_primary_listing_history.csv"
OUTDIR = ROOT / "private_runtime/audit/g1-yahoo-bulk-sweep"
UA = "Mozilla/5.0 (compatible; G1ResearchSweep/1.0; +https://github.com/P00NSMASHER/trading-platform)"

FINANCIAL_WORDS = {
    "earnings","results","reports","reported","announces","announced","financial",
    "quarter","quarterly","fiscal","revenue","revenues","profit","loss","eps"
}
DROP = {
    "inc","corp","corporation","company","co","ltd","plc","holdings","holding",
    "nyse","nasdaq","mkt","global","select","market","business","wire","marketwired",
    "prnewswire","release","news","immediate","first","second","third","fourth",
    "quarter","results","reports","reported","financial","fiscal","year","today",
    "january","february","march","april","may","june","july","august","september",
    "october","november","december","calif","california","conn","connecticut",
    "mass","massachusetts","pennsylvania","colorado","texas","york","illinois",
    "rhode","island","florida","virginia","washington","ohio","michigan","minnesota",
    "new","north","south","east","west"
}

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links=[]
        self._href=None
        self._text=[]
    def handle_starttag(self, tag, attrs):
        if tag.lower()=="a":
            self._href=dict(attrs).get("href")
            self._text=[]
    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
    def handle_endtag(self, tag):
        if tag.lower()=="a" and self._href is not None:
            text=" ".join("".join(self._text).split())
            self.links.append((self._href, html.unescape(text)))
            self._href=None
            self._text=[]

def norm(s:str)->str:
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9 ]+"," ",(s or "").lower())).strip()

def read_csv(path:Path):
    with path.open(newline="",encoding="utf-8") as h:
        return list(csv.DictReader(h))

def alias_tokens(excerpt:str, symbol:str):
    n=norm(excerpt)
    toks=n.split()
    idx=None
    for i,t in enumerate(toks):
        if t in {"nyse","nasdaq"}:
            idx=i
            break
    if idx is not None:
        pre=toks[max(0,idx-7):idx]
    else:
        pre=toks[:12]
    cleaned=[t for t in pre if t not in DROP and not t.isdigit() and len(t)>2]
    sym=symbol.lower()
    # Prefer tokens nearest the exchange marker; preserve symbol if it is also the issuer word (e.g. qlik).
    cleaned=cleaned[-4:]
    if sym in cleaned and len(cleaned)>1:
        # Keep symbol only when other tokens look generic/noisy.
        useful=[t for t in cleaned if t!=sym]
        if useful:
            cleaned=useful+[sym]
    if not cleaned:
        cleaned=[sym]
    # de-dupe while preserving order
    out=[]
    for t in cleaned:
        if t not in out: out.append(t)
    return out

def parse_utc_from_yahoo_url(url:str, article_date:str):
    # Yahoo legacy article URLs end in HHMMSS + an internal id, e.g. -200500973.html => 20:05:00 UTC.
    m=re.search(r"-(\d{6})\d{0,6}(?:--[^/?]+)?\.html(?:\?|$)",url)
    if not m:
        return None
    hh,mm,ss=map(int,(m.group(1)[:2],m.group(1)[2:4],m.group(1)[4:6]))
    if hh>23 or mm>59 or ss>59:
        return None
    d=datetime.fromisoformat(article_date).date()
    return datetime(d.year,d.month,d.day,hh,mm,ss,tzinfo=timezone.utc)

def fetch(url:str, timeout=20):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return r.read().decode("utf-8","replace")

def sitemap_url(d:datetime, cursor:datetime):
    return f"https://finance.yahoo.com/sitemap/{d:%Y_%m_%d}_start{int(cursor.timestamp()*1000)}/"

def page_windows(day:datetime, earliest_trade_utc:datetime):
    # Hit the dense release windows directly: from the earliest compromised trade,
    # two after-close windows, and two next-morning windows.
    d0=datetime(day.year,day.month,day.day,tzinfo=timezone.utc)
    nextd=d0+timedelta(days=1)
    vals=[
        max(earliest_trade_utc-timedelta(minutes=5),d0),
        d0+timedelta(hours=19,minutes=45),
        d0+timedelta(hours=20,minutes=30),
        d0+timedelta(hours=21),
        nextd+timedelta(hours=11,minutes=30),
        nextd+timedelta(hours=13),
    ]
    # preserve unique cursor times
    out=[]
    for x in vals:
        if x not in out: out.append(x)
    return out

def main():
    OUTDIR.mkdir(parents=True,exist_ok=True)
    ann=[r for r in read_csv(ANNOUNCEMENTS) if r["resolution_status"]=="excluded_fail_closed"]
    g3={r["event_id"]:r for r in read_csv(G3)}
    assert len(ann)==125, len(ann)

    events=[]
    by_date={}
    for r in ann:
        trade=datetime.fromisoformat(r["first_documented_illicit_trade_ts"].replace("Z","+00:00"))
        if trade.tzinfo is None:
            trade=trade.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
        else:
            trade=trade.astimezone(timezone.utc)
        gr=g3.get(r["event_id"],{})
        aliases=alias_tokens(gr.get("evidence_excerpt",""),r["historical_symbol"])
        e={**r,"trade_utc":trade,"aliases":aliases,"g3_excerpt":gr.get("evidence_excerpt",""),"g3_source":gr.get("source_reference","")}
        events.append(e)
        by_date.setdefault(r["event_date"],[]).append(e)

    jobs=[]
    for date_s, group in by_date.items():
        day=datetime.fromisoformat(date_s).replace(tzinfo=timezone.utc)
        earliest=min(e["trade_utc"] for e in group)
        for cursor in page_windows(day,earliest):
            page_day=cursor.date()
            jobs.append((date_s, group, datetime(page_day.year,page_day.month,page_day.day,tzinfo=timezone.utc),cursor))

    pages={}
    def one(job):
        base_date,group,page_day,cursor=job
        url=sitemap_url(page_day,cursor)
        try:
            body=fetch(url)
            p=LinkParser();p.feed(body)
            return (url,p.links,None)
        except Exception as exc:
            return (url,[],repr(exc))

    with ThreadPoolExecutor(max_workers=12) as ex:
        futs=[ex.submit(one,j) for j in jobs]
        for fut in as_completed(futs):
            url,links,err=fut.result()
            pages[url]={"links":links,"error":err}

    candidates=[]
    seen=set()
    for e in events:
        trade=e["trade_utc"]
        event_day=datetime.fromisoformat(e["event_date"]).date()
        for url,info in pages.items():
            # only pages for event day or next day
            m=re.search(r"/sitemap/(\d{4})_(\d{2})_(\d{2})_",url)
            if not m: continue
            page_date=datetime(int(m.group(1)),int(m.group(2)),int(m.group(3)),tzinfo=timezone.utc).date()
            if page_date not in {event_day,event_day+timedelta(days=1)}: continue
            for href,title in info["links"]:
                if "finance.yahoo.com/news/" not in href and "finance.yahoo.com/markets/" not in href:
                    continue
                ntitle=norm(title)
                if not ntitle or not any(w in ntitle.split() for w in FINANCIAL_WORDS):
                    continue
                hits=[t for t in e["aliases"] if t in ntitle.split()]
                required=1 if len(e["aliases"])<=1 else min(2,len(e["aliases"]))
                if len(hits)<required:
                    continue
                ts=parse_utc_from_yahoo_url(href,page_date.isoformat())
                if ts is None or not (trade < ts <= trade+timedelta(days=7)):
                    continue
                key=(e["event_id"],href)
                if key in seen: continue
                seen.add(key)
                candidates.append({
                    "event_id":e["event_id"],
                    "historical_symbol":e["historical_symbol"],
                    "event_date":e["event_date"],
                    "first_trade_utc":trade.isoformat().replace("+00:00","Z"),
                    "aliases":e["aliases"],
                    "alias_hits":hits,
                    "title":title,
                    "url":href,
                    "url_clock_utc":ts.isoformat().replace("+00:00","Z"),
                    "seconds_after_trade":int((ts-trade).total_seconds()),
                    "source_page_date":page_date.isoformat(),
                    "g3_excerpt":e["g3_excerpt"],
                    "g3_source":e["g3_source"],
                    "status":"CANDIDATE_REQUIRES_PAGE_METADATA_CONFIRMATION",
                })

    candidates.sort(key=lambda x:(x["event_date"],x["historical_symbol"],x["url_clock_utc"]))
    summary={
        "schema_version":"1",
        "research_use_only":True,
        "unresolved_events_scanned":len(events),
        "unique_event_dates":len(by_date),
        "sitemap_requests":len(jobs),
        "sitemap_failures":sum(1 for x in pages.values() if x["error"]),
        "candidate_count":len(candidates),
        "candidate_event_count":len({x["event_id"] for x in candidates}),
        "method":"Yahoo historical sitemap time-window sweep. URL clock is triage only; every candidate requires page-metadata confirmation and normal G1 fail-closed validation before promotion.",
    }
    (OUTDIR/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    (OUTDIR/"candidates.json").write_text(json.dumps(candidates,indent=2)+"\n")
    with (OUTDIR/"candidates.csv").open("w",newline="",encoding="utf-8") as h:
        fields=["event_id","historical_symbol","event_date","first_trade_utc","title","url","url_clock_utc","seconds_after_trade","aliases","alias_hits","status"]
        w=csv.DictWriter(h,fieldnames=fields);w.writeheader()
        for row in candidates:
            w.writerow({**{k:row[k] for k in fields if k not in {"aliases","alias_hits"}},"aliases":" ".join(row["aliases"]),"alias_hits":" ".join(row["alias_hits"])})
    print(json.dumps(summary,indent=2))

if __name__=="__main__":
    main()
