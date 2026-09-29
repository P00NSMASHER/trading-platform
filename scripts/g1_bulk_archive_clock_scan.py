from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv"
G3 = ROOT / "data/public/metadata/g3_primary_listing_history.csv"
OUT = ROOT / "data/public/metadata/g1_bulk_archive_clock_scan.json"

WIRE_TERMS = (
    "business wire",
    "marketwired",
    "marketwire",
    "pr newswire",
    "prnewswire",
    "globe newswire",
    "globenewswire",
    "reuters",
)
TIME_RE = re.compile(
    r"(?i)\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?|am|pm|"
    r"et|est|edt|pt|pst|pdt|ct|cst|cdt)?\b|"
    r"\b(?:1[0-2]|0?[1-9])\s*(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?|am|pm)\b"
)
TZ_RE = re.compile(r"(?i)\b(?:eastern|central|mountain|pacific)\s+(?:time|standard time|daylight time)\b|\b(?:EST|EDT|CST|CDT|MST|MDT|PST|PDT|ET|CT|MT|PT)\b")
URL_RE = re.compile(r"https?://[^\s<>()\]\[\"']+")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def normalize_text(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


ann = read_csv(ANN)
g3 = {row["event_id"]: row for row in read_csv(G3)}
unresolved = [row for row in ann if row["resolution_status"] == "excluded_fail_closed"]

archive_refs: dict[str, list[dict[str, str]]] = defaultdict(list)
unmapped = []
for row in unresolved:
    ev = g3.get(row["event_id"], {})
    ref = ev.get("source_reference", "")
    m = re.match(
        r"github:vgreg/hacked_earnings_jfe@(?P<commit>[0-9a-f]{40}):"
        r"Data/Press releases/(?P<year>\d{4})\.zip::(?P<member>.+)$",
        ref,
    )
    if not m:
        unmapped.append({
            "event_id": row["event_id"],
            "historical_symbol": row["historical_symbol"],
            "event_date": row["event_date"],
            "source_reference": ref,
        })
        continue
    item = dict(row)
    item.update(m.groupdict())
    item["evidence_excerpt"] = ev.get("evidence_excerpt", "")
    archive_refs[f'{m.group("commit")}:{m.group("year")}'].append(item)

results = []
archive_status = []
for archive_key, items in sorted(archive_refs.items()):
    commit, year = archive_key.split(":", 1)
    raw_path = f"Data/Press releases/{year}.zip"
    url = (
        f"https://raw.githubusercontent.com/vgreg/hacked_earnings_jfe/{commit}/"
        + urllib.parse.quote(raw_path, safe="/")
    )
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            zip_bytes = response.read()
        archive_sha = hashlib.sha256(zip_bytes).hexdigest()
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        names = zf.namelist()
        archive_status.append({
            "year": year,
            "commit": commit,
            "url": url,
            "sha256": archive_sha,
            "member_count": len(names),
            "status": "downloaded",
        })
    except Exception as exc:
        archive_status.append({
            "year": year,
            "commit": commit,
            "url": url,
            "status": "error",
            "error": repr(exc),
        })
        continue

    for item in items:
        member = item["member"]
        candidates = [n for n in names if n == member or n.endswith("/" + member) or n.endswith(member)]
        if len(candidates) != 1:
            results.append({
                "event_id": item["event_id"],
                "historical_symbol": item["historical_symbol"],
                "event_date": item["event_date"],
                "archive_year": year,
                "archive_member_requested": member,
                "status": "member_not_unique",
                "member_candidates": candidates[:20],
            })
            continue

        actual = candidates[0]
        info = zf.getinfo(actual)
        raw = zf.read(actual)
        text = normalize_text(raw)
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        time_lines = []
        source_lines = []
        call_lines = []
        for line in lines:
            if TIME_RE.search(line) or TZ_RE.search(line):
                time_lines.append(line[:1000])
            lower = line.lower()
            if any(term in lower for term in WIRE_TERMS):
                source_lines.append(line[:1000])
            if "conference call" in lower or "webcast" in lower or "earnings call" in lower:
                call_lines.append(line[:1000])

        all_times = []
        for line in time_lines:
            all_times.extend(m.group(0) for m in TIME_RE.finditer(line))
        urls = URL_RE.findall(text)

        results.append({
            "event_id": item["event_id"],
            "historical_symbol": item["historical_symbol"],
            "event_date": item["event_date"],
            "first_documented_illicit_trade_ts": item["first_documented_illicit_trade_ts"],
            "archive_year": year,
            "archive_commit": commit,
            "archive_member": actual,
            "archive_entry_mtime_not_release_evidence": "%04d-%02d-%02dT%02d:%02d:%02d" % info.date_time,
            "release_text_sha256": hashlib.sha256(raw).hexdigest(),
            "release_bytes": len(raw),
            "status": "scanned",
            "evidence_excerpt_from_g3": item["evidence_excerpt"],
            "text_prefix": text[:1800],
            "candidate_time_strings": sorted(set(all_times))[:50],
            "lines_with_time_or_timezone": time_lines[:40],
            "lines_with_wire_markers": source_lines[:20],
            "lines_with_conference_call_or_webcast": call_lines[:30],
            "urls_in_release": urls[:30],
            "has_non_call_time_line": any(
                ("conference call" not in line.lower() and "webcast" not in line.lower() and "earnings call" not in line.lower())
                for line in time_lines
            ),
            "time_line_count": len(time_lines),
            "call_line_count": len(call_lines),
        })

summary = {
    "schema_version": "1",
    "purpose": "Research-only bulk inspection of the original hacked-earnings replication press-release archive for embedded clock/source metadata. ZIP entry mtimes are explicitly non-admissible as release clocks.",
    "research_use_only": True,
    "unresolved_event_count": len(unresolved),
    "archive_mapped_event_count": sum(len(v) for v in archive_refs.values()),
    "unmapped_event_count": len(unmapped),
    "scanned_event_count": sum(1 for r in results if r.get("status") == "scanned"),
    "events_with_any_time_line": sum(1 for r in results if r.get("time_line_count", 0) > 0),
    "events_with_non_call_time_line": sum(1 for r in results if r.get("has_non_call_time_line")),
    "archives": archive_status,
    "unmapped": unmapped,
    "results": sorted(results, key=lambda r: (r.get("event_date", ""), r.get("historical_symbol", ""), r.get("event_id", ""))),
}

OUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps({k: summary[k] for k in (
    "unresolved_event_count",
    "archive_mapped_event_count",
    "unmapped_event_count",
    "scanned_event_count",
    "events_with_any_time_line",
    "events_with_non_call_time_line",
)}, indent=2))
