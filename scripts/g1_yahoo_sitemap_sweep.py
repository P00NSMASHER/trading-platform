#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANNOUNCEMENTS = ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv"
G3 = ROOT / "data/public/metadata/g3_primary_listing_history.csv"

UA = "Mozilla/5.0 (compatible; G1HistoricalResearch/1.0; +https://github.com/P00NSMASHER/trading-platform)"
EARNINGS_RE = re.compile(r"\b(report|reports|reported|results|earnings|quarter|quarterly|fiscal|profit|loss|financial)\b", re.I)
WIRE_MARKERS = ("BUSINESS WIRE", "Marketwired", "MARKETWIRE", "PRNewswire", "PR Newswire", "GlobeNewswire", "GLOBE NEWSWIRE")
GENERIC = {
    "reports","report","reported","results","result","quarter","quarterly","financial","earnings","fiscal",
    "company","corporation","inc","incorporated","limited","plc","group","holdings","the","and","for","first",
    "second","third","fourth","full","year","announces","announce","today","nasdaq","nyse","common","stock",
}
URL_TS_RE = re.compile(r"-(\d{6})\d{3}(?:--[a-z]+)?\.html(?:\?|$)", re.I)
DATE_PUBLISHED_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.I)

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []
    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            text = " ".join(" ".join(self._text).split())
            self.links.append((self._href, html.unescape(text)))
            self._href = None
            self._text = []

def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")

def parse_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def clean_tokens(text: str):
    toks = re.findall(r"[A-Za-z][A-Za-z0-9&.'-]{2,}", text or "")
    return {t.lower().strip(".'-") for t in toks if t.lower().strip(".'-") not in GENERIC}

def event_aliases():
    rows = parse_rows(G3)
    out = defaultdict(set)
    for row in rows:
        eid = row["event_id"]
        sym = row["historical_symbol"].upper()
        out[eid].add(sym.lower())
        excerpt = row.get("evidence_excerpt", "")
        toks = list(clean_tokens(excerpt))
        # The first press-release/SEC excerpt words are usually the issuer name.
        for tok in toks[:14]:
            out[eid].add(tok)
    return out

def parse_yahoo_url_timestamp(url: str, date_hint: str):
    m = URL_TS_RE.search(url)
    if not m:
        return None
    hhmmss = m.group(1)
    try:
        day = datetime.strptime(date_hint, "%Y-%m-%d").date()
        return datetime(day.year, day.month, day.day, int(hhmmss[:2]), int(hhmmss[2:4]), int(hhmmss[4:6]), tzinfo=timezone.utc)
    except ValueError:
        return None

def sitemap_url(date_str: str, dt: datetime):
    stamp = int(dt.timestamp() * 1000)
    d = dt.strftime("%Y_%m_%d")
    return f"https://finance.yahoo.com/sitemap/{d}_start{stamp}/"

def next_sitemap(links, date_str):
    d = date_str.replace("-", "_")
    candidates = [urllib.parse.urljoin("https://finance.yahoo.com", href) for href, _ in links if f"/sitemap/{d}_start" in href]
    if not candidates:
        return None
    # Yahoo emits one forward cursor plus sometimes the current/bare date.
    def stamp(u):
        m = re.search(r"_start(\d+)/", u)
        return int(m.group(1)) if m else -1
    return max(candidates, key=stamp)

def scan_window(date_str: str, start_dt: datetime, end_dt: datetime):
    url = sitemap_url(date_str, start_dt)
    seen_pages = set()
    articles = {}
    errors = []
    for _ in range(80):
        if url in seen_pages:
            break
        seen_pages.add(url)
        try:
            body = fetch(url)
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
            break
        parser = LinkParser()
        parser.feed(body)
        next_url = next_sitemap(parser.links, date_str)
        for href, title in parser.links:
            full = urllib.parse.urljoin("https://finance.yahoo.com", href)
            if "/news/" not in full or not title or not EARNINGS_RE.search(title):
                continue
            ts = parse_yahoo_url_timestamp(full, date_str)
            if ts is None:
                continue
            if start_dt <= ts <= end_dt:
                articles[full] = {"url": full, "title": title, "url_timestamp_utc": ts.isoformat().replace("+00:00","Z")}
        if not next_url:
            break
        m = re.search(r"_start(\d+)/", next_url)
        if not m:
            break
        next_dt = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
        if next_dt > end_dt:
            break
        url = next_url
        time.sleep(0.03)
    return list(articles.values()), errors

def article_match(article, events, alias_map):
    url = article["url"]
    title = article["title"]
    ts = datetime.fromisoformat(article["url_timestamp_utc"].replace("Z","+00:00"))
    title_tokens = clean_tokens(title)
    try:
        body = fetch(url)
    except Exception:
        body = ""
    upper = body.upper()
    page_ts = None
    m = DATE_PUBLISHED_RE.search(body)
    if m:
        page_ts = m.group(1)
    wire = next((w for w in WIRE_MARKERS if w.upper() in upper), None)
    matches = []
    for event in events:
        trade = datetime.fromisoformat(event["first_documented_illicit_trade_ts"].replace("Z","+00:00"))
        if not (trade < ts <= trade + timedelta(days=7)):
            continue
        sym = event["historical_symbol"].upper()
        ticker_marker = any(marker in upper for marker in (
            f"NASDAQ: {sym}", f"NASDAQ:{sym}", f"NYSE: {sym}", f"NYSE:{sym}",
            f"NASDAQGS: {sym}", f"NASDAQGS:{sym}", f"NYSE MKT: {sym}", f"NYSE MKT:{sym}"
        ))
        aliases = alias_map.get(event["event_id"], set())
        alias_overlap = sorted(title_tokens & aliases)
        score = 0
        if ticker_marker:
            score += 7
        if sym.lower() in title.lower().split():
            score += 4
        if len(alias_overlap) >= 2:
            score += 4
        elif len(alias_overlap) == 1:
            score += 1
        if wire:
            score += 5
        if EARNINGS_RE.search(title):
            score += 1
        if score >= 5:
            matches.append({
                "event_id": event["event_id"],
                "historical_symbol": sym,
                "trade_ts": event["first_documented_illicit_trade_ts"],
                "candidate_public_ts": article["url_timestamp_utc"],
                "title": title,
                "url": url,
                "wire_marker": wire,
                "ticker_marker": ticker_marker,
                "alias_overlap": alias_overlap,
                "score": score,
                "page_datePublished": page_ts,
                "seconds_after_trade": int((ts-trade).total_seconds()),
            })
    return matches

def known_self_check():
    known = [
        ("2013-04-25", "https://finance.yahoo.com/news/ehealth-inc-announces-first-quarter-201500765.html", "20:15:00"),
        ("2013-04-25", "https://finance.yahoo.com/news/micrel-reports-2013-first-quarter-200100018.html", "20:01:00"),
        ("2013-04-25", "https://finance.yahoo.com/news/proofpoint-announces-first-quarter-2013-200500289.html", "20:05:00"),
    ]
    out = []
    for d, url, clock in known:
        ts = parse_yahoo_url_timestamp(url, d)
        ok = bool(ts and ts.strftime("%H:%M:%S") == clock)
        try:
            body = fetch(url)
            wire = any(w.upper() in body.upper() for w in WIRE_MARKERS)
        except Exception:
            wire = False
        out.append({"url": url, "timestamp_ok": ok, "wire_marker_seen": wire})
    return out

def scan_date(date_str, date_events, alias_map):
    trades = [datetime.fromisoformat(r["first_documented_illicit_trade_ts"].replace("Z","+00:00")) for r in date_events]
    earliest = min(trades)
    date0 = earliest.date()
    # Same-day: start just before the earliest suspicious trade, through midnight.
    start1 = earliest.replace(minute=(earliest.minute//15)*15, second=0, microsecond=0) - timedelta(minutes=15)
    end1 = datetime(date0.year, date0.month, date0.day, 23, 59, 59, tzinfo=timezone.utc)
    articles1, errors1 = scan_window(date_str, start1, end1)
    # Next morning captures releases like Gardner Denver.
    next_day = date0 + timedelta(days=1)
    start2 = datetime(next_day.year, next_day.month, next_day.day, 9, 30, 0, tzinfo=timezone.utc)
    end2 = datetime(next_day.year, next_day.month, next_day.day, 16, 0, 0, tzinfo=timezone.utc)
    articles2, errors2 = scan_window(next_day.isoformat(), start2, end2)

    dedup = {a["url"]: a for a in articles1 + articles2}
    matches = []
    for article in dedup.values():
        matches.extend(article_match(article, date_events, alias_map))
    # Keep best candidate per event/url, then sort by score/time.
    unique = {}
    for m in matches:
        key = (m["event_id"], m["url"])
        if key not in unique or m["score"] > unique[key]["score"]:
            unique[key] = m
    ordered = sorted(unique.values(), key=lambda x: (-x["score"], x["candidate_public_ts"], x["event_id"]))
    return {
        "event_date": date_str,
        "event_count": len(date_events),
        "article_candidates_scanned": len(dedup),
        "matches": ordered,
        "errors": errors1 + errors2,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-dates", type=int, default=20)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default="private_runtime/audit/g1-yahoo-sitemap-sweep/candidates.json")
    args = ap.parse_args()

    rows = [r for r in parse_rows(ANNOUNCEMENTS) if r["resolution_status"] == "excluded_fail_closed"]
    grouped = defaultdict(list)
    for r in rows:
        grouped[r["event_date"]].append(r)
    selected = sorted(grouped, key=lambda d: (-len(grouped[d]), d))[:args.top_dates]
    aliases = event_aliases()

    self_check = known_self_check()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(scan_date, d, grouped[d], aliases): d for d in selected}
        for fut in as_completed(futs):
            d = futs[fut]
            try:
                results.append(fut.result())
            except Exception as exc:
                results.append({"event_date": d, "event_count": len(grouped[d]), "article_candidates_scanned": 0, "matches": [], "errors": [f"{type(exc).__name__}: {exc}"]})
    results.sort(key=lambda r: (-r["event_count"], r["event_date"]))

    best = {}
    for result in results:
        for m in result["matches"]:
            eid = m["event_id"]
            if eid not in best or m["score"] > best[eid]["score"]:
                best[eid] = m
    strong = sorted((m for m in best.values() if m["wire_marker"] and m["score"] >= 10), key=lambda x: (-x["score"], x["event_id"]))
    review = sorted((m for m in best.values() if m not in strong), key=lambda x: (-x["score"], x["event_id"]))

    payload = {
        "schema_version": "1",
        "research_use_only": True,
        "method": "Yahoo historical sitemap epoch-window sweep; original/preserved wire candidates only, never auto-promotes G1.",
        "unresolved_event_count": len(rows),
        "dates_scanned": selected,
        "self_check": self_check,
        "strong_candidate_count": len(strong),
        "strong_candidates": strong,
        "review_candidate_count": len(review),
        "review_candidates": review,
        "date_results": results,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "unresolved_event_count": len(rows),
        "dates_scanned": len(selected),
        "strong_candidate_count": len(strong),
        "review_candidate_count": len(review),
        "self_check": self_check,
        "out": str(out.relative_to(ROOT)),
    }, indent=2))

if __name__ == "__main__":
    main()
