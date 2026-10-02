from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "private_runtime" / "audit" / "fnspid-bulk-probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

RESOLUTIONS = ROOT / "data" / "processed" / "authorized_input_real" / "announcement_resolutions.csv"

WIRE_WORDS = (
    "business wire",
    "pr newswire",
    "globenewswire",
    "globe newswire",
    "marketwired",
    "marketwire",
)
GOOD_PHRASES = (
    "reports",
    "announces",
    "financial results",
    "quarter results",
    "quarterly results",
    "earnings",
    "fiscal",
)
BAD_PHRASES = (
    "to announce",
    "to report",
    "scheduled",
    "conference call",
    "earnings call",
    "transcript",
    "preview",
    "estimate",
    "estimates",
    "analyst",
    "beats",
    "misses",
    "why ",
    "shares are trading",
)


def parse_iso(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_news_date(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    variants = [
        raw.replace(" UTC", "+00:00"),
        raw.replace(" GMT", "+00:00"),
        raw,
    ]
    for item in variants:
        try:
            dt = datetime.fromisoformat(item)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def load_unresolved() -> list[dict[str, object]]:
    out = []
    with RESOLUTIONS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["resolution_status"] != "excluded_fail_closed":
                continue
            trade = parse_iso(row["first_documented_illicit_trade_ts"])
            out.append(
                {
                    "event_id": row["event_id"],
                    "symbol": row["historical_symbol"],
                    "event_date": row["event_date"],
                    "trade_ts": trade,
                    "window_end": trade + timedelta(days=7),
                }
            )
    return out


def score_candidate(title: str, publisher: str, url: str) -> int:
    t = (title or "").lower()
    p = (publisher or "").lower()
    score = 0
    if "financial results" in t:
        score += 7
    if "reports" in t or "announces" in t:
        score += 4
    if "results" in t:
        score += 4
    if "earnings" in t:
        score += 2
    if any(x in t for x in ("quarter", "quarterly", "fiscal", "year-end", "full year")):
        score += 2
    if any(x in p for x in WIRE_WORDS):
        score += 5
    host = urlparse(url or "").netloc.lower()
    if host.endswith("finance.yahoo.com"):
        score += 3
    if host.endswith("businesswire.com") or host.endswith("prnewswire.com") or host.endswith("globenewswire.com"):
        score += 5
    if any(x in t for x in BAD_PHRASES):
        score -= 8
    return score


def main() -> int:
    unresolved = load_unresolved()
    by_symbol: dict[str, list[dict[str, object]]] = defaultdict(list)
    for event in unresolved:
        by_symbol[str(event["symbol"]).upper()].append(event)

    candidates: dict[str, list[dict[str, object]]] = defaultdict(list)
    total_lines = 0
    malformed = 0
    symbol_hits = 0
    window_hits = 0

    for raw in sys.stdin.buffer:
        total_lines += 1
        try:
            row = json.loads(raw)
        except Exception:
            malformed += 1
            continue
        symbol = str(row.get("Stock_symbol") or "").strip().upper()
        if symbol not in by_symbol:
            continue
        symbol_hits += 1
        dt = parse_news_date(str(row.get("Date") or ""))
        if dt is None:
            continue
        for event in by_symbol[symbol]:
            trade = event["trade_ts"]
            end = event["window_end"]
            if not (trade < dt <= end):
                continue
            window_hits += 1
            title = str(row.get("Article_title") or "").strip()
            url = str(row.get("Url") or "").strip()
            publisher = str(row.get("Publisher") or "").strip()
            score = score_candidate(title, publisher, url)
            candidates[str(event["event_id"])].append(
                {
                    "event_id": event["event_id"],
                    "symbol": symbol,
                    "event_date": event["event_date"],
                    "first_trade_utc": trade.isoformat().replace("+00:00", "Z"),
                    "news_timestamp_utc": dt.isoformat().replace("+00:00", "Z"),
                    "seconds_after_trade": int((dt - trade).total_seconds()),
                    "title": title,
                    "publisher": publisher,
                    "url": url,
                    "score": score,
                }
            )

    result_rows = []
    release_like_events = 0
    any_events = 0
    for event in unresolved:
        eid = str(event["event_id"])
        rows = sorted(
            candidates.get(eid, []),
            key=lambda r: (-int(r["score"]), r["news_timestamp_utc"], r["url"]),
        )
        if rows:
            any_events += 1
        if rows and int(rows[0]["score"]) >= 7:
            release_like_events += 1
        result_rows.extend(rows[:15])

    summary = {
        "schema_version": "1",
        "source": "FNSPID Stock_news/All_external.jsonl",
        "source_url": "https://huggingface.co/datasets/khaihernlow/fnspid/resolve/main/Stock_news/All_external.jsonl?download=true",
        "research_use_only": True,
        "unresolved_event_count": len(unresolved),
        "events_with_any_candidate": any_events,
        "events_with_release_like_top_candidate_score_ge_7": release_like_events,
        "total_lines_seen": total_lines,
        "malformed_lines_skipped": malformed,
        "symbol_matching_rows_seen": symbol_hits,
        "event_window_rows_seen": window_hits,
        "candidate_rows_retained": len(result_rows),
        "note": "Candidates are discovery leads only. FNSPID timestamps must be corroborated against admissible publisher/issuer evidence before G1 promotion.",
    }

    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (OUT_DIR / "candidates.json").write_text(json.dumps(result_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    fields = [
        "event_id", "symbol", "event_date", "first_trade_utc", "news_timestamp_utc",
        "seconds_after_trade", "score", "publisher", "title", "url",
    ]
    with (OUT_DIR / "candidates.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result_rows)

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# trigger bulk probe
