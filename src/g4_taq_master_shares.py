from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CIK_MAP = ROOT / "data/public/metadata/g4_historical_cik_map.csv"

SPEC_URL = (
    "https://www.nyse.com/publicdocs/nyse/data/Daily_TAQ_Client_Spec_v2.1.pdf"
)
MASTER_PREFIX = "EQY_US_ALL_REF_MASTER_"
NYSE_SOURCE_LISTED_EXCHANGE = "00"

# Historical Daily TAQ fixed-width Master layout (v1.9/v2.1).
SOURCE_LISTED_EXCHANGE_OFFSET = 156
SOURCE_LISTED_EXCHANGE_SIZE = 2
SYMBOL_OFFSET = 160
SYMBOL_SIZE = 10
SHARES_OUTSTANDING_OFFSET = 177
SHARES_OUTSTANDING_SIZE = 10
MIN_RECORD_SIZE = SHARES_OUTSTANDING_OFFSET + SHARES_OUTSTANDING_SIZE

ANCHOR_FIELDS = [
    "historical_symbol",
    "cik",
    "fact_date",
    "shares_outstanding",
    "filed_date",
    "form",
    "accession",
    "source_tag",
    "source_reference",
    "source_grade",
    "max_staleness_days",
    "staleness_exception_reason",
    "notes",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def infer_master_date(path: Path) -> date:
    match = re.search(r"EQY_US_ALL_REF_MASTER_(\d{8})", path.name)
    if not match:
        raise ValueError(
            f"{path}: filename must contain EQY_US_ALL_REF_MASTER_YYYYMMDD"
        )
    return date.fromisoformat(
        f"{match.group(1)[0:4]}-{match.group(1)[4:6]}-{match.group(1)[6:8]}"
    )


def parse_master_record(line: str) -> dict[str, object] | None:
    raw = line.rstrip("\r\n")
    if len(raw) < MIN_RECORD_SIZE:
        return None

    exchange = raw[
        SOURCE_LISTED_EXCHANGE_OFFSET:
        SOURCE_LISTED_EXCHANGE_OFFSET + SOURCE_LISTED_EXCHANGE_SIZE
    ].strip()
    symbol = raw[SYMBOL_OFFSET:SYMBOL_OFFSET + SYMBOL_SIZE].strip()
    shares_raw = raw[
        SHARES_OUTSTANDING_OFFSET:
        SHARES_OUTSTANDING_OFFSET + SHARES_OUTSTANDING_SIZE
    ].strip()

    # The historical specification explicitly limits this field to NYSE-listed issues.
    if exchange != NYSE_SOURCE_LISTED_EXCHANGE or not symbol:
        return None
    if not shares_raw:
        return None
    if not shares_raw.isdigit():
        raise ValueError(
            f"NYSE master row for {symbol!r} has non-integer Shares Outstanding "
            f"value {shares_raw!r}"
        )
    shares = int(shares_raw)
    if shares <= 0:
        raise ValueError(
            f"NYSE master row for {symbol!r} has non-positive Shares Outstanding"
        )
    return {
        "historical_symbol": symbol.upper(),
        "shares_outstanding": shares,
        "source_listed_exchange": exchange,
    }


def _decode_lines(payload: bytes) -> Iterable[str]:
    # Historical TAQ Master is documented as ASCII.
    return io.StringIO(payload.decode("ascii", errors="strict"))


def read_master_lines(path: Path) -> Iterable[str]:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [
                info for info in archive.infolist()
                if not info.is_dir() and not info.filename.startswith("__MACOSX/")
            ]
            if len(members) != 1:
                raise ValueError(
                    f"{path}: expected exactly one data member, found {len(members)}"
                )
            with archive.open(members[0]) as handle:
                payload = handle.read()
        yield from _decode_lines(payload)
        return

    if suffix == ".gz":
        with gzip.open(path, "rt", encoding="ascii", errors="strict") as handle:
            yield from handle
        return

    with path.open("rt", encoding="ascii", errors="strict") as handle:
        yield from handle


def read_cik_map(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or {"historical_symbol", "cik"} - set(rows[0]):
        raise ValueError(f"{path}: invalid G4 CIK map")
    result: dict[str, str] = {}
    for row in rows:
        symbol = (row["historical_symbol"] or "").strip().upper()
        cik = (row["cik"] or "").strip()
        if symbol and cik:
            result[symbol] = cik
    return result


def official_archive_path(master_date: date) -> str:
    compact = master_date.strftime("%Y%m%d")
    year = master_date.strftime("%Y")
    month = master_date.strftime("%Y%m")
    filename = f"{MASTER_PREFIX}{compact}.zip"
    return (
        "/EQY_US_ALL_REF_MASTER/"
        f"EQY_US_ALL_REF_MASTER_{year}/"
        f"EQY_US_ALL_REF_MASTER_{month}/"
        f"{filename}"
    )


def extract_anchors(
    paths: list[Path],
    *,
    symbols: set[str],
    cik_map: dict[str, str],
) -> list[dict[str, str]]:
    wanted = {symbol.strip().upper() for symbol in symbols if symbol.strip()}
    if not wanted:
        raise ValueError("at least one target symbol is required")

    missing_cik = sorted(wanted - set(cik_map))
    if missing_cik:
        raise ValueError(f"missing CIK mapping for symbols: {missing_cik}")

    anchors: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for path in sorted(paths, key=lambda p: str(p)):
        master_date = infer_master_date(path)
        date_text = master_date.isoformat()
        file_sha = sha256_file(path)
        found: dict[str, int] = {}

        for line in read_master_lines(path):
            row = parse_master_record(line)
            if row is None:
                continue
            symbol = str(row["historical_symbol"])
            if symbol not in wanted:
                continue
            shares = int(row["shares_outstanding"])
            if symbol in found and found[symbol] != shares:
                raise ValueError(
                    f"{path}: conflicting Shares Outstanding rows for {symbol}"
                )
            found[symbol] = shares

        for symbol, shares in sorted(found.items()):
            key = (symbol, date_text)
            if key in seen:
                raise ValueError(f"duplicate master anchor for {symbol} {date_text}")
            seen.add(key)
            archive_path = official_archive_path(master_date)
            anchors.append(
                {
                    "historical_symbol": symbol,
                    "cik": cik_map[symbol],
                    "fact_date": date_text,
                    "shares_outstanding": str(shares),
                    # G4 materializer treats filed_date conservatively as available
                    # only at end-of-day, preventing same-day look-ahead.
                    "filed_date": date_text,
                    "form": "NYSE Daily TAQ Master",
                    "accession": path.name,
                    "source_tag": "nyse_daily_taq_master:shares_outstanding",
                    "source_reference": f"sftp.nyse.com:{archive_path}",
                    "source_grade": "A",
                    "max_staleness_days": "",
                    "staleness_exception_reason": "",
                    "notes": (
                        f"Official NYSE Daily TAQ fixed-width Master; file_sha256={file_sha}; "
                        f"historical spec={SPEC_URL}; Shares Outstanding field is NYSE-only."
                    ),
                }
            )
    return anchors


def write_anchors(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANCHOR_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Extract exact NYSE-listed shares-outstanding anchors from licensed "
            "historical Daily TAQ Master files. No network access is performed."
        )
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--symbol", action="append", required=True)
    parser.add_argument("--cik-map", type=Path, default=DEFAULT_CIK_MAP)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = extract_anchors(
        args.input,
        symbols=set(args.symbol),
        cik_map=read_cik_map(args.cik_map),
    )
    write_anchors(rows, args.output)
    print(
        json.dumps(
            {
                "anchors_written": len(rows),
                "symbols": sorted({row["historical_symbol"] for row in rows}),
                "output": str(args.output),
                "coverage_claimed": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
