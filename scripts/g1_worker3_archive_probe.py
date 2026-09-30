#!/usr/bin/env python3
import csv, html, json, re, sys, time
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse
import requests

TARGETS = [
 {"event_id":"HEJFE-F9E72EEF6E5BD373","symbol":"NATI","date":"2015-01-29","title":"National Instruments Reports Record Revenue and Net Income for 2014","known_urls":["https://ca.marketscreener.com/quote/stock/NATIONAL-INSTRUMENTS-CORP-10156/news/National-Instruments-Reports-Record-Revenue-and-Net-Income-for-2014-19785765/","https://www.businesswire.com/news/home/20150129006428/en"]},
 {"event_id":"HEJFE-947F50EBAFBA54DC","symbol":"CRL","date":"2015-02-10","title":"Charles River Laboratories Announces Fourth-Quarter and Full-Year 2014 Results from Continuing Operations and Provides 2015 Guidance","known_urls":["https://ir.criver.com/news-releases/news-release-details/charles-river-laboratories-announces-fourth-quarter-and-full-3","https://www.businesswire.com/news/home/20150210006620/en"]},
 {"event_id":"HEJFE-22BF36BABB9D19D7","symbol":"ALNY","date":"2015-02-12","title":"Alnylam Pharmaceuticals Reports Fourth Quarter and Full Year 2014 Financial Results and Highlights Recent Period Progress","known_urls":["https://investors.alnylam.com/press-release?id=15321","https://www.businesswire.com/news/home/20150212006389/en"]},
 {"event_id":"HEJFE-7CEFB3FE3D986464","symbol":"ROG","date":"2015-02-17","title":"Rogers Corporation Reports 2014 Fourth Quarter and Year-End Results","known_urls":[]},
 {"event_id":"HEJFE-0273F1BFCD285E7F","symbol":"THC","date":"2015-02-23","title":"","known_urls":[]},
 {"event_id":"HEJFE-4D7E68AD113380B3","symbol":"TRAK","date":"2015-02-23","title":"Dealertrack Technologies Reports Record Revenue for Fourth Quarter and Full Year 2014","known_urls":[]},
 {"event_id":"HEJFE-99F31DB35F001A44","symbol":"DXCM","date":"2015-02-25","title":"DexCom, Inc. Reports Fourth Quarter and Full Year 2014 Financial Results","known_urls":["https://investors.dexcom.com/news/news-details/2015/DexCom-Inc.-Reports-Fourth-Quarter-and-Full-Year-2014-Financial-Results/default.aspx","https://www.businesswire.com/news/home/20150225006324/en"]},
 {"event_id":"HEJFE-BB62E8864F35DCD0","symbol":"WLL","date":"2015-02-25","title":"Whiting Petroleum Corporation Announces Fourth Quarter and Full-Year 2014 Financial and Operating Results","known_urls":[]},
 {"event_id":"HEJFE-EBC49B9A024181AD","symbol":"VEEV","date":"2015-03-03","title":"Veeva Announces Fourth Quarter and Fiscal Year 2015 Results","known_urls":["https://www.veeva.com/resources/veeva-announces-fourth-quarter-and-fiscal-year-2015-results/"]},
 {"event_id":"HEJFE-263620F13A6443DD","symbol":"MAT","date":"2015-04-16","title":"","known_urls":[]},
 {"event_id":"HEJFE-D35C7804C2F5326C","symbol":"CREE","date":"2015-04-21","title":"Cree Reports Financial Results for the Third Quarter of Fiscal Year 2015","known_urls":[]},
 {"event_id":"HEJFE-33FC1D00348D7C59","symbol":"ROG","date":"2015-04-29","title":"Rogers Corporation Reports Strong Earnings and All-time Record Quarterly Sales for the First Quarter of 2015","known_urls":[]},
 {"event_id":"HEJFE-EFFA194386ABDD28","symbol":"IDTI","date":"2015-05-04","title":"","known_urls":[]},
 {"event_id":"HEJFE-A3C5C43F6AC75C44","symbol":"PRU","date":"2015-05-06","title":"PRUDENTIAL FINANCIAL, INC. ANNOUNCES FIRST QUARTER 2015 RESULTS","known_urls":[]},
 {"event_id":"HEJFE-E575622C8FDAB71F","symbol":"ISIL","date":"2013-04-24","title":"Intersil Corporation Reports First Quarter 2013 Results","known_urls":[]},
 {"event_id":"HEJFE-C368B17FADFC15C7","symbol":"ECHO","date":"2013-04-25","title":"Echo Global Logistics Announces First Quarter 2013 Results","known_urls":[]},
 {"event_id":"HEJFE-ED8CFC03F1053B9A","symbol":"CAMP","date":"2013-04-25","title":"CalAmp Reports Fiscal 2013 Fourth Quarter and Full Year Results","known_urls":[]},
 {"event_id":"HEJFE-A5AE76F13A48C40F","symbol":"DGI","date":"2013-05-07","title":"DigitalGlobe Reports First Quarter 2013 Results","known_urls":[]},
 {"event_id":"HEJFE-D7BD84C255F2273D","symbol":"GORO","date":"2013-05-08","title":"GOLD RESOURCE CORPORATION REPORTS FIRST QUARTER RESULTS; MAINTAINS 2013 PRODUCTION OUTLOOK","known_urls":[]},
 {"event_id":"HEJFE-847F0EFE669B2440","symbol":"P","date":"2015-02-05","title":"","known_urls":[]},
]

UA = {"User-Agent":"Mozilla/5.0 (compatible; G1HistoricalResearch/1.0; +https://github.com/P00NSMASHER/trading-platform)"}
OUT=Path("g1_worker3_archive_probe")
OUT.mkdir(exist_ok=True)

TIME_PATTERNS = [
 re.compile(r'(?i)(published|posted|release(?:d)?|updated|date)[^\n<]{0,100}?(\b\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?|AM|PM)?\s*(?:EST|EDT|ET|CST|CDT|CT|MST|MDT|MT|PST|PDT|PT|UTC|GMT)\b)'),
 re.compile(r'(?i)\b(\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?|AM|PM)\s*(?:EST|EDT|ET|CST|CDT|CT|MST|MDT|MT|PST|PDT|PT|UTC|GMT))\b'),
 re.compile(r'(?i)\b(\d{1,2}:\d{2}:\d{2}\s*(?:EST|EDT|UTC|GMT))\b'),
]
META_KEYS=("datePublished","article:published_time","publishdate","pubdate","datepublished","datePublished","og:published_time")

def get(url):
    try:
        r=requests.get(url,headers=UA,timeout=25,allow_redirects=True)
        return {"requested_url":url,"final_url":r.url,"status":r.status_code,"headers":dict(r.headers),"text":r.text[:2_000_000]}
    except Exception as e:
        return {"requested_url":url,"error":repr(e),"text":""}

def search_ddg(q):
    u="https://html.duckduckgo.com/html/?q="+quote_plus(q)
    d=get(u)
    links=[]
    for m in re.finditer(r'class="result__a"[^>]+href="([^"]+)"',d.get("text","")):
        href=html.unescape(m.group(1))
        links.append(href)
    return d,links

def extract(url, body):
    flat=re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',body))
    times=[]
    for p in TIME_PATTERNS:
        for m in p.finditer(flat):
            times.append(m.group(0)[:220])
    metas=[]
    for key in META_KEYS:
        for m in re.finditer(r'(?is)<meta[^>]+(?:name|property)=["\']%s["\'][^>]+content=["\']([^"\']+)["\']' % re.escape(key),body):
            metas.append({"key":key,"value":html.unescape(m.group(1))})
        for m in re.finditer(r'(?is)["\']%s["\']\s*:\s*["\']([^"\']+)["\']' % re.escape(key),body):
            metas.append({"key":key,"value":html.unescape(m.group(1))})
    return {"url":url,"time_hits":times[:30],"meta_hits":metas[:30],"title_hint":flat[:500]}

rows=[]
raw={}
for t in TARGETS:
    queries=[]
    if t["title"]:
        queries += [
          f'"{t["title"]}" site:marketscreener.com',
          f'"{t["title"]}" site:streetinsider.com',
          f'"{t["title"]}" site:businesswire.com',
          f'"{t["title"]}" site:financialcontent.com',
          f'"{t["title"]}" "{t["date"]}"'
        ]
    else:
        queries += [f'{t["symbol"]} earnings {t["date"]} Business Wire',f'{t["symbol"]} results {t["date"]} press release']
    urls=list(t["known_urls"])
    search_records=[]
    for q in queries:
        d,links=search_ddg(q)
        search_records.append({"q":q,"status":d.get("status"),"links":links[:20]})
        for u in links:
            if any(dom in u for dom in ["marketscreener.","streetinsider.","businesswire.","financialcontent.","nasdaq.","yahoo.","prnewswire.","globenewswire.","marketwired.","accesswire.","ir.","investor","veeva.com","dexcom.com"]):
                urls.append(u)
        time.sleep(.4)
    seen=[]
    for u in urls:
        if u not in seen: seen.append(u)
    fetched=[]
    for u in seen[:40]:
        d=get(u)
        e=extract(d.get("final_url",u),d.get("text",""))
        fetched.append({k:v for k,v in d.items() if k!="text"} | e)
        key=f'{t["event_id"]}_{len(fetched):02d}.html'
        if d.get("text"):
            (OUT/key).write_text(d["text"],encoding="utf-8",errors="ignore")
        time.sleep(.25)
    rec={"target":t,"searches":search_records,"fetched":fetched}
    raw[t["event_id"]]=rec
    for f in fetched:
        for mh in f.get("meta_hits",[]):
            rows.append({"event_id":t["event_id"],"symbol":t["symbol"],"date":t["date"],"source_url":f.get("final_url"),"kind":"meta","evidence":f'{mh["key"]}={mh["value"]}'})
        for th in f.get("time_hits",[]):
            rows.append({"event_id":t["event_id"],"symbol":t["symbol"],"date":t["date"],"source_url":f.get("final_url"),"kind":"time_text","evidence":th})

(OUT/"probe.json").write_text(json.dumps(raw,indent=2,sort_keys=True),encoding="utf-8")
with (OUT/"hits.csv").open("w",newline="",encoding="utf-8") as fh:
    w=csv.DictWriter(fh,fieldnames=["event_id","symbol","date","source_url","kind","evidence"])
    w.writeheader(); w.writerows(rows)
print(json.dumps({"targets":len(TARGETS),"evidence_rows":len(rows),"out":str(OUT)},indent=2))
