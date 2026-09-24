from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Literal
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "0.2.0"
ALLOWED_KINDS = {"equity_trade", "equity_quote", "option_trade", "option_quote"}


@dataclass(frozen=True)
class NormalizedMarketEvent:
    event_kind: str
    event_ts_utc: str
    symbol: str
    underlying_symbol: str
    price: str
    size: str
    bid: str
    ask: str
    bid_size: str
    ask_size: str
    option_symbol: str
    expiration: str
    strike: str
    option_type: str
    exchange: str
    conditions: str
    source_name: str
    source_row_number: int
    research_use_only: int = 1


@dataclass(frozen=True)
class EquityMinute:
    minute_ts_utc: str
    symbol: str
    trade_count: int
    volume: int
    dollar_volume: float
    open: str
    high: str
    low: str
    close: str
    vwap: str
    quote_count: int
    mean_mid: str
    mean_quoted_spread: str
    mean_relative_spread: str
    last_bid: str
    last_ask: str
    source_name: str
    research_use_only: int = 1


@dataclass(frozen=True)
class OptionMinute:
    minute_ts_utc: str
    underlying_symbol: str
    trade_count: int
    contract_volume: int
    dollar_volume: float
    call_volume: int
    put_volume: int
    unique_contracts_traded: int
    quote_count: int
    mean_quoted_spread: str
    source_name: str
    research_use_only: int = 1


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _parse_float(value: str, *, field: str, row_number: int, allow_blank: bool = False) -> float | None:
    value = _clean(value)
    if not value and allow_blank:
        return None
    try:
        result = float(value)
    except Exception as exc:
        raise ValueError(f"row {row_number}: invalid {field}={value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"row {row_number}: non-finite {field}={value!r}")
    return result


def _parse_int(value: str, *, field: str, row_number: int, allow_blank: bool = False) -> int | None:
    value = _clean(value)
    if not value and allow_blank:
        return None
    try:
        # Many vendors serialize integer sizes as 100.0; accept only integral floats.
        parsed = float(value)
        if not parsed.is_integer():
            raise ValueError
        result = int(parsed)
    except Exception as exc:
        raise ValueError(f"row {row_number}: invalid {field}={value!r}") from exc
    return result


def _parse_timestamp(value: str, input_tz: str, *, row_number: int) -> datetime:
    value = _clean(value)
    if not value:
        raise ValueError(f"row {row_number}: blank timestamp")

    parsed: datetime | None = None
    # ISO-8601 first, including Z/offset.
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass

    if parsed is None:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError(f"row {row_number}: unsupported timestamp {value!r}")

    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(input_tz))
        except Exception as exc:
            raise ValueError(f"invalid input timezone {input_tz!r}") from exc
    return parsed.astimezone(timezone.utc)


def _fmt_num(value: float | int | None, digits: int = 10) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    return (f"{value:.{digits}f}").rstrip("0").rstrip(".")


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _require_columns(reader: csv.DictReader, required: set[str]) -> None:
    missing = required.difference(reader.fieldnames or [])
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")


def _validate_symbol(symbol: str, *, field: str, row_number: int) -> str:
    symbol = _clean(symbol).upper()
    if not symbol:
        raise ValueError(f"row {row_number}: blank {field}")
    if len(symbol) > 64:
        raise ValueError(f"row {row_number}: implausibly long {field}")
    return symbol


def _trade_event(row: dict[str, str], *, kind: str, input_tz: str, source_name: str, row_number: int) -> NormalizedMarketEvent:
    is_option = kind == "option_trade"
    symbol = _validate_symbol(row.get("symbol", ""), field="symbol", row_number=row_number)
    underlying = _validate_symbol(row.get("underlying_symbol", symbol if not is_option else ""), field="underlying_symbol", row_number=row_number)
    price = _parse_float(row.get("price", ""), field="price", row_number=row_number)
    size = _parse_int(row.get("size", ""), field="size", row_number=row_number)
    if price is None or price <= 0:
        raise ValueError(f"row {row_number}: price must be > 0")
    if size is None or size <= 0:
        raise ValueError(f"row {row_number}: size must be > 0")

    option_symbol = ""
    expiration = ""
    strike = ""
    option_type = ""
    if is_option:
        option_symbol = _validate_symbol(row.get("option_symbol", symbol), field="option_symbol", row_number=row_number)
        expiration = _clean(row.get("expiration"))
        if expiration:
            try:
                datetime.strptime(expiration, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"row {row_number}: invalid expiration={expiration!r}") from exc
        strike_val = _parse_float(row.get("strike", ""), field="strike", row_number=row_number)
        if strike_val is None or strike_val <= 0:
            raise ValueError(f"row {row_number}: strike must be > 0")
        strike = _fmt_num(strike_val)
        option_type = _clean(row.get("option_type")).upper()
        if option_type not in {"C", "P", "CALL", "PUT"}:
            raise ValueError(f"row {row_number}: option_type must be C/P/CALL/PUT")
        option_type = "C" if option_type in {"C", "CALL"} else "P"

    return NormalizedMarketEvent(
        event_kind=kind,
        event_ts_utc=_fmt_ts(_parse_timestamp(row.get("timestamp", ""), input_tz, row_number=row_number)),
        symbol=symbol,
        underlying_symbol=underlying,
        price=_fmt_num(price),
        size=str(size),
        bid="",
        ask="",
        bid_size="",
        ask_size="",
        option_symbol=option_symbol,
        expiration=expiration,
        strike=strike,
        option_type=option_type,
        exchange=_clean(row.get("exchange")).upper(),
        conditions=_clean(row.get("conditions")),
        source_name=source_name,
        source_row_number=row_number,
    )


def _quote_event(row: dict[str, str], *, kind: str, input_tz: str, source_name: str, row_number: int) -> NormalizedMarketEvent:
    is_option = kind == "option_quote"
    symbol = _validate_symbol(row.get("symbol", ""), field="symbol", row_number=row_number)
    underlying = _validate_symbol(row.get("underlying_symbol", symbol if not is_option else ""), field="underlying_symbol", row_number=row_number)
    bid = _parse_float(row.get("bid", ""), field="bid", row_number=row_number)
    ask = _parse_float(row.get("ask", ""), field="ask", row_number=row_number)
    bid_size = _parse_int(row.get("bid_size", ""), field="bid_size", row_number=row_number)
    ask_size = _parse_int(row.get("ask_size", ""), field="ask_size", row_number=row_number)
    if bid is None or ask is None or bid < 0 or ask <= 0:
        raise ValueError(f"row {row_number}: quote prices must satisfy bid >= 0 and ask > 0")
    if bid > ask:
        raise ValueError(f"row {row_number}: crossed quote bid={bid} ask={ask}")
    if bid_size is None or ask_size is None or bid_size < 0 or ask_size < 0:
        raise ValueError(f"row {row_number}: quote sizes must be >= 0")

    option_symbol = ""
    expiration = ""
    strike = ""
    option_type = ""
    if is_option:
        option_symbol = _validate_symbol(row.get("option_symbol", symbol), field="option_symbol", row_number=row_number)
        expiration = _clean(row.get("expiration"))
        if expiration:
            try:
                datetime.strptime(expiration, "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"row {row_number}: invalid expiration={expiration!r}") from exc
        strike_val = _parse_float(row.get("strike", ""), field="strike", row_number=row_number)
        if strike_val is None or strike_val <= 0:
            raise ValueError(f"row {row_number}: strike must be > 0")
        strike = _fmt_num(strike_val)
        option_type = _clean(row.get("option_type")).upper()
        if option_type not in {"C", "P", "CALL", "PUT"}:
            raise ValueError(f"row {row_number}: option_type must be C/P/CALL/PUT")
        option_type = "C" if option_type in {"C", "CALL"} else "P"

    return NormalizedMarketEvent(
        event_kind=kind,
        event_ts_utc=_fmt_ts(_parse_timestamp(row.get("timestamp", ""), input_tz, row_number=row_number)),
        symbol=symbol,
        underlying_symbol=underlying,
        price="",
        size="",
        bid=_fmt_num(bid),
        ask=_fmt_num(ask),
        bid_size=str(bid_size),
        ask_size=str(ask_size),
        option_symbol=option_symbol,
        expiration=expiration,
        strike=strike,
        option_type=option_type,
        exchange=_clean(row.get("exchange")).upper(),
        conditions=_clean(row.get("conditions")),
        source_name=source_name,
        source_row_number=row_number,
    )


def load_csv(path: Path, *, kind: str, input_tz: str = "America/New_York", source_name: str | None = None) -> list[NormalizedMarketEvent]:
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"kind must be one of {sorted(ALLOWED_KINDS)}")
    source_name = source_name or path.name

    required = {"timestamp", "symbol"}
    if kind.endswith("trade"):
        required |= {"price", "size"}
    else:
        required |= {"bid", "ask", "bid_size", "ask_size"}
    if kind.startswith("option"):
        required |= {"underlying_symbol", "option_symbol", "expiration", "strike", "option_type"}

    events: list[NormalizedMarketEvent] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        _require_columns(reader, required)
        for row_number, row in enumerate(reader, start=2):
            if kind.endswith("trade"):
                event = _trade_event(row, kind=kind, input_tz=input_tz, source_name=source_name, row_number=row_number)
            else:
                event = _quote_event(row, kind=kind, input_tz=input_tz, source_name=source_name, row_number=row_number)
            events.append(event)
    events.sort(key=lambda e: (e.event_ts_utc, e.symbol, e.option_symbol, e.source_row_number))
    return events


def _minute_key(ts: str) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    dt = dt.replace(second=0, microsecond=0)
    return _fmt_ts(dt)


def aggregate_equity_minutes(events: Iterable[NormalizedMarketEvent]) -> list[EquityMinute]:
    buckets: dict[tuple[str, str], list[NormalizedMarketEvent]] = defaultdict(list)
    for e in events:
        if e.event_kind not in {"equity_trade", "equity_quote"}:
            continue
        buckets[(_minute_key(e.event_ts_utc), e.symbol)].append(e)

    out: list[EquityMinute] = []
    for (minute, symbol), rows in sorted(buckets.items()):
        source_name = ";".join(sorted({r.source_name for r in rows}))
        trades = [r for r in rows if r.event_kind == "equity_trade"]
        quotes = [r for r in rows if r.event_kind == "equity_quote"]
        trade_prices = [float(r.price) for r in trades]
        trade_sizes = [int(r.size) for r in trades]
        volume = sum(trade_sizes)
        dollar_volume = sum(p * s for p, s in zip(trade_prices, trade_sizes))
        mids: list[float] = []
        spreads: list[float] = []
        rel_spreads: list[float] = []
        for q in quotes:
            bid, ask = float(q.bid), float(q.ask)
            mid = (bid + ask) / 2.0
            spread = ask - bid
            mids.append(mid)
            spreads.append(spread)
            if mid > 0:
                rel_spreads.append(spread / mid)
        last_quote = max(quotes, key=lambda q: q.event_ts_utc) if quotes else None
        out.append(
            EquityMinute(
                minute_ts_utc=minute,
                symbol=symbol,
                trade_count=len(trades),
                volume=volume,
                dollar_volume=round(dollar_volume, 8),
                open=_fmt_num(trade_prices[0] if trade_prices else None),
                high=_fmt_num(max(trade_prices) if trade_prices else None),
                low=_fmt_num(min(trade_prices) if trade_prices else None),
                close=_fmt_num(trade_prices[-1] if trade_prices else None),
                vwap=_fmt_num(dollar_volume / volume if volume else None),
                quote_count=len(quotes),
                mean_mid=_fmt_num(sum(mids) / len(mids) if mids else None),
                mean_quoted_spread=_fmt_num(sum(spreads) / len(spreads) if spreads else None),
                mean_relative_spread=_fmt_num(sum(rel_spreads) / len(rel_spreads) if rel_spreads else None),
                last_bid=last_quote.bid if last_quote else "",
                last_ask=last_quote.ask if last_quote else "",
                source_name=source_name,
            )
        )
    return out


def aggregate_option_minutes(events: Iterable[NormalizedMarketEvent]) -> list[OptionMinute]:
    buckets: dict[tuple[str, str], list[NormalizedMarketEvent]] = defaultdict(list)
    for e in events:
        if e.event_kind not in {"option_trade", "option_quote"}:
            continue
        buckets[(_minute_key(e.event_ts_utc), e.underlying_symbol)].append(e)

    out: list[OptionMinute] = []
    for (minute, underlying), rows in sorted(buckets.items()):
        source_name = ";".join(sorted({r.source_name for r in rows}))
        trades = [r for r in rows if r.event_kind == "option_trade"]
        quotes = [r for r in rows if r.event_kind == "option_quote"]
        contract_volume = sum(int(r.size) for r in trades)
        # Option price is per share; 100-share multiplier is explicit for economic notional.
        dollar_volume = sum(float(r.price) * int(r.size) * 100.0 for r in trades)
        call_volume = sum(int(r.size) for r in trades if r.option_type == "C")
        put_volume = sum(int(r.size) for r in trades if r.option_type == "P")
        contracts = {r.option_symbol for r in trades}
        spreads = [float(q.ask) - float(q.bid) for q in quotes]
        out.append(
            OptionMinute(
                minute_ts_utc=minute,
                underlying_symbol=underlying,
                trade_count=len(trades),
                contract_volume=contract_volume,
                dollar_volume=round(dollar_volume, 8),
                call_volume=call_volume,
                put_volume=put_volume,
                unique_contracts_traded=len(contracts),
                quote_count=len(quotes),
                mean_quoted_spread=_fmt_num(sum(spreads) / len(spreads) if spreads else None),
                source_name=source_name,
            )
        )
    return out


def write_records(records: Iterable[object], path: Path) -> None:
    records = list(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text("", encoding="utf-8")
        return
    names = [f.name for f in fields(records[0])]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=names)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(*, inputs: list[tuple[Path, str]], normalized_count: int, equity_minute_count: int, option_minute_count: int) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Historical market-surveillance research input normalization; never a trading signal.",
        "point_in_time_policy": (
            "Only event-time fields present in the supplied lawful market-data files are normalized. "
            "No future announcement content, future prices, enforcement outcomes, or directional labels are added."
        ),
        "timestamp_policy": "All normalized timestamps are UTC ISO-8601; naive inputs require an explicit source timezone.",
        "inputs": [
            {"path": str(path), "kind": kind, "sha256": _sha256(path)}
            for path, kind in inputs
        ],
        "outputs": {
            "normalized_event_count": normalized_count,
            "equity_minute_count": equity_minute_count,
            "option_minute_count": option_minute_count,
        },
        "prohibited_outputs": ["BUY", "SELL", "expected_return", "target_price", "position_size", "order"],
    }


def build(specs: list[tuple[Path, str]], output_dir: Path, *, input_tz: str = "America/New_York", source_name: str = "historical_market_data") -> dict:
    normalized: list[NormalizedMarketEvent] = []
    for path, kind in specs:
        normalized.extend(load_csv(path, kind=kind, input_tz=input_tz, source_name=source_name))
    normalized.sort(key=lambda e: (e.event_ts_utc, e.event_kind, e.symbol, e.option_symbol, e.source_row_number))

    equity_minutes = aggregate_equity_minutes(normalized)
    option_minutes = aggregate_option_minutes(normalized)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_records(normalized, output_dir / "normalized_market_events.csv")
    write_records(equity_minutes, output_dir / "equity_minutes.csv")
    write_records(option_minutes, output_dir / "option_minutes.csv")

    manifest = build_manifest(
        inputs=specs,
        normalized_count=len(normalized),
        equity_minute_count=len(equity_minutes),
        option_minute_count=len(option_minutes),
    )
    (output_dir / "market_data_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _parse_spec(value: str) -> tuple[Path, str]:
    try:
        kind, raw_path = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("input spec must be KIND=PATH") from exc
    kind = kind.strip()
    if kind not in ALLOWED_KINDS:
        raise argparse.ArgumentTypeError(f"kind must be one of {sorted(ALLOWED_KINDS)}")
    return Path(raw_path), kind


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize lawful historical market data for surveillance research.")
    parser.add_argument("--input", action="append", type=_parse_spec, required=True, help="KIND=PATH; repeatable")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input-tz", default="America/New_York")
    parser.add_argument("--source-name", default="historical_market_data")
    args = parser.parse_args()
    manifest = build(args.input, args.output_dir, input_tz=args.input_tz, source_name=args.source_name)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
