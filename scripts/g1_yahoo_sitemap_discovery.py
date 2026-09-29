from __future__ import annotations

import csv
import json
import math
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
RESOLUTIONS = ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv"
LISTING = ROOT / "data/public/metadata/g3_primary_listing_history.csv"
OUT = Path("/tmp/g1-yahoo-sitemap-discovery.json")
UA = "Mozilla/5.0 (compatible; historical-research/1.0; +https://github.com/P00NSMASHER/trading-platform)"
ET = ZoneInfo("America/New_York")

ALLOWED_PROVIDERS = {
    "business wire": "Business Wire",
    "marketwired": "Marketwired",
    "marketwire": "Marketwired",
    "pr newswire": "PR Newswire",
    "prnewswire": "PR Newswire",
    "globenewswire": "GlobeNewswire",
    "globe newswire": "GlobeNewswire",
}
DISALLOWED_PROVIDERS = [
    "associated press", "reuters", "zacks", "thestreet", "motley fool",
    "benzinga", "marketbeat", "seeking alpha", "briefing.com",
]
STOP = {
    "inc","corp","corporation","company","companies","ltd","limited","holdings","holding","group",
    "the","and","for","with","from","this","that","today","reported","reports","report","announced","announces",
    "financial","results","result","quarter","quarterly","year","fiscal","ended","ending","first","second","third","fourth",
    "nyse","nasdaq","nasdaqgs","release","press","news","million","billion","percent","common","share","shares",
    "january","february","march","april","may","june","july","august","september","october","november","december",
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
            self.links.append((" ".join("".join(self._text).split()), self._href))
            self._href=None
            self._text=[]

def get(url: str, retries: int = 3) -> str:
    err=None
    for i in range(retries):
        try:
            req=Request(url,headers={"User-Agent":UA,"Accept-Language":"en-US,en;q=0.9"})
            with urlopen(req,timeout=20) as r:
                return r.read().decode("utf-8","replace")
        except Exception as exc:
            err=exc
            time.sleep(0.4*(i+1))
    raise RuntimeError(f"fetch failed: {url}: {err}")

def norm_tokens(text: str):
    return re.findall(r"[a-z0-9]+", text.lower())

def expected_provider(excerpt: str):
    low=excerpt.lower().replace("-"," ")
    for needle,canon in ALLOWED_PROVIDERS.items():
        if needle in low:
            return canon
    return None

def aliases(symbol: str, excerpt: str):
    toks=norm_tokens(excerpt)
    sym=symbol.lower()
    markers={"nyse","nasdaq","nasdaqgs"}
    chunks=[]
    for i,t in enumerate(toks):
        if t in markers and i+1<len(toks) and toks[i+1]==sym:
            chunks=toks[max(0,i-8):i]
            break
    if not chunks:
        chunks=toks[:14]
    out=[]
    for t in chunks:
        if t not in STOP and len(t)>=4 and not t.isdigit():
            out.append(t)
    if len(sym)>=4:
        out.append(sym)
    # keep order, unique
    return list(dict.fromkeys(out))

def parse_inputs():
    with RESOLUTIONS.open(newline="",encoding="utf-8") as h:
        rr=list(csv.DictReader(h))
    with LISTING.open(newline="",encoding="utf-8") as h:
        lr={r["event_id"]:r for r in csv.DictReader(h)}
    events=[]
    for r in rr:
        if r["resolution_status"]!="excluded_fail_closed" or not r["event_date"].startswith("2015-"):
            continue
        ev=lr.get(r["event_id"],{})
        excerpt=ev.get("evidence_excerpt","")
        events.append({
            "event_id":r["event_id"],
            "symbol":r["historical_symbol"],
            "event_date":r["event_date"],
            "first_trade":r["first_documented_illicit_trade_ts"],
            "excerpt":excerpt,
            "aliases":aliases(r["historical_symbol"],excerpt),
            "expected_provider":expected_provider(excerpt),
        })
    return events

def next_sitemap_url(html: str, current: str):
    p=LinkParser();p.feed(html)
    for text,href in p.links:
        if text.strip().lower()=="next":
            return urljoin(current,href)
    return None

def scan_window(date: str, start_hour_utc: int, max_pages: int = 7):
    d=datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    cursor=int((d+timedelta(hours=start_hour_utc)).timestamp()*1000)
    url=f"https://finance.yahoo.com/sitemap/{date.replace('-','_')}_start{cursor}/"
    out=[]
    seen=set()
    for _ in range(max_pages):
        if url in seen:
            break
        seen.add(url)
        html=get(url)
        p=LinkParser();p.feed(html)
        for text,href in p.links:
            full=urljoin(url,href)
            if "finance.yahoo.com/news/" in full and text and text.lower() not in {"previous","next"}:
                out.append({"title":text,"url":full})
        nxt=next_sitemap_url(html,url)
        if not nxt:
            break
        # stop if next cursor is well outside event date + 1 day
        m=re.search(r"_start(\d+)",nxt)
        if m:
            ts=datetime.fromtimestamp(int(m.group(1))/1000,tz=timezone.utc)
            if ts > d+timedelta(days=1,hours=17):
                break
        url=nxt
    # unique URL
    return list({x["url"]:x for x in out}.values())

def extract_meta(html: str):
    vals=[]
    patterns=[
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'"pubDate"\s*:\s*"([^"]+)"',
        r'"published_at"\s*:\s*"([^"]+)"',
    ]
    for pat in patterns:
        vals += re.findall(pat,html,re.I)
    # de-duplicate
    vals=list(dict.fromkeys(vals))
    provider=None
    low=html.lower()
    if any(x in low for x in DISALLOWED_PROVIDERS):
        # still permit if an explicit allowed wire provider is present; report conflict.
        pass
    for needle,canon in ALLOWED_PROVIDERS.items():
        if needle in low:
            provider=canon
            break
    return vals,provider,[x for x in DISALLOWED_PROVIDERS if x in low]

def parse_ts(raw: str):
    val=raw.strip().replace("Z","+00:00")
    try:
        dt=datetime.fromisoformat(val)
    except Exception:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)

def url_clock_hint(url: str, date: str):
    m=re.search(r"-(\d{6})(\d{3})?\.html",url)
    if not m:
        return None
    hhmmss=m.group(1)
    try:
        dt=datetime.fromisoformat(f"{date}T{hhmmss[0:2]}:{hhmmss[2:4]}:{hhmmss[4:6]}+00:00")
        return dt.isoformat().replace("+00:00","Z")
    except Exception:
        return None

def main():
    events=parse_inputs()
    token_freq=Counter(t for e in events for t in set(e["aliases"]))
    by_date=defaultdict(list)
    for e in events:
        by_date[e["event_date"]].append(e)

    scans={}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs={}
        for date in by_date:
            # same-day after-market and next-morning windows
            futs[ex.submit(scan_window,date,19,7)]=(date,"after_market")
            futs[ex.submit(scan_window,(datetime.fromisoformat(date)+timedelta(days=1)).date().isoformat(),10,5)]=(date,"next_morning")
        for fut in as_completed(futs):
            date,kind=futs[fut]
            try:
                scans.setdefault(date,{})[kind]=fut.result()
            except Exception as exc:
                scans.setdefault(date,{})[kind]=[]
                scans[date][kind+"_error"]=str(exc)

    candidate_map=[]
    for date,evs in by_date.items():
        articles=(scans.get(date,{}).get("after_market",[])+scans.get(date,{}).get("next_morning",[]))
        for ev in evs:
            scored=[]
            for a in articles:
                title_tokens=set(norm_tokens(a["title"]))
                score=0.0
                matched=[]
                for tok in ev["aliases"]:
                    if tok in title_tokens:
                        w=1.0+math.log((1+len(events))/(1+token_freq[tok]))
                        score+=w
                        matched.append(tok)
                if score>=1.8:
                    scored.append((score,a,matched))
            for score,a,matched in sorted(scored,key=lambda x:-x[0])[:8]:
                candidate_map.append({**ev,"candidate_title":a["title"],"candidate_url":a["url"],"match_score":round(score,3),"matched_aliases":matched})

    # Fetch candidate article metadata concurrently
    unique_urls=sorted({c["candidate_url"] for c in candidate_map})
    meta={}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs={ex.submit(get,u):u for u in unique_urls}
        for fut in as_completed(futs):
            u=futs[fut]
            try:
                html=fut.result()
                vals,provider,bad=extract_meta(html)
                meta[u]={"published_values":vals,"provider":provider,"disallowed_markers":bad}
            except Exception as exc:
                meta[u]={"error":str(exc),"published_values":[],"provider":None,"disallowed_markers":[]}

    admissible=[]
    reviewed=[]
    for c in candidate_map:
        m=meta[c["candidate_url"]]
        trade=datetime.fromisoformat(c["first_trade"]).replace(tzinfo=ET).astimezone(timezone.utc)
        best=None
        for raw in m.get("published_values",[]):
            dt=parse_ts(raw)
            if dt and trade < dt <= trade+timedelta(days=7):
                best=(raw,dt)
                break
        provider=m.get("provider")
        expected=c.get("expected_provider")
        bad=m.get("disallowed_markers",[])
        provider_ok=provider in set(ALLOWED_PROVIDERS.values())
        provider_match=(expected is None or provider==expected)
        row={
            "event_id":c["event_id"],"symbol":c["symbol"],"event_date":c["event_date"],
            "first_trade":c["first_trade"],"candidate_title":c["candidate_title"],"candidate_url":c["candidate_url"],
            "match_score":c["match_score"],"matched_aliases":c["matched_aliases"],
            "expected_provider":expected,"detected_provider":provider,"disallowed_markers":bad,
            "published_values":m.get("published_values",[]),"url_clock_hint":url_clock_hint(c["candidate_url"],c["event_date"]),
        }
        if best:
            row["selected_published_raw"]=best[0]
            row["selected_published_utc"]=best[1].isoformat().replace("+00:00","Z")
        row["admissible_candidate"]=bool(best and provider_ok and provider_match and not bad)
        reviewed.append(row)
        if row["admissible_candidate"]:
            admissible.append(row)

    report={
        "schema_version":"1",
        "research_use_only":True,
        "method":"Yahoo Finance date-cursor sitemap discovery; exact clocks require timezone-aware page metadata plus allowed wire provider and existing chronology window.",
        "unresolved_2015_event_count":len(events),
        "event_date_count":len(by_date),
        "sitemap_article_count":sum(len(v.get("after_market",[]))+len(v.get("next_morning",[])) for v in scans.values()),
        "matched_candidate_count":len(reviewed),
        "admissible_candidate_count":len(admissible),
        "admissible_candidates":admissible,
        "reviewed_candidates":reviewed,
        "scan_errors":{d:{k:v for k,v in x.items() if k.endswith("_error")} for d,x in scans.items() if any(k.endswith("_error") for k in x)},
    }
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
        "unresolved_2015_event_count":report["unresolved_2015_event_count"],
        "event_date_count":report["event_date_count"],
        "sitemap_article_count":report["sitemap_article_count"],
        "matched_candidate_count":report["matched_candidate_count"],
        "admissible_candidate_count":report["admissible_candidate_count"],
        "admissible":[{"event_id":r["event_id"],"symbol":r["symbol"],"timestamp":r["selected_published_utc"],"provider":r["detected_provider"],"url":r["candidate_url"]} for r in admissible],
    },indent=2))

if __name__=="__main__":
    main()
