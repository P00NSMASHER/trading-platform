from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen


SCHEMA_VERSION = "1"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
ALLOWED_FORMS = {
    "10-K",
    "10-K/A",
    "10-Q",
    "10-Q/A",
    "8-K",
    "8-K/A",
    "20-F",
    "20-F/A",
    "40-F",
    "40-F/A",
    "6-K",
    "6-K/A",
}

OUTPUT_FIELDS = [
    "event_date",
    "symbol",
    "effective_ts_utc",
    "sector",
    "sic_code",
    "cik",
    "accession_number",
    "filing_form",
    "source_reference",
    "research_use_only",
]

UNRESOLVED_FIELDS = [
    "event_date",
    "symbol",
    "reason",
    "cik",
    "research_use_only",
]


class G5SecClassificationError(ValueError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    return fields, rows


def _normalize_cik(value: str) -> str:
    raw = str(value or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    if not raw.isdigit():
        raise G5SecClassificationError(f"invalid CIK {value!r}")
    return raw.zfill(10)


def _parse_date(value: str, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError as exc:
        raise G5SecClassificationError(
            f"{label} must be a valid YYYY-MM-DD date"
        ) from exc


def _parse_aware(value: str, *, label: str) -> datetime:
    raw = str(value or "").strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G5SecClassificationError(
            f"{label} must be a valid ISO timestamp"
        ) from exc
    if dt.tzinfo is None:
        raise G5SecClassificationError(f"{label} must include timezone")
    return dt.astimezone(timezone.utc)


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _load_targets(path: Path) -> list[dict[str, object]]:
    fields, rows = _read_csv(path)
    required = {
        "event_date",
        "candidate_symbol",
        "latest_acceptable_effective_ts_utc",
    }
    missing = required.difference(fields)
    if missing:
        raise G5SecClassificationError(
            f"target file missing columns: {sorted(missing)}"
        )
    if not rows:
        raise G5SecClassificationError("target file is empty")

    out = []
    seen = set()
    for row_no, row in enumerate(rows, 2):
        event_date = _parse_date(
            row["event_date"],
            label=f"target row {row_no} event_date",
        )
        symbol = row["candidate_symbol"].upper()
        cutoff = _parse_aware(
            row["latest_acceptable_effective_ts_utc"],
            label=f"target row {row_no} cutoff",
        )
        if not symbol:
            raise G5SecClassificationError(
                f"target row {row_no}: candidate_symbol required"
            )
        key = (event_date.isoformat(), symbol)
        if key in seen:
            raise G5SecClassificationError(
                f"duplicate target {event_date.isoformat()}|{symbol}"
            )
        seen.add(key)
        out.append(
            {
                "event_date": event_date,
                "symbol": symbol,
                "cutoff": cutoff,
            }
        )
    return out


def _load_cik_map(path: Path) -> dict[str, list[dict[str, object]]]:
    fields, rows = _read_csv(path)
    required = {"historical_symbol", "cik"}
    missing = required.difference(fields)
    if missing:
        raise G5SecClassificationError(
            f"CIK map missing columns: {sorted(missing)}"
        )

    out: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        if not symbol:
            raise G5SecClassificationError(
                f"CIK map row {row_no}: historical_symbol required"
            )
        valid_from = (
            _parse_date(row["valid_from"], label=f"CIK map row {row_no} valid_from")
            if row.get("valid_from")
            else None
        )
        valid_through = (
            _parse_date(
                row["valid_through"],
                label=f"CIK map row {row_no} valid_through",
            )
            if row.get("valid_through")
            else None
        )
        if valid_from and valid_through and valid_through < valid_from:
            raise G5SecClassificationError(
                f"CIK map row {row_no}: valid_through precedes valid_from"
            )
        out[symbol].append(
            {
                "cik": _normalize_cik(row["cik"]),
                "valid_from": valid_from,
                "valid_through": valid_through,
            }
        )
    return out


def _resolve_cik(
    mappings: dict[str, list[dict[str, object]]],
    *,
    symbol: str,
    event_date: date,
) -> str:
    matches = []
    for row in mappings.get(symbol, []):
        valid_from = row["valid_from"]
        valid_through = row["valid_through"]
        if valid_from is not None and event_date < valid_from:
            continue
        if valid_through is not None and event_date > valid_through:
            continue
        matches.append(str(row["cik"]))
    matches = sorted(set(matches))
    if len(matches) > 1:
        raise G5SecClassificationError(
            f"multiple CIK mappings apply to {symbol}|{event_date}: {matches}"
        )
    return matches[0] if matches else ""


def _recent_records(payload: dict) -> list[dict[str, str]]:
    if "filings" in payload:
        raw = (payload.get("filings") or {}).get("recent") or {}
    else:
        raw = payload
    if not isinstance(raw, dict):
        return []
    accession = list(raw.get("accessionNumber") or [])
    filing_date = list(raw.get("filingDate") or [])
    form = list(raw.get("form") or [])
    n = min(len(accession), len(filing_date), len(form))
    return [
        {
            "accession_number": str(accession[i] or "").strip(),
            "filing_date": str(filing_date[i] or "").strip()[:10],
            "form": str(form[i] or "").strip().upper(),
        }
        for i in range(n)
        if str(accession[i] or "").strip()
    ]


def _additional_files(payload: dict) -> list[str]:
    filings = payload.get("filings") or {}
    files = filings.get("files") or []
    out = []
    for item in files:
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            out.append(str(item["name"]).strip())
    return out


def _filing_text_url(cik: str, accession: str) -> str:
    cik_dir = str(int(cik))
    return (
        f"{SEC_ARCHIVES}/{cik_dir}/"
        f"{accession.replace('-', '')}/{accession}.txt"
    )


_ACCEPTANCE_RE = re.compile(
    r"(?:<ACCEPTANCE-DATETIME>|ACCEPTANCE-DATETIME:\s*)(\d{14})",
    re.IGNORECASE,
)
_SIC_RE = re.compile(
    r"STANDARD INDUSTRIAL CLASSIFICATION:\s*[^\r\n]*?\[(\d{3,4})\]",
    re.IGNORECASE,
)


def _parse_acceptance(text: str) -> datetime | None:
    match = _ACCEPTANCE_RE.search(text)
    if not match:
        return None
    return datetime.strptime(
        match.group(1), "%Y%m%d%H%M%S"
    ).replace(tzinfo=SEC_TIMEZONE).astimezone(timezone.utc)


def _parse_sic(text: str) -> str:
    match = _SIC_RE.search(text)
    return match.group(1).zfill(4) if match else ""


def _sic_division(code: str) -> str:
    try:
        value = int(code)
    except ValueError as exc:
        raise G5SecClassificationError(f"invalid SIC code {code!r}") from exc
    if 100 <= value <= 999:
        division = "A"
    elif 1000 <= value <= 1499:
        division = "B"
    elif 1500 <= value <= 1799:
        division = "C"
    elif 2000 <= value <= 3999:
        division = "D"
    elif 4000 <= value <= 4999:
        division = "E"
    elif 5000 <= value <= 5199:
        division = "F"
    elif 5200 <= value <= 5999:
        division = "G"
    elif 6000 <= value <= 6799:
        division = "H"
    elif 7000 <= value <= 8999:
        division = "I"
    elif 9100 <= value <= 9729:
        division = "J"
    else:
        division = "UNCLASSIFIED"
    return f"SEC_SIC_DIVISION_{division}"


class HttpSecFetcher:
    def __init__(self, *, user_agent: str, min_interval_seconds: float = 0.12):
        self.user_agent = user_agent.strip()
        if not self.user_agent:
            raise G5SecClassificationError("SEC User-Agent must be nonblank")
        self.min_interval_seconds = max(float(min_interval_seconds), 0.11)
        self._last_request = 0.0

    def _get(self, url: str) -> bytes:
        delay = self.min_interval_seconds - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        req = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "identity",
            },
        )
        with urlopen(req, timeout=30) as response:
            payload = response.read()
        self._last_request = time.monotonic()
        return payload

    def json(self, url: str) -> dict:
        return json.loads(self._get(url).decode("utf-8"))

    def text(self, url: str) -> str:
        return self._get(url).decode("utf-8", errors="replace")


def build(
    *,
    targets_path: Path,
    cik_map_path: Path,
    output_dir: Path,
    fetch_json: Callable[[str], dict],
    fetch_text: Callable[[str], str],
) -> dict:
    targets = _load_targets(targets_path)
    mappings = _load_cik_map(cik_map_path)

    filings_cache: dict[str, list[dict[str, str]]] = {}
    text_cache: dict[str, str] = {}
    rows: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    used_accessions: set[str] = set()

    for target in sorted(
        targets,
        key=lambda row: (
            str(row["event_date"]),
            str(row["symbol"]),
        ),
    ):
        event_date = target["event_date"]
        symbol = str(target["symbol"])
        cutoff = target["cutoff"]
        assert isinstance(event_date, date)
        assert isinstance(cutoff, datetime)

        cik = _resolve_cik(
            mappings,
            symbol=symbol,
            event_date=event_date,
        )
        if not cik:
            unresolved.append(
                {
                    "event_date": event_date.isoformat(),
                    "symbol": symbol,
                    "reason": "NO_EXPLICIT_HISTORICAL_CIK_MAPPING",
                    "cik": "",
                    "research_use_only": "1",
                }
            )
            continue

        if cik not in filings_cache:
            root_url = f"{SEC_SUBMISSIONS}/CIK{cik}.json"
            root = fetch_json(root_url)
            records = _recent_records(root)
            for name in _additional_files(root):
                extra = fetch_json(f"{SEC_SUBMISSIONS}/{name}")
                records.extend(_recent_records(extra))
            unique = {
                (
                    row["accession_number"],
                    row["filing_date"],
                    row["form"],
                ): row
                for row in records
            }
            filings_cache[cik] = list(unique.values())

        candidates = [
            row
            for row in filings_cache[cik]
            if row["form"] in ALLOWED_FORMS
            and row["filing_date"]
            and row["filing_date"] <= event_date.isoformat()
        ]
        candidates.sort(
            key=lambda row: (
                row["filing_date"],
                row["accession_number"],
            ),
            reverse=True,
        )

        selected = None
        for filing in candidates:
            accession = filing["accession_number"]
            url = _filing_text_url(cik, accession)
            if accession not in text_cache:
                text_cache[accession] = fetch_text(url)
            filing_text = text_cache[accession]
            accepted = _parse_acceptance(filing_text)
            if accepted is None or accepted > cutoff:
                continue
            sic = _parse_sic(filing_text)
            if not sic:
                continue
            selected = (filing, url, accepted, sic)
            break

        if selected is None:
            unresolved.append(
                {
                    "event_date": event_date.isoformat(),
                    "symbol": symbol,
                    "reason": "NO_PRE_CUTOFF_FILING_WITH_SIC",
                    "cik": cik,
                    "research_use_only": "1",
                }
            )
            continue

        filing, url, accepted, sic = selected
        used_accessions.add(filing["accession_number"])
        rows.append(
            {
                "event_date": event_date.isoformat(),
                "symbol": symbol,
                "effective_ts_utc": _fmt_utc(accepted),
                "sector": _sic_division(sic),
                "sic_code": sic,
                "cik": cik,
                "accession_number": filing["accession_number"],
                "filing_form": filing["form"],
                "source_reference": url,
                "research_use_only": "1",
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = output_dir / "g5_sec_sic_classification_source.csv"
    unresolved_path = output_dir / "g5_sec_sic_classification_unresolved.csv"

    with source_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    with unresolved_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=UNRESOLVED_FIELDS)
        writer.writeheader()
        writer.writerows(unresolved)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Acquire public point-in-time SEC SIC classification for G5 targets "
            "using only explicit historical symbol-to-CIK mappings and archival "
            "filings accepted no later than each target cutoff."
        ),
        "research_use_only": True,
        "target_count": len(targets),
        "resolved_sector_target_count": len(rows),
        "unresolved_target_count": len(unresolved),
        "unique_cik_count": len(filings_cache),
        "unique_filing_accession_count": len(used_accessions),
        "inputs": {
            "targets": {
                "path": str(targets_path),
                "sha256": _sha256(targets_path),
            },
            "historical_cik_map": {
                "path": str(cik_map_path),
                "sha256": _sha256(cik_map_path),
            },
        },
        "outputs": {
            "classification_source": str(source_path),
            "unresolved": str(unresolved_path),
        },
        "policy": {
            "current_ticker_to_cik_inference_allowed": False,
            "explicit_historical_cik_mapping_required": True,
            "filing_acceptance_must_not_exceed_target_cutoff": True,
            "historical_sic_is_parsed_from_archival_filing_text": True,
            "sector_encoding": "SEC_SIC_DIVISION_NAMESPACED",
            "index_bucket_populated": False,
            "source_rows_are_canonical_g5_readiness": False,
            "purchase_performed": False,
        },
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_sec_sic_classification_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire public SEC SIC classification for G5 targets."
    )
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--historical-cik-map", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--user-agent",
        required=True,
        help="Declared SEC User-Agent, including contact information.",
    )
    args = parser.parse_args()

    fetcher = HttpSecFetcher(user_agent=args.user_agent)
    result = build(
        targets_path=args.targets,
        cik_map_path=args.historical_cik_map,
        output_dir=args.output_dir,
        fetch_json=fetcher.json,
        fetch_text=fetcher.text,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
