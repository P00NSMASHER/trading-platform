from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Mapping

OPTION_TRADE_FIELDS = [
    "timestamp",
    "symbol",
    "underlying_symbol",
    "option_symbol",
    "expiration",
    "strike",
    "option_type",
    "price",
    "size",
    "exchange",
    "conditions",
]
OPTION_QUOTE_FIELDS = [
    "timestamp",
    "symbol",
    "underlying_symbol",
    "option_symbol",
    "expiration",
    "strike",
    "option_type",
    "bid",
    "ask",
    "bid_size",
    "ask_size",
    "exchange",
    "conditions",
]

_DX_OPTION_RE = re.compile(
    r"^\.(?P<root>[A-Z0-9.]+)(?P<expiry>\d{6})(?P<option_type>[CP])"
    r"(?P<strike>\d+(?:\.\d+)?)$"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_text(path: Path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def read_rows(path: Path) -> list[dict[str, str]]:
    with _open_text(path) as handle:
        reader = csv.DictReader(
            (line for line in handle if line.strip() and not line.startswith("#="))
        )
        return list(reader)


def _parse_dxfeed_csv(path: Path) -> list[dict[str, str]]:
    """Read native dxFeed CSV, whose header begins with '#=EventType,'."""
    with _open_text(path) as handle:
        lines = [line for line in handle if line.strip()]
    if not lines:
        raise ValueError("dxFeed input is empty")

    header = lines[0].rstrip("\r\n")
    if not header.startswith("#="):
        raise ValueError("dxFeed input is missing #= event header")

    fieldnames = header[2:].split(",")
    if not fieldnames or fieldnames[0] not in {"Quote", "Trade", "TimeAndSale"}:
        raise ValueError("unsupported dxFeed event header")

    reader = csv.DictReader(lines[1:], fieldnames=fieldnames)
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = dict(raw)
        event_label = str(row.get(fieldnames[0]) or "").strip()
        # Some TimeAndSale exports use TimeAndSale&C style action records.
        # Keep plain TimeAndSale events and reject mutation/correction markers.
        if fieldnames[0] == "TimeAndSale" and event_label != "TimeAndSale":
            continue
        rows.append(row)
    return rows


def parse_option_symbol(event_symbol: object) -> dict[str, str]:
    value = str(event_symbol or "").strip().upper()
    match = _DX_OPTION_RE.fullmatch(value)
    if not match:
        raise ValueError(f"unsupported dxFeed option symbol {value!r}")

    expiry_raw = match.group("expiry")
    expiry = datetime.strptime(expiry_raw, "%y%m%d").date().isoformat()
    strike = match.group("strike").lstrip("0") or "0"
    if strike.startswith("."):
        strike = "0" + strike

    return {
        "underlying_symbol": match.group("root"),
        "option_symbol": value,
        "expiration": expiry,
        "strike": strike,
        "option_type": match.group("option_type"),
    }


def parse_event_time(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("blank dxFeed EventTime")
    for fmt in ("%Y%m%d-%H%M%S.%f%z", "%Y%m%d-%H%M%S%z"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.isoformat(timespec="milliseconds")
        except ValueError:
            continue
    raise ValueError(f"unsupported dxFeed EventTime {raw!r}")


def _number(value: object, *, field: str, positive: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"blank {field}")
    try:
        parsed = float(raw)
    except ValueError as exc:
        raise ValueError(f"invalid {field}={raw!r}") from exc
    if parsed < 0 or (positive and parsed <= 0):
        raise ValueError(f"invalid {field}={raw!r}")
    return raw


def _size(value: object, *, field: str, positive: bool = False) -> str:
    raw = _number(value, field=field, positive=positive)
    parsed = float(raw)
    if not parsed.is_integer():
        raise ValueError(f"non-integral {field}={raw!r}")
    return str(int(parsed))


def _assert_scope(
    metadata: Mapping[str, str],
    *,
    timestamp: str,
    trade_date: str,
    allowed_underlyings: set[str],
) -> None:
    observed_date = datetime.fromisoformat(timestamp).date().isoformat()
    if observed_date != trade_date:
        raise ValueError(
            f"wrong dxFeed event date {observed_date}; expected {trade_date}"
        )
    if metadata["underlying_symbol"] not in allowed_underlyings:
        raise ValueError(
            f"unexpected dxFeed underlying {metadata['underlying_symbol']}"
        )


def adapt_trade_row(
    row: Mapping[str, object],
    *,
    trade_date: str,
    allowed_underlyings: set[str],
) -> dict[str, str]:
    metadata = parse_option_symbol(row.get("EventSymbol"))
    timestamp = parse_event_time(row.get("EventTime"))
    _assert_scope(
        metadata,
        timestamp=timestamp,
        trade_date=trade_date,
        allowed_underlyings=allowed_underlyings,
    )

    price = _number(row.get("Price"), field="Price", positive=True)
    size = _size(row.get("Size"), field="Size", positive=True)
    exchange = str(row.get("ExchangeCode") or "").strip().upper()
    conditions = str(
        row.get("SaleConditions")
        or row.get("Flags")
        or ""
    ).strip()

    return {
        "timestamp": timestamp,
        "symbol": metadata["option_symbol"],
        "underlying_symbol": metadata["underlying_symbol"],
        "option_symbol": metadata["option_symbol"],
        "expiration": metadata["expiration"],
        "strike": metadata["strike"],
        "option_type": metadata["option_type"],
        "price": price,
        "size": size,
        "exchange": exchange,
        "conditions": conditions,
    }


def adapt_quote_row(
    row: Mapping[str, object],
    *,
    trade_date: str,
    allowed_underlyings: set[str],
) -> dict[str, str]:
    metadata = parse_option_symbol(row.get("EventSymbol"))
    timestamp = parse_event_time(row.get("EventTime"))
    _assert_scope(
        metadata,
        timestamp=timestamp,
        trade_date=trade_date,
        allowed_underlyings=allowed_underlyings,
    )

    bid = _number(row.get("BidPrice"), field="BidPrice", positive=True)
    ask = _number(row.get("AskPrice"), field="AskPrice", positive=True)
    bid_size = _size(row.get("BidSize"), field="BidSize", positive=True)
    ask_size = _size(row.get("AskSize"), field="AskSize", positive=True)

    if float(bid) > float(ask):
        raise ValueError("crossed dxFeed quote")

    bid_exchange = str(row.get("BidExchangeCode") or "").strip().upper()
    ask_exchange = str(row.get("AskExchangeCode") or "").strip().upper()
    exchange = (
        bid_exchange
        if bid_exchange == ask_exchange
        else f"{bid_exchange}/{ask_exchange}".strip("/")
    )

    return {
        "timestamp": timestamp,
        "symbol": metadata["option_symbol"],
        "underlying_symbol": metadata["underlying_symbol"],
        "option_symbol": metadata["option_symbol"],
        "expiration": metadata["expiration"],
        "strike": metadata["strike"],
        "option_type": metadata["option_type"],
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "exchange": exchange,
        "conditions": "",
    }


def adapt_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    event_kind: str,
    trade_date: str,
    allowed_underlyings: set[str],
) -> dict[str, object]:
    if event_kind not in {"Trade", "TimeAndSale", "Quote"}:
        raise ValueError("event_kind must be Trade, TimeAndSale, or Quote")
    if not allowed_underlyings:
        raise ValueError("allowed_underlyings must be non-empty")
    date.fromisoformat(trade_date)

    trades: list[dict[str, str]] = []
    quotes: list[dict[str, str]] = []
    rejected = Counter()

    for raw in rows:
        row = dict(raw)
        try:
            if event_kind == "Quote":
                quotes.append(
                    adapt_quote_row(
                        row,
                        trade_date=trade_date,
                        allowed_underlyings=allowed_underlyings,
                    )
                )
            else:
                trades.append(
                    adapt_trade_row(
                        row,
                        trade_date=trade_date,
                        allowed_underlyings=allowed_underlyings,
                    )
                )
        except ValueError as exc:
            rejected[str(exc)] += 1

    return {
        "schema_version": "1",
        "vendor": "dxFeed",
        "trade_date": trade_date,
        "allowed_underlyings": sorted(allowed_underlyings),
        "option_trades": trades,
        "option_quotes": quotes,
        "summary": {
            "event_kind": event_kind,
            "input_rows": len(trades) + len(quotes) + sum(rejected.values()),
            "trade_rows": len(trades),
            "quote_rows": len(quotes),
            "rejected_rows": sum(rejected.values()),
            "rejection_reasons": dict(sorted(rejected.items())),
            "g2_coverage_change": False,
        },
    }


def _write_csv(
    path: Path,
    rows: list[dict[str, str]],
    fields: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)


def write_adaptation(
    payload: Mapping[str, object],
    *,
    output_dir: Path,
    input_path: Path,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trades = list(payload.get("option_trades") or [])
    quotes = list(payload.get("option_quotes") or [])

    if trades:
        _write_csv(output_dir / "option_trades.csv", trades, OPTION_TRADE_FIELDS)
    if quotes:
        _write_csv(output_dir / "option_quotes.csv", quotes, OPTION_QUOTE_FIELDS)

    receipt = {
        "schema_version": "1",
        "vendor": "dxFeed",
        "trade_date": payload["trade_date"],
        "allowed_underlyings": payload["allowed_underlyings"],
        "input_receipt": {
            "file_name": input_path.name,
            "size_bytes": input_path.stat().st_size,
            "sha256": _sha256(input_path),
        },
        "summary": payload["summary"],
        "authorization_promoted": False,
        "validation_promoted": False,
        "g2_coverage_change": 0,
    }
    (output_dir / "dxfeed_adaptation_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Adapt authorized dxFeed option tick CSV files into canonical G2 option lanes. "
            "This tool never grants authorization or promotes G2 coverage."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--event-kind",
        choices=["Trade", "TimeAndSale", "Quote"],
        required=True,
    )
    parser.add_argument("--date", required=True)
    parser.add_argument(
        "--underlying",
        action="append",
        required=True,
        help="Expected historical underlying; repeatable.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    rows = _parse_dxfeed_csv(args.input)
    payload = adapt_rows(
        rows,
        event_kind=args.event_kind,
        trade_date=args.date,
        allowed_underlyings={value.strip().upper() for value in args.underlying if value.strip()},
    )
    receipt = write_adaptation(
        payload,
        output_dir=args.output_dir,
        input_path=args.input,
    )
    print(json.dumps(receipt["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
