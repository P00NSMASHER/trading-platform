from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/public/metadata/g1_businesswire_bulk_timestamp_scan.json"

SOURCES = [
    ("HEJFE-47A3794D1C360650","NOW","https://www.businesswire.com/news/home/20150416006548/en/ServiceNow-Reports-Financial-Results-Quarter-2015"),
    ("HEJFE-EBC49B9A024181AD","VEEV","https://www.businesswire.com/news/home/20150303006649/en/Veeva-Announces-Fourth-Quarter-Fiscal-Year-2015"),
    ("HEJFE-B9C8B3D0EF3DCB5E","CACI","https://www.businesswire.com/news/home/20150429006490/en/CACI-Reports-Results-Fiscal-2015-Quarter"),
    ("HEJFE-4291CBF555CED6A9","PBI","https://www.businesswire.com/news/home/20150430005115/en/Pitney-Bowes-Announces-Quarter-2015-Financial-Results"),
    ("HEJFE-7CEFB3FE3D986464","ROG","https://www.businesswire.com/news/home/20150217006527/en/Rogers-Corporation-Reports-2014-Fourth-Quarter-Year-End"),
    ("HEJFE-33FC1D00348D7C59","ROG","https://www.businesswire.com/news/home/20150429006474/en/Rogers-Corporation-Reports-Strong-Earnings-All-time-Record"),
    ("HEJFE-332D5C6DC3ACE6B1","NDSN","https://www.businesswire.com/news/home/20150519007045/en/Nordson-Corporation-Reports-Fiscal-Year-2015-Quarter"),
    ("HEJFE-D51AC412EDF93AA8","INT","https://www.businesswire.com/news/home/20150430006873/en/World-Fuel-Services-Corporation-Reports-Record-Quarter"),
    ("HEJFE-FBA59D82CEE8FD00","CGNX","https://www.businesswire.com/news/home/20150212006374/en/Cognex-Reports-Record-Results-2014"),
    ("HEJFE-8EAA8616B1750B40","CGNX","https://www.businesswire.com/news/home/20150504006143/en/Cognex-Reports-Record-Quarter-Revenue-Net-Income"),
    ("HEJFE-8A0517D50278EAE4","POWI","https://www.businesswire.com/news/home/20150429006614/en/Power-Integrations-Reports-First-Quarter-Financial-Results"),
    ("HEJFE-947F50EBAFBA54DC","CRL","https://www.businesswire.com/news/home/20150210006620/en/Charles-River-Laboratories-Announces-Fourth-Quarter-Full-Year-2014"),
    ("HEJFE-45559DD90D876D39","ILMN","https://www.businesswire.com/news/home/20150421006647/en/Illumina-Reports-Strong-Start-Fiscal-Year-2015"),
    ("HEJFE-22BF36BABB9D19D7","ALNY","https://www.businesswire.com/news/home/20150212006389/en/Alnylam-Pharmaceuticals-Reports-Fourth-Quarter-Full-Year"),
    ("HEJFE-93A7D27EF425EDF0","MIC","https://www.businesswire.com/news/home/20150218006559/en/Macquarie-Infrastructure-Company-Reports-Fourth-Quarter-Full-Year"),
    ("HEJFE-C926C41F03E66E82","PAY","https://www.businesswire.com/news/home/20141215006347/en/Verifone-Reports-Results-Fourth-Quarter-Full-Year"),
    ("HEJFE-99F31DB35F001A44","DXCM","https://www.businesswire.com/news/home/20150225006324/en/DexCom-Reports-Fourth-Quarter-Full-Year-2014"),
    ("HEJFE-5D222F0F8E0C77D0","TW","https://www.businesswire.com/news/home/20150505005226/en/Towers-Watson-Reports-Strong-Quarter-Earnings"),
    ("HEJFE-6C4EA140AD75FFE2","THC","https://www.businesswire.com/news/home/20150504006425/en/Tenet-Reports-Adjusted-EBITDA-529-Million-Quarter"),
    ("HEJFE-A3C5C43F6AC75C44","PRU","https://www.businesswire.com/news/home/20150506006527/en/Prudential-Financial-Announces-Quarter-2015-Results"),
    ("HEJFE-E28050410A1480C6","DYN","https://www.businesswire.com/news/home/20150506006641/en/Dynegy-Announces-2015-Quarter-Results-Affirms-2015"),
    ("HEJFE-3046057647A0FC5C","BRKR","https://www.businesswire.com/news/home/20150506006103/en/Bruker-Reports-Quarter-2015-Financial-Results"),
    ("HEJFE-5E9AD5C9AD67944D","CSOD","https://www.businesswire.com/news/home/20150506006589/en/Cornerstone-OnDemand-Announces-Quarter-2015-Financial-Results"),
]

ISO_RE = re.compile(r"20(?:11|12|13|14|15)-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})")
DATE_PUBLISHED_RES = [
    re.compile(r'(?i)["\']datePublished["\']\s*:\s*["\']([^"\']+)["\']'),
    re.compile(r'(?i)property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)["\']'),
    re.compile(r'(?i)name=["\']article:published_time["\'][^>]*content=["\']([^"\']+)["\']'),
    re.compile(r'(?i)content=["\']([^"\']+)["\'][^>]*property=["\']article:published_time["\']'),
]
VISIBLE_CLOCK_RE = re.compile(
    r"(?i)(?:published|release(?:d)?|issued)[^\n<]{0,120}?"
    r"((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+20(?:11|12|13|14|15)"
    r"[^\n<]{0,80}?(?:\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)\s*(?:EST|EDT|ET|PST|PDT|PT|CST|CDT|CT)?))"
)

def fetch(url: str) -> tuple[int, str, str]:
    cmd = [
        "curl","-sS","-L","--compressed","--max-time","40",
        "-A","Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36",
        "-H","Accept-Language: en-US,en;q=0.9",
        "-w","\n__STATUS__:%{http_code}\n__FINAL__:%{url_effective}\n",
        url,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=50)
    text = p.stdout
    mstatus = re.search(r"\n__STATUS__:(\d+)\n", text)
    mfinal = re.search(r"\n__FINAL__:(.+)\n?$", text)
    status = int(mstatus.group(1)) if mstatus else 0
    final = mfinal.group(1).strip() if mfinal else url
    body = text[:mstatus.start()] if mstatus else text
    return status, final, body

rows=[]
for event_id,symbol,url in SOURCES:
    try:
        status,final,body=fetch(url)
    except Exception as exc:
        rows.append({"event_id":event_id,"symbol":symbol,"url":url,"status":"exception","error":repr(exc)})
        continue

    decoded=html.unescape(body)
    published=[]
    for rx in DATE_PUBLISHED_RES:
        published += [m.group(1).strip() for m in rx.finditer(decoded)]
    iso=ISO_RE.findall(decoded)
    visible=[m.group(1).strip() for m in VISIBLE_CLOCK_RE.finditer(decoded)]

    title=""
    mt=re.search(r"(?is)<title[^>]*>(.*?)</title>",decoded)
    if mt:
        title=re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",mt.group(1))).strip()

    rows.append({
        "event_id":event_id,
        "symbol":symbol,
        "url":url,
        "http_status":status,
        "final_url":final,
        "html_bytes":len(body.encode("utf-8",errors="ignore")),
        "title":title[:500],
        "date_published_candidates":sorted(set(published)),
        "iso_timestamp_candidates":sorted(set(iso))[:100],
        "visible_publication_clock_candidates":sorted(set(visible))[:50],
        "contains_businesswire_marker":"BUSINESS WIRE" in decoded.upper(),
        "contains_bot_challenge":any(x in decoded.lower() for x in ("access denied","captcha","cf-chl","just a moment")),
        "body_prefix":re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",decoded[:5000]))[:1500],
    })

summary={
    "schema_version":"1",
    "research_use_only":True,
    "purpose":"Bulk scan of exact original Business Wire URLs for publisher publication-time metadata. No row is admissible until independently validated against event identity, chronology and corroborating evidence.",
    "source_count":len(SOURCES),
    "http_200_count":sum(r.get("http_status")==200 for r in rows),
    "explicit_date_published_count":sum(bool(r.get("date_published_candidates")) for r in rows),
    "visible_publication_clock_count":sum(bool(r.get("visible_publication_clock_candidates")) for r in rows),
    "bot_challenge_count":sum(bool(r.get("contains_bot_challenge")) for r in rows),
    "results":rows,
}
OUT.write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps({k:summary[k] for k in ("source_count","http_200_count","explicit_date_published_count","visible_publication_clock_count","bot_challenge_count")},indent=2))
