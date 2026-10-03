from __future__ import annotations

import csv
import gzip
import hashlib
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

import pandas as pd

RAW_QUOTE_COLUMNS = [
    "#RIC",
    "Date[G]",
    "Time[G]",
    "GMT Offset",
    "Type",
    "Buyer ID",
    "Bid Price",
    "Bid Size",
    "Seller ID",
    "Ask Price",
    "Ask Size",
    "Qualifiers",
    "Quote Time",
]

RAW_TRADE_COLUMNS = [
    "#RIC",
    "Date[G]",
    "Time[G]",
    "GMT Offset",
    "Type",
    "Ex/Cntrb.ID",
    "Price",
    "Volume",
    "Market VWAP",
    "Qualifiers",
    "Seq. No.",
    "Exch Time",
    "Trd/Qte Date",
]


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_md5_sidecar(path: Path) -> dict[str, str]:
    """
    Reproduce the original research integrity gate.

    The companion TRTH scripts calculate MD5 for each gzipped TAS data part and
    compare it to the first 32 characters of the sibling '<file>.md5sum'.
    """
    sidecar = Path(str(path) + ".md5sum")
    if not sidecar.exists():
        raise FileNotFoundError(f"missing TRTH checksum sidecar: {sidecar.name}")
    expected = sidecar.read_text(encoding="utf-8", errors="replace")[:32].lower()
    if len(expected) != 32:
        raise ValueError(f"{sidecar.name}: invalid MD5 sidecar")
    actual = md5_file(path)
    if actual.lower() != expected:
        raise ValueError(
            f"{path.name}: MD5 mismatch expected={expected} actual={actual}"
        )
    return {
        "data_file": path.name,
        "sidecar_file": sidecar.name,
        "md5": actual,
    }


def tas_filename_date(path: Path | str) -> date:
    """
    Parse the original fixed-position TRTH TAS filename convention.

    Research code used:
      filename[4:14]  -> YYYY-MM-DD
      filename[15:23] -> 'TAS-Data'
    """
    name = Path(path).name
    if len(name) < 23 or name[15:23] != "TAS-Data" or not name.endswith(".gz"):
        raise ValueError(f"not an original-layout TAS data filename: {name}")
    try:
        return date.fromisoformat(name[4:14])
    except ValueError as exc:
        raise ValueError(f"{name}: invalid TAS date slice {name[4:14]!r}") from exc


def discover_tas_parts(month_dir: Path) -> dict[date, list[Path]]:
    """
    Discover and group original-layout gzipped TAS data parts by UTC file date.
    """
    root = month_dir.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"TRTH TAS directory does not exist: {root}")

    grouped: dict[date, list[Path]] = defaultdict(list)
    for path in sorted(root.iterdir(), key=lambda p: p.name):
        if not path.is_file() or not path.name.endswith(".gz"):
            continue
        try:
            trade_date = tas_filename_date(path)
        except ValueError:
            continue
        grouped[trade_date].append(path)
    return dict(sorted(grouped.items()))


def _kind_columns(kind: str) -> tuple[str, list[str]]:
    normalized = str(kind).strip().lower()
    if normalized == "trade":
        return "Trade", list(RAW_TRADE_COLUMNS)
    if normalized == "quote":
        return "Quote", list(RAW_QUOTE_COLUMNS)
    raise ValueError("kind must be 'trade' or 'quote'")


def iter_tas_rows(
    paths: Sequence[Path],
    *,
    kind: str,
    allowed_rics: Iterable[str] | None = None,
    chunksize: int = 1_000_000,
) -> Iterator[dict[str, object]]:
    """
    Verify each raw TAS part before reading, then emit only the requested row type.

    This keeps the exact raw fields required by the original TRTH normalizer.
    No credentials or network activity are involved.
    """
    if chunksize <= 0:
        raise ValueError("chunksize must be positive")
    type_value, columns = _kind_columns(kind)
    allowed = None if allowed_rics is None else {str(x) for x in allowed_rics}

    for path in paths:
        verify_md5_sidecar(path)
        for chunk in pd.read_csv(
            path,
            compression="gzip",
            chunksize=chunksize,
            usecols=columns,
        ):
            selected = chunk[chunk["Type"] == type_value]
            if allowed is not None:
                selected = selected[selected["#RIC"].astype(str).isin(allowed)]
            for row in selected.to_dict(orient="records"):
                yield row


def load_tas_day(
    month_dir: Path,
    target_date: date,
    *,
    kind: str,
    allowed_rics: Iterable[str] | None = None,
    chunksize: int = 1_000_000,
) -> dict[str, object]:
    """
    Load one original TRTH TAS partition date after checksum validation.

    Returns raw rows plus a deterministic receipt. Date realignment to the U.S.
    Eastern calendar remains a downstream responsibility because the original
    research performed that after trade timestamp classification.
    """
    grouped = discover_tas_parts(month_dir)
    parts = list(grouped.get(target_date, []))
    rows = list(
        iter_tas_rows(
            parts,
            kind=kind,
            allowed_rics=allowed_rics,
            chunksize=chunksize,
        )
    )
    return {
        "schema_version": "1",
        "partition_date": target_date.isoformat(),
        "kind": str(kind).strip().lower(),
        "part_count": len(parts),
        "parts": [path.name for path in parts],
        "row_count": len(rows),
        "rows": rows,
        "coverage_claim": False,
    }
