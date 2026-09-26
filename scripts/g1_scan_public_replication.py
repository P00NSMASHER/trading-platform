from __future__ import annotations

import argparse
import csv
import io
import json
import re
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

BASE = "https://raw.githubusercontent.com/vgreg/hacked_earnings_jfe/main/Data/Press%20releases/{year}.zip"
YEARS = range(2011, 2016)
ENTRY_RE = re.compile(r"^(?P<permno>\\d+)_(?P<date>\\d{8})_(?P<suffix>.+)\\.txt$", re.I)
TIME_RE = re.compile(
    r"(?<!\\d)(?:1[0-2]|0?[1-9])(?:[:.]?[0-5]\\d)?\\s*"
    r"(?:a\\.?m\\.?|p\\.?m\\.?)"
    r"(?:\\s*(?:ET|EST|EDT|Eastern(?:\\s+Time)?))?",
    re.I,
)
NOISE_RE = re.compile(r"conference\\s+call|webcast|web\\s*cast|replay|dial(?:-?in)?|presentation", re.I)
RELEASE_RE = re.compile(r"for\\s+(?:immediate\\s+)?release|release(?:d)?|published|distribution", re.I)


def _norm_space(value: str) -> str:
    return re.sub(r"\\s+", " ", value).strip()


def _decode(blob: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return blob.decode(enc)
        except UnicodeDecodeError:
            pass
    return blob.decode("utf-8", errors="replace")


def _extract_times(text: str) -> list[dict]:
    out = []
    for m in TIME_RE.finditer(text):
        start = max(0, m.start() - 180)
        end = min(len(text), m.end() + 180)
        context = _norm_space(text[start:end])
        out.append({
            "time_text": _norm_space(m.group(0)),
            "context": context,
            "release_context": bool(RELEASE_RE.search(context)),
            "call_or_replay_context": bool(NOISE_RE.search(context)),
            "offset": m.start(),
        })
    return out


def _download(year: int) -> bytes:
    req = urllib.request.Request(
        BASE.format(year=year),
        headers={"User-Agent": "trading-platform-g1-public-corpus-scan/1.0"},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return response.read()


def scan(events_path: Path, outdir: Path) -> dict:
    with events_path.open(newline="", encoding="utf-8") as f:
        events = list(csv.DictReader(f))

    entries_by_permno: dict[str, list[dict]] = {}
    archive_receipts = []

    for year in YEARS:
        blob = _download(year)
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = zf.namelist()
            archive_receipts.append({
                "year": year,
                "url": BASE.format(year=year),
                "byte_count": len(blob),
                "entry_count": len(names),
            })
            for name in names:
                base = Path(name).name
                m = ENTRY_RE.match(base)
                if not m:
                    continue
                try:
                    release_date = datetime.strptime(m.group("date"), "%Y%m%d").date()
                except ValueError:
                    continue
                entries_by_permno.setdefault(m.group("permno"), []).append({
                    "year": year,
                    "name": name,
                    "release_date": release_date,
                    "zip_bytes": blob,
                })

    results = []
    events_with_candidate_files = 0
    events_with_time_tokens = 0
    events_with_release_context_time = 0

    # Re-open archives only when a matching file is needed. Cache ZipFile objects in memory.
    zip_cache: dict[int, zipfile.ZipFile] = {}
    blob_cache: dict[int, bytes] = {}
    for rec in archive_receipts:
        year = rec["year"]
        blob_cache[year] = _download(year)
        zip_cache[year] = zipfile.ZipFile(io.BytesIO(blob_cache[year]))

    try:
        for e in events:
            trade_raw = e["first_documented_illicit_trade_ts"].strip()
            trade = datetime.fromisoformat(trade_raw).date()
            end = trade + timedelta(days=7)
            permno = e["permno"].strip()
            cands = []
            for item in entries_by_permno.get(permno, []):
                if not (trade <= item["release_date"] <= end):
                    continue
                text = _decode(zip_cache[item["year"]].read(item["name"]))
                times = _extract_times(text)
                cands.append({
                    "archive_year": item["year"],
                    "archive_file": item["name"],
                    "release_date": item["release_date"].isoformat(),
                    "text_length": len(text),
                    "text_head": _norm_space(text[:1200]),
                    "time_matches": times,
                })

            if cands:
                events_with_candidate_files += 1
            if any(c["time_matches"] for c in cands):
                events_with_time_tokens += 1
            if any(
                any(t["release_context"] and not t["call_or_replay_context"] for t in c["time_matches"])
                for c in cands
            ):
                events_with_release_context_time += 1

            results.append({
                "event_id": e["event_id"],
                "permno": permno,
                "gvkey": e["gvkey"],
                "historical_symbol": e["historical_symbol"],
                "first_documented_illicit_trade_ts": trade_raw,
                "candidate_file_count": len(cands),
                "candidates": cands,
            })
    finally:
        for zf in zip_cache.values():
            zf.close()

    outdir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "purpose": "Public replication-corpus evidence scan for G1 announcement-time research; no gate is closed automatically.",
        "source_repository": "vgreg/hacked_earnings_jfe",
        "event_count": len(events),
        "events_with_candidate_files": events_with_candidate_files,
        "events_with_time_tokens": events_with_time_tokens,
        "events_with_release_context_time": events_with_release_context_time,
        "archive_receipts": archive_receipts,
        "results": results,
    }
    (outdir / "g1_public_replication_scan.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\\n", encoding="utf-8"
    )

    with (outdir / "g1_public_replication_scan.csv").open("w", newline="", encoding="utf-8") as f:
        fields = [
            "event_id", "permno", "historical_symbol", "first_documented_illicit_trade_ts",
            "candidate_file_count", "candidate_files", "candidate_dates",
            "time_match_count", "release_context_time_count",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            matches = [t for c in r["candidates"] for t in c["time_matches"]]
            strong = [t for t in matches if t["release_context"] and not t["call_or_replay_context"]]
            w.writerow({
                "event_id": r["event_id"],
                "permno": r["permno"],
                "historical_symbol": r["historical_symbol"],
                "first_documented_illicit_trade_ts": r["first_documented_illicit_trade_ts"],
                "candidate_file_count": r["candidate_file_count"],
                "candidate_files": ";".join(c["archive_file"] for c in r["candidates"]),
                "candidate_dates": ";".join(c["release_date"] for c in r["candidates"]),
                "time_match_count": len(matches),
                "release_context_time_count": len(strong),
            })

    summary = {k: payload[k] for k in (
        "event_count", "events_with_candidate_files", "events_with_time_tokens",
        "events_with_release_context_time"
    )}
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\\n", encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", type=Path, default=Path("data/processed/historical_events.csv"))
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(scan(args.events, args.outdir), indent=2))


if __name__ == "__main__":
    main()
