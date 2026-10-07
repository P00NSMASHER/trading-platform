from __future__ import annotations

import argparse
import csv
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "1"
NY = ZoneInfo("America/New_York")
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
ALLOWED_FORMS = {
    "10-K", "10-K/A", "10-Q", "10-Q/A",
    "20-F", "20-F/A", "40-F", "40-F/A",
}

_ACCEPTANCE_RE = re.compile(
    r"(?:<ACCEPTANCE-DATETIME>|ACCEPTANCE-DATETIME:\s*)(\d{14})",
    re.IGNORECASE,
)
_TRADING_SYMBOL_PATTERNS = (
    re.compile(
        r"<(?:dei:)?TradingSymbol(?:\s[^>]*)?>([^<]+)</(?:dei:)?TradingSymbol>",
        re.IGNORECASE,
    ),
    re.compile(
        r"Trading\s+Symbol(?:\(s\))?\s*[:|]\s*([A-Z][A-Z0-9.\-]{0,9})",
        re.IGNORECASE,
    ),
)


class G5HistoricalCikBracketError(ValueError):
    pass


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    return fields, rows


def _parse_date(value: str, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError as exc:
        raise G5HistoricalCikBracketError(
            f"{label} must be YYYY-MM-DD"
        ) from exc


def _parse_acceptance(text: str) -> datetime | None:
    match = _ACCEPTANCE_RE.search(text)
    if not match:
        return None
    return datetime.strptime(
        match.group(1), "%Y%m%d%H%M%S"
    ).replace(tzinfo=NY).astimezone(timezone.utc)


def _trading_symbols(text: str) -> set[str]:
    out = set()
    for pattern in _TRADING_SYMBOL_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(1).strip().upper()
            if value:
                out.add(value)
    return out


def _ticker_leads(payload: dict) -> dict[str, str]:
    out = {}
    for item in payload.values():
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        cik = str(item.get("cik_str") or "").strip()
        if not ticker or not cik.isdigit():
            continue
        normalized = cik.zfill(10)
        prior = out.get(ticker)
        if prior is not None and prior != normalized:
            raise G5HistoricalCikBracketError(
                f"current SEC ticker lead is ambiguous for {ticker}"
            )
        out[ticker] = normalized
    return out


def _recent_records(payload: dict) -> list[dict[str, str]]:
    raw = (payload.get("filings") or {}).get("recent") or {}
    accession = list(raw.get("accessionNumber") or [])
    filing_date = list(raw.get("filingDate") or [])
    form = list(raw.get("form") or [])
    n = min(len(accession), len(filing_date), len(form))
    return [
        {
            "accession": str(accession[i] or "").strip(),
            "filing_date": str(filing_date[i] or "").strip()[:10],
            "form": str(form[i] or "").strip().upper(),
        }
        for i in range(n)
        if str(accession[i] or "").strip()
    ]


def _additional_files(payload: dict) -> list[str]:
    return [
        str(item.get("name") or "").strip()
        for item in ((payload.get("filings") or {}).get("files") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]


def _filing_url(cik: str, accession: str) -> str:
    return (
        f"{SEC_ARCHIVES}/{int(cik)}/"
        f"{accession.replace('-', '')}/{accession}.txt"
    )


class HttpSecFetcher:
    def __init__(self, *, user_agent: str, min_interval_seconds: float = 0.12):
        self.user_agent = user_agent.strip()
        if not self.user_agent:
            raise G5HistoricalCikBracketError("SEC User-Agent required")
        self.min_interval_seconds = max(float(min_interval_seconds), 0.11)
        self._last = 0.0

    def _get(self, url: str) -> bytes:
        delay = self.min_interval_seconds - (time.monotonic() - self._last)
        if delay > 0:
            time.sleep(delay)
        request = Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "identity"},
        )
        with urlopen(request, timeout=30) as response:
            data = response.read()
        self._last = time.monotonic()
        return data

    def json(self, url: str) -> dict:
        return json.loads(self._get(url).decode("utf-8"))

    def text(self, url: str) -> str:
        return self._get(url).decode("utf-8", errors="replace")


def verify(
    *,
    acquisition_queue_path: Path,
    output_path: Path,
    fetch_json: Callable[[str], dict],
    fetch_text: Callable[[str], str],
    max_bracket_days: int = 400,
) -> dict:
    fields, queue = _read_csv(acquisition_queue_path)
    required = {"historical_symbol", "required_event_dates"}
    missing = required.difference(fields)
    if missing:
        raise G5HistoricalCikBracketError(
            f"acquisition queue missing columns: {sorted(missing)}"
        )

    leads = _ticker_leads(fetch_json(SEC_TICKERS_URL))
    submission_cache: dict[str, list[dict[str, str]]] = {}
    text_cache: dict[str, str] = {}
    verified = []
    gaps = []

    for row in queue:
        symbol = row["historical_symbol"].upper()
        event_dates = [
            _parse_date(value, label=f"{symbol} event date")
            for value in row["required_event_dates"].split(";")
            if value
        ]
        cik = leads.get(symbol, "")
        if not cik:
            gaps.append((symbol, "NO_CURRENT_SEC_CIK_LEAD"))
            continue

        if cik not in submission_cache:
            root = fetch_json(f"{SEC_SUBMISSIONS}/CIK{cik}.json")
            records = _recent_records(root)
            for name in _additional_files(root):
                records.extend(
                    _recent_records(fetch_json(f"{SEC_SUBMISSIONS}/{name}"))
                )
            submission_cache[cik] = [
                item
                for item in records
                if item["form"] in ALLOWED_FORMS and item["filing_date"]
            ]

        filings = submission_cache[cik]
        evidence_by_accession = {}
        for filing in filings:
            filing_date = _parse_date(
                filing["filing_date"], label=f"{symbol} filing_date"
            )
            if all(
                abs((filing_date - event_date).days) > max_bracket_days
                for event_date in event_dates
            ):
                continue
            accession = filing["accession"]
            if accession not in text_cache:
                text_cache[accession] = fetch_text(_filing_url(cik, accession))
            text = text_cache[accession]
            accepted = _parse_acceptance(text)
            symbols = _trading_symbols(text)
            if accepted is None or symbol not in symbols:
                continue
            evidence_by_accession[accession] = {
                "accepted": accepted,
                "url": _filing_url(cik, accession),
            }

        evidence = sorted(
            evidence_by_accession.values(),
            key=lambda item: item["accepted"],
        )
        brackets = []
        all_covered = True
        for event_date in event_dates:
            event_start = datetime.combine(
                event_date, datetime.min.time(), tzinfo=timezone.utc
            )
            before = [
                item for item in evidence
                if item["accepted"] < event_start
                and (event_start.date() - item["accepted"].date()).days
                <= max_bracket_days
            ]
            after = [
                item for item in evidence
                if item["accepted"].date() > event_date
                and (item["accepted"].date() - event_date).days
                <= max_bracket_days
            ]
            if not before or not after:
                all_covered = False
                break
            brackets.append((max(before, key=lambda x: x["accepted"]),
                             min(after, key=lambda x: x["accepted"])))

        if not all_covered:
            gaps.append((symbol, "NO_MATCHING_TRADING_SYMBOL_BRACKET"))
            continue

        valid_from = min(pair[0]["accepted"].date() for pair in brackets)
        valid_through = max(pair[1]["accepted"].date() for pair in brackets)
        source_urls = sorted(
            {
                item["url"]
                for pair in brackets
                for item in pair
            }
        )
        effective = max(pair[1]["accepted"] for pair in brackets)
        verified.append(
            {
                "historical_symbol": symbol,
                "cik": cik,
                "valid_from": valid_from.isoformat(),
                "valid_through": valid_through.isoformat(),
                "source_reference": ";".join(source_urls),
                "evidence_effective_at": effective.isoformat(
                    timespec="seconds"
                ).replace("+00:00", "Z"),
                "review_status": "EXPLICIT_HISTORICAL_CIK_VERIFIED",
                "research_use_only": "1",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "historical_symbol", "cik", "valid_from", "valid_through",
        "source_reference", "evidence_effective_at", "review_status",
        "research_use_only",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(verified, key=lambda row: row["historical_symbol"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "queue_symbol_count": len(queue),
        "verified_symbol_count": len(verified),
        "gap_symbol_count": len(gaps),
        "gap_reasons": {
            reason: sum(1 for _symbol, item_reason in gaps if item_reason == reason)
            for reason in sorted({reason for _symbol, reason in gaps})
        },
        "max_bracket_days": max_bracket_days,
        "policy": {
            "current_ticker_mapping_is_lead_only": True,
            "historical_trading_symbol_must_match_in_archival_filing": True,
            "every_required_event_date_must_be_bracketed": True,
            "same_cik_required_for_both_sides_of_bracket": True,
            "verification_changes_canonical_g5_readiness": False,
        },
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify historical CIK leads using bracketing SEC filings."
    )
    parser.add_argument("--acquisition-queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--user-agent", required=True)
    parser.add_argument("--max-bracket-days", type=int, default=400)
    args = parser.parse_args()
    fetcher = HttpSecFetcher(user_agent=args.user_agent)
    result = verify(
        acquisition_queue_path=args.acquisition_queue,
        output_path=args.output,
        fetch_json=fetcher.json,
        fetch_text=fetcher.text,
        max_bracket_days=args.max_bracket_days,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
