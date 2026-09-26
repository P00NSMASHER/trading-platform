from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

SOURCE_REPOSITORY = "vgreg/hacked_earnings_jfe"
SOURCE_REVISION = "c23c7d79d067a79d70cf20e31b072d3703497eae"
ARCHIVE_URL = (
    "https://raw.githubusercontent.com/vgreg/hacked_earnings_jfe/"
    + SOURCE_REVISION
    + "/Data/Press%20releases/{year}.zip"
)
YEARS = range(2011, 2016)
ENTRY_RE = re.compile(r"^(?P<permno>\d+)_(?P<date>\d{8})_(?P<suffix>.+)\.txt$", re.I)
VALID_EXCHANGES = {"XNYS", "XNAS", "XASE"}
OUTPUT_FIELDS = [
    "event_id", "historical_symbol", "effective_date", "primary_exchange",
    "evidence_kind", "evidence_date", "source_grade", "source_reference",
    "evidence_excerpt", "research_use_only",
]


class G3EvidenceError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def _decode(blob: bytes) -> str:
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return blob.decode(enc)
        except UnicodeDecodeError:
            pass
    return blob.decode("utf-8", errors="replace")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def classify_exchange(text: str, symbol: str) -> tuple[set[str], str]:
    t = _normalize(text)
    sym = re.escape(symbol.lower())
    rules = [
        ("XASE", rf"\b(?:nyse mkt|nyse american|amex)\s+{sym}\b"),
        (
            "XNAS",
            rf"\b(?:nasdaq(?: global select market| global select| global market| capital market| gs| gm| cm)?|"
            rf"the nasdaq global select market)\s+{sym}\b",
        ),
        ("XNYS", rf"\b(?:nyse|new york stock exchange)\s+{sym}\b"),
    ]
    found: set[str] = set()
    contexts: list[str] = []
    for exchange, pattern in rules:
        for m in re.finditer(pattern, t):
            found.add(exchange)
            contexts.append(t[max(0, m.start() - 100): min(len(t), m.end() + 120)])
    return found, (contexts[0] if contexts else "")


def _download(year: int) -> bytes:
    req = urllib.request.Request(
        ARCHIVE_URL.format(year=year),
        headers={"User-Agent": "trading-platform-g3-listing-evidence/1.0"},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return response.read()


def _load_supplement(path: Path) -> dict[str, dict[str, str]]:
    rows = _read_csv(path)
    out: dict[str, dict[str, str]] = {}
    for i, row in enumerate(rows, 2):
        eid = row.get("event_id", "")
        if not eid or eid in out:
            raise G3EvidenceError(f"supplement row {i}: event_id must be unique and nonblank")
        if row.get("primary_exchange") not in VALID_EXCHANGES:
            raise G3EvidenceError(f"supplement row {i}: invalid primary_exchange")
        if not row.get("source_reference"):
            raise G3EvidenceError(f"supplement row {i}: source_reference is required")
        out[eid] = row
    return out


def build(events_path: Path, supplement_path: Path, output_path: Path, report_path: Path) -> dict:
    events = _read_csv(events_path)
    supplement = _load_supplement(supplement_path)
    event_ids = {e.get("event_id", "") for e in events}
    extra = sorted(set(supplement) - event_ids)
    if extra:
        raise G3EvidenceError(f"supplement contains unknown event_ids: {extra[:5]}")

    archives: dict[int, bytes] = {}
    archive_receipts = []
    entries_by_permno: dict[str, list[dict]] = {}
    for year in YEARS:
        blob = _download(year)
        archives[year] = blob
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            archive_receipts.append({
                "year": year,
                "url": ARCHIVE_URL.format(year=year),
                "sha256": _sha256_bytes(blob),
                "byte_count": len(blob),
                "entry_count": len(zf.namelist()),
            })
            for name in zf.namelist():
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
                })

    zips = {year: zipfile.ZipFile(io.BytesIO(blob)) for year, blob in archives.items()}
    output: list[dict[str, str]] = []
    archive_resolved = 0
    supplement_resolved = 0
    supplement_corroborated = 0
    unresolved = []
    conflicts = []

    try:
        for e in events:
            eid = e["event_id"]
            symbol = e["historical_symbol"].upper()
            permno = str(e.get("permno", "")).strip()
            event_date = datetime.fromisoformat(e["first_documented_illicit_trade_ts"]).date()
            end = event_date + timedelta(days=3)
            found: dict[str, list[dict]] = {}

            for item in entries_by_permno.get(permno, []):
                if not (event_date <= item["release_date"] <= end):
                    continue
                text = _decode(zips[item["year"]].read(item["name"]))
                exchanges, excerpt = classify_exchange(text, symbol)
                for exchange in exchanges:
                    found.setdefault(exchange, []).append({
                        **item, "excerpt": excerpt,
                    })

            if len(found) > 1:
                conflicts.append({"event_id": eid, "symbol": symbol, "exchanges": sorted(found)})
                continue

            if len(found) == 1:
                exchange = next(iter(found))
                item = sorted(found[exchange], key=lambda x: (x["release_date"], x["name"]))[0]
                row = supplement.get(eid)
                if row is not None:
                    if row.get("historical_symbol", "").upper() != symbol:
                        raise G3EvidenceError(f"supplement symbol mismatch for {eid}")
                    if row.get("effective_date") != event_date.isoformat():
                        raise G3EvidenceError(f"supplement effective_date mismatch for {eid}")
                    if row.get("primary_exchange") != exchange:
                        conflicts.append({
                            "event_id": eid,
                            "symbol": symbol,
                            "archive_exchange": exchange,
                            "supplement_exchange": row.get("primary_exchange"),
                        })
                        continue
                    corroborated = {k: row.get(k, "") for k in OUTPUT_FIELDS}
                    corroborated["evidence_kind"] = (
                        (corroborated.get("evidence_kind") or "public_event_evidence")
                        + "+replication_archive_corroborated"
                    )
                    output.append(corroborated)
                    supplement_resolved += 1
                    supplement_corroborated += 1
                    continue

                output.append({
                    "event_id": eid,
                    "historical_symbol": symbol,
                    "effective_date": event_date.isoformat(),
                    "primary_exchange": exchange,
                    "evidence_kind": "replication_archive_press_release",
                    "evidence_date": item["release_date"].isoformat(),
                    "source_grade": "B",
                    "source_reference": (
                        f"github:{SOURCE_REPOSITORY}@{SOURCE_REVISION}:"
                        f"Data/Press releases/{item['year']}.zip::{item['name']}"
                    ),
                    "evidence_excerpt": item["excerpt"],
                    "research_use_only": "1",
                })
                archive_resolved += 1
                continue

            row = supplement.get(eid)
            if row is None:
                unresolved.append({"event_id": eid, "symbol": symbol})
                continue
            if row.get("historical_symbol", "").upper() != symbol:
                raise G3EvidenceError(f"supplement symbol mismatch for {eid}")
            if row.get("effective_date") != event_date.isoformat():
                raise G3EvidenceError(f"supplement effective_date mismatch for {eid}")
            output.append({k: row.get(k, "") for k in OUTPUT_FIELDS})
            supplement_resolved += 1
    finally:
        for zf in zips.values():
            zf.close()

    if conflicts or unresolved:
        raise G3EvidenceError(
            f"G3 evidence incomplete: conflicts={len(conflicts)} unresolved={len(unresolved)} "
            f"unresolved_preview={unresolved[:10]} conflict_preview={conflicts[:5]}"
        )
    if len(output) != len(events):
        raise G3EvidenceError(f"expected {len(events)} output rows, got {len(output)}")
    if len({r["event_id"] for r in output}) != len(output):
        raise G3EvidenceError("duplicate event_id in output")

    output.sort(key=lambda r: r["event_id"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        w.writeheader()
        w.writerows(output)

    counts = Counter(r["primary_exchange"] for r in output)
    report = {
        "schema_version": "1",
        "purpose": "Event-bound point-in-time primary-listing evidence for G3 historical surveillance reconstruction.",
        "research_use_only": True,
        "source_repository": SOURCE_REPOSITORY,
        "source_revision": SOURCE_REVISION,
        "events_path": str(events_path),
        "events_sha256": _sha256_file(events_path),
        "supplement_path": str(supplement_path),
        "supplement_sha256": _sha256_file(supplement_path),
        "output_path": str(output_path),
        "output_sha256": _sha256_file(output_path),
        "event_count": len(events),
        "resolved_count": len(output),
        "archive_resolved_count": archive_resolved,
        "supplement_resolved_count": supplement_resolved,
        "supplement_corroborated_count": supplement_corroborated,
        "unresolved_count": 0,
        "conflict_count": 0,
        "exchange_counts": dict(sorted(counts.items())),
        "archive_receipts": archive_receipts,
        "g3_ready": len(output) == len(events),
        "prohibited_outputs": [
            "BUY", "SELL", "expected_return", "target_price",
            "position_size", "order", "execution_instruction",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Build public point-in-time listing evidence for G3.")
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--supplement", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(build(args.events, args.supplement, args.output, args.report), indent=2))


if __name__ == "__main__":
    main()
