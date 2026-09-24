from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator
from zoneinfo import ZoneInfo

import market_data_adapter as mda

SCHEMA_VERSION = "0.15.0"
NY = ZoneInfo("America/New_York")

ALLOWED_RECORD_KINDS = {
    "equity_trade",
    "equity_quote",
    "option_trade",
    "option_quote",
    "itch_decoded",
}
ALLOWED_SOURCE_FAMILIES = {
    "nyse_daily_taq",
    "nasdaq_itch_5_0_decoded",
    "cboe_option_trades",
    "cboe_option_quotes",
    "generic_authorized_market_data",
    "synthetic_fixture",
}
NON_SYNTHETIC_CLASS = "authorized_historical_market_data"
SYNTHETIC_CLASS = "synthetic_fixture"


@dataclass(frozen=True)
class SourceContract:
    source_id: str
    source_family: str
    record_kind: str
    path: str
    authorized: bool
    data_classification: str
    license_reference: str
    trade_date: str
    timezone: str
    delimiter: str
    encoding: str
    format_version: str
    column_map: dict[str, str]
    notes: str = ""


@dataclass(frozen=True)
class ItchExecution:
    event_ts_utc: str
    symbol: str
    order_reference: str
    match_number: str
    resting_side: str
    aggressor_side: str
    executed_shares: int
    execution_price: str
    printable: int
    source_name: str
    source_row_number: int
    research_use_only: int = 1


@dataclass(frozen=True)
class OrderFlowMinute:
    minute_ts_utc: str
    symbol: str
    execution_count: int
    printable_execution_count: int
    executed_shares: int
    signed_aggressor_shares: int
    buy_aggressor_shares: int
    sell_aggressor_shares: int
    absolute_order_imbalance: str
    source_name: str
    research_use_only: int = 1


@dataclass(frozen=True)
class MicrostructureMinute:
    minute_ts_utc: str
    symbol: str
    signed_trade_count: int
    signed_share_volume: int
    buy_volume: int
    sell_volume: int
    taq_absolute_order_imbalance: str
    mean_effective_spread_pct: str
    mean_realized_spread_5m_pct: str
    mean_price_impact_5m_pct: str
    quoted_spread_pct: str
    realized_spread_uses_future_market_data: int
    price_impact_uses_future_market_data: int
    research_use_only: int = 1


@dataclass(frozen=True)
class EventMinutePanelRow:
    event_id: str
    historical_symbol: str
    first_trade_ts_utc: str
    minute_ts_utc: str
    relative_minute: int
    equity_trade_count: str
    share_volume: str
    log_share_volume: str
    dollar_volume: str
    share_turnover: str
    option_trade_count: str
    option_contract_volume: str
    log_option_volume: str
    option_call_volume: str
    option_put_volume: str
    quoted_spread_pct: str
    effective_spread_pct: str
    realized_spread_5m_pct: str
    price_impact_5m_pct: str
    absolute_order_imbalance: str
    order_flow_source: str
    research_use_only: int = 1


@dataclass(frozen=True)
class EventCoverage:
    event_id: str
    historical_symbol: str
    first_trade_ts_utc: str
    panel_minute_count: int
    equity_minutes_present: int
    option_minutes_present: int
    order_flow_minutes_present: int
    effective_spread_minutes_present: int
    posthoc_5m_minutes_present: int
    source_families: str
    non_synthetic_authorized_sources: int
    research_use_only: int = 1


def _clean(v: object) -> str:
    return "" if v is None else str(v).strip()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fmt(value: float | int | None, digits: int = 10) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return ""
    return (f"{value:.{digits}f}").rstrip("0").rstrip(".")


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware: {value!r}")
    return dt.astimezone(timezone.utc)


def _first_trade_to_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(timezone.utc)


def _minute(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _read_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("contract root must be a JSON object")
    return obj


def _safe_delimiter(value: str) -> str:
    if value in {"comma", ","}:
        return ","
    if value in {"pipe", "|"}:
        return "|"
    if value in {"tab", "\\t", "\t"}:
        return "\t"
    if len(value) != 1:
        raise ValueError(f"delimiter must be one character or comma/pipe/tab; got {value!r}")
    return value


def load_contract(path: Path) -> tuple[list[SourceContract], dict]:
    obj = _read_json(path)
    if obj.get("schema_version") != "1":
        raise ValueError("source contract schema_version must equal '1'")
    sources = obj.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("source contract must include a non-empty sources list")
    out: list[SourceContract] = []
    seen: set[str] = set()
    for i, raw in enumerate(sources, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"source {i}: must be an object")
        source_id = _clean(raw.get("source_id"))
        if not source_id or source_id in seen:
            raise ValueError(f"source {i}: source_id must be unique and non-blank")
        seen.add(source_id)
        family = _clean(raw.get("source_family"))
        kind = _clean(raw.get("record_kind"))
        if family not in ALLOWED_SOURCE_FAMILIES:
            raise ValueError(f"source {source_id}: unsupported source_family={family!r}")
        if kind not in ALLOWED_RECORD_KINDS:
            raise ValueError(f"source {source_id}: unsupported record_kind={kind!r}")
        authorized = bool(raw.get("authorized"))
        if not authorized:
            raise PermissionError(f"source {source_id}: authorized must be true")
        data_class = _clean(raw.get("data_classification"))
        if data_class not in {NON_SYNTHETIC_CLASS, SYNTHETIC_CLASS}:
            raise ValueError(f"source {source_id}: unsupported data_classification={data_class!r}")
        license_ref = _clean(raw.get("license_reference"))
        if data_class == NON_SYNTHETIC_CLASS and not license_ref:
            raise ValueError(f"source {source_id}: non-synthetic authorized data requires license_reference")
        trade_date = _clean(raw.get("trade_date"))
        if trade_date:
            datetime.strptime(trade_date, "%Y-%m-%d")
        timezone_name = _clean(raw.get("timezone")) or "America/New_York"
        ZoneInfo(timezone_name)
        delimiter = _safe_delimiter(_clean(raw.get("delimiter")) or ",")
        encoding = _clean(raw.get("encoding")) or "utf-8"
        format_version = _clean(raw.get("format_version"))
        column_map = raw.get("column_map") or {}
        if not isinstance(column_map, dict):
            raise ValueError(f"source {source_id}: column_map must be an object")
        path_value = _clean(raw.get("path"))
        if not path_value:
            raise ValueError(f"source {source_id}: path is required")
        data_path = Path(path_value)
        if not data_path.is_absolute():
            data_path = (path.parent / data_path).resolve()
        if not data_path.exists():
            raise FileNotFoundError(f"source {source_id}: file does not exist: {data_path}")
        if family == "nasdaq_itch_5_0_decoded" and not format_version:
            raise ValueError(f"source {source_id}: decoded ITCH requires format_version")
        out.append(SourceContract(
            source_id=source_id,
            source_family=family,
            record_kind=kind,
            path=str(data_path),
            authorized=authorized,
            data_classification=data_class,
            license_reference=license_ref,
            trade_date=trade_date,
            timezone=timezone_name,
            delimiter=delimiter,
            encoding=encoding,
            format_version=format_version,
            column_map={str(k): str(v) for k, v in column_map.items()},
            notes=_clean(raw.get("notes")),
        ))
    return out, obj


def _open_dict_rows(spec: SourceContract) -> Iterator[tuple[int, dict[str, str]]]:
    path = Path(spec.path)
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rt", encoding=spec.encoding, newline="") as f:
        reader = csv.DictReader(f, delimiter=spec.delimiter)
        if not reader.fieldnames:
            raise ValueError(f"source {spec.source_id}: missing header")
        for row_number, row in enumerate(reader, 2):
            yield row_number, {str(k): _clean(v) for k, v in row.items() if k is not None}


def _mapped(row: dict[str, str], spec: SourceContract, canonical: str, default: str = "") -> str:
    source_col = spec.column_map.get(canonical, canonical)
    if source_col in row:
        return _clean(row.get(source_col))
    return default


def _compose_timestamp(row: dict[str, str], spec: SourceContract) -> str:
    value = _mapped(row, spec, "timestamp")
    if value:
        return value
    date = _mapped(row, spec, "date") or spec.trade_date
    time = _mapped(row, spec, "time")
    if not date or not time:
        raise ValueError(f"source {spec.source_id}: timestamp requires timestamp or date+time mapping")
    return f"{date} {time}"


def _map_market_row(row: dict[str, str], spec: SourceContract) -> dict[str, str]:
    out = {
        "timestamp": _compose_timestamp(row, spec),
        "symbol": _mapped(row, spec, "symbol"),
        "price": _mapped(row, spec, "price"),
        "size": _mapped(row, spec, "size"),
        "bid": _mapped(row, spec, "bid"),
        "ask": _mapped(row, spec, "ask"),
        "bid_size": _mapped(row, spec, "bid_size", "0"),
        "ask_size": _mapped(row, spec, "ask_size", "0"),
        "underlying_symbol": _mapped(row, spec, "underlying_symbol"),
        "option_symbol": _mapped(row, spec, "option_symbol"),
        "expiration": _mapped(row, spec, "expiration"),
        "strike": _mapped(row, spec, "strike"),
        "option_type": _mapped(row, spec, "option_type"),
        "exchange": _mapped(row, spec, "exchange"),
        "conditions": _mapped(row, spec, "conditions"),
    }
    if spec.record_kind.startswith("option") and not out["symbol"]:
        out["symbol"] = out["option_symbol"]
    if spec.record_kind.startswith("option") and not out["option_symbol"]:
        out["option_symbol"] = out["symbol"]
    if spec.record_kind.startswith("equity") and not out["underlying_symbol"]:
        out["underlying_symbol"] = out["symbol"]
    return out


def load_market_events(spec: SourceContract) -> list[mda.NormalizedMarketEvent]:
    if spec.record_kind == "itch_decoded":
        return []
    events: list[mda.NormalizedMarketEvent] = []
    for row_number, row in _open_dict_rows(spec):
        mapped = _map_market_row(row, spec)
        if spec.record_kind.endswith("trade"):
            event = mda._trade_event(mapped, kind=spec.record_kind, input_tz=spec.timezone,
                                     source_name=spec.source_id, row_number=row_number)
        else:
            event = mda._quote_event(mapped, kind=spec.record_kind, input_tz=spec.timezone,
                                     source_name=spec.source_id, row_number=row_number)
        events.append(event)
    events.sort(key=lambda e: (e.event_ts_utc, e.symbol, e.option_symbol, e.source_row_number))
    return events


def _parse_int(value: str, *, field: str, row_number: int) -> int:
    try:
        x = float(_clean(value))
        if not x.is_integer():
            raise ValueError
        return int(x)
    except Exception as exc:
        raise ValueError(f"row {row_number}: invalid {field}={value!r}") from exc


def _parse_float(value: str, *, field: str, row_number: int) -> float:
    try:
        x = float(_clean(value))
    except Exception as exc:
        raise ValueError(f"row {row_number}: invalid {field}={value!r}") from exc
    if not math.isfinite(x):
        raise ValueError(f"row {row_number}: non-finite {field}")
    return x


def load_itch_executions(spec: SourceContract) -> list[ItchExecution]:
    if spec.record_kind != "itch_decoded":
        return []
    orders: dict[str, dict[str, object]] = {}
    executions_by_match: dict[str, ItchExecution] = {}
    ordered_execs: list[ItchExecution] = []

    for row_number, row in _open_dict_rows(spec):
        message_type = _mapped(row, spec, "message_type").upper()
        if not message_type:
            raise ValueError(f"row {row_number}: blank message_type")
        ts = _fmt_ts(mda._parse_timestamp(_compose_timestamp(row, spec), spec.timezone, row_number=row_number))
        order_ref = _mapped(row, spec, "order_reference")
        if message_type in {"A", "F", "ADD", "ADD_ORDER"}:
            if not order_ref:
                raise ValueError(f"row {row_number}: add order missing order_reference")
            side = _mapped(row, spec, "side").upper()
            if side not in {"B", "S", "BUY", "SELL"}:
                raise ValueError(f"row {row_number}: add order side must be B/S")
            side = "B" if side in {"B", "BUY"} else "S"
            symbol = _mapped(row, spec, "symbol").upper()
            shares = _parse_int(_mapped(row, spec, "shares"), field="shares", row_number=row_number)
            price = _parse_float(_mapped(row, spec, "price"), field="price", row_number=row_number)
            if not symbol or shares <= 0 or price <= 0:
                raise ValueError(f"row {row_number}: invalid add-order symbol/shares/price")
            orders[order_ref] = {"side": side, "symbol": symbol, "shares": shares, "price": price}
            continue
        if message_type in {"X", "CANCEL"}:
            if order_ref in orders:
                cancel = _parse_int(_mapped(row, spec, "cancelled_shares") or _mapped(row, spec, "shares"), field="cancelled_shares", row_number=row_number)
                orders[order_ref]["shares"] = max(0, int(orders[order_ref]["shares"]) - cancel)
            continue
        if message_type in {"D", "DELETE"}:
            orders.pop(order_ref, None)
            continue
        if message_type in {"U", "REPLACE"}:
            new_ref = _mapped(row, spec, "new_order_reference")
            old = orders.pop(order_ref, None)
            if old is not None and new_ref:
                shares_raw = _mapped(row, spec, "shares")
                price_raw = _mapped(row, spec, "price")
                orders[new_ref] = {
                    "side": old["side"],
                    "symbol": old["symbol"],
                    "shares": _parse_int(shares_raw, field="shares", row_number=row_number) if shares_raw else old["shares"],
                    "price": _parse_float(price_raw, field="price", row_number=row_number) if price_raw else old["price"],
                }
            continue
        if message_type in {"E", "C", "EXECUTE", "EXECUTE_WITH_PRICE"}:
            state = orders.get(order_ref)
            if state is None:
                # Fail closed: without the add-order state we cannot sign the execution reliably.
                continue
            shares = _parse_int(_mapped(row, spec, "executed_shares") or _mapped(row, spec, "shares"), field="executed_shares", row_number=row_number)
            price_raw = _mapped(row, spec, "execution_price") or _mapped(row, spec, "price")
            price = _parse_float(price_raw, field="execution_price", row_number=row_number) if price_raw else float(state["price"])
            match_number = _mapped(row, spec, "match_number")
            resting = str(state["side"])
            aggressor = "B" if resting == "S" else "S"
            printable_raw = (_mapped(row, spec, "printable") or "Y").upper()
            printable = int(printable_raw not in {"N", "0", "FALSE"})
            exe = ItchExecution(
                event_ts_utc=ts,
                symbol=str(state["symbol"]),
                order_reference=order_ref,
                match_number=match_number,
                resting_side=resting,
                aggressor_side=aggressor,
                executed_shares=shares,
                execution_price=_fmt(price),
                printable=printable,
                source_name=spec.source_id,
                source_row_number=row_number,
            )
            ordered_execs.append(exe)
            if match_number:
                executions_by_match[match_number] = exe
            state["shares"] = max(0, int(state["shares"]) - shares)
            continue
        if message_type in {"B", "TRADE_BREAK"}:
            match_number = _mapped(row, spec, "match_number")
            prior = executions_by_match.pop(match_number, None)
            if prior is not None:
                try:
                    ordered_execs.remove(prior)
                except ValueError:
                    pass
            continue
        # Cross/non-displayed trade messages are intentionally not assigned an aggressor sign here.
    ordered_execs.sort(key=lambda e: (e.event_ts_utc, e.symbol, e.source_row_number))
    return ordered_execs


def aggregate_order_flow_minutes(executions: Iterable[ItchExecution]) -> list[OrderFlowMinute]:
    buckets: dict[tuple[str, str], list[ItchExecution]] = defaultdict(list)
    for e in executions:
        buckets[(mda._minute_key(e.event_ts_utc), e.symbol)].append(e)
    out: list[OrderFlowMinute] = []
    for (minute, symbol), rows in sorted(buckets.items()):
        buy = sum(r.executed_shares for r in rows if r.aggressor_side == "B")
        sell = sum(r.executed_shares for r in rows if r.aggressor_side == "S")
        total = buy + sell
        signed = buy - sell
        out.append(OrderFlowMinute(
            minute_ts_utc=minute,
            symbol=symbol,
            execution_count=len(rows),
            printable_execution_count=sum(r.printable for r in rows),
            executed_shares=total,
            signed_aggressor_shares=signed,
            buy_aggressor_shares=buy,
            sell_aggressor_shares=sell,
            absolute_order_imbalance=_fmt(abs(signed) / total if total else None),
            source_name=";".join(sorted({r.source_name for r in rows})),
        ))
    return out


def _quote_series(events: Iterable[mda.NormalizedMarketEvent]) -> dict[str, tuple[list[datetime], list[mda.NormalizedMarketEvent]]]:
    by: dict[str, list[mda.NormalizedMarketEvent]] = defaultdict(list)
    for e in events:
        if e.event_kind == "equity_quote":
            by[e.symbol].append(e)
    out = {}
    for symbol, rows in by.items():
        rows.sort(key=lambda x: x.event_ts_utc)
        out[symbol] = ([_parse_utc(r.event_ts_utc) for r in rows], rows)
    return out


def _prev_quote(series: tuple[list[datetime], list[mda.NormalizedMarketEvent]] | None, ts: datetime, max_age_seconds: int) -> mda.NormalizedMarketEvent | None:
    if not series:
        return None
    times, rows = series
    i = bisect.bisect_right(times, ts) - 1
    if i < 0:
        return None
    if (ts - times[i]).total_seconds() > max_age_seconds:
        return None
    return rows[i]


def _future_quote(series: tuple[list[datetime], list[mda.NormalizedMarketEvent]] | None, target: datetime, tolerance_seconds: int) -> mda.NormalizedMarketEvent | None:
    if not series:
        return None
    times, rows = series
    i = bisect.bisect_left(times, target)
    if i >= len(times):
        return None
    if (times[i] - target).total_seconds() > tolerance_seconds:
        return None
    return rows[i]


def build_microstructure_minutes(events: Iterable[mda.NormalizedMarketEvent], *, quote_max_age_seconds: int = 30,
                                 future_horizon_minutes: int = 5, future_tolerance_seconds: int = 90) -> list[MicrostructureMinute]:
    events = list(events)
    quote_index = _quote_series(events)
    trades_by: dict[tuple[str, str], list[mda.NormalizedMarketEvent]] = defaultdict(list)
    equity_minute_by: dict[tuple[str, str], mda.EquityMinute] = {
        (x.symbol, x.minute_ts_utc): x for x in mda.aggregate_equity_minutes(events)
    }
    for e in events:
        if e.event_kind == "equity_trade":
            trades_by[(e.symbol, mda._minute_key(e.event_ts_utc))].append(e)

    out: list[MicrostructureMinute] = []
    last_trade_price: dict[str, float] = {}
    last_tick_sign: dict[str, int] = {}
    for (symbol, minute), trades in sorted(trades_by.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        signed_rows = []
        for t in sorted(trades, key=lambda x: x.event_ts_utc):
            ts = _parse_utc(t.event_ts_utc)
            price = float(t.price)
            size = int(t.size)
            q = _prev_quote(quote_index.get(symbol), ts, quote_max_age_seconds)
            sign = 0
            mid = None
            if q is not None:
                mid = (float(q.bid) + float(q.ask)) / 2.0
                if price > mid:
                    sign = 1
                elif price < mid:
                    sign = -1
            if sign == 0:
                prev = last_trade_price.get(symbol)
                if prev is not None:
                    sign = 1 if price > prev else -1 if price < prev else last_tick_sign.get(symbol, 0)
            if sign:
                last_tick_sign[symbol] = sign
            last_trade_price[symbol] = price
            effective = None
            realized = None
            impact = None
            if sign and mid and mid > 0:
                effective = 2.0 * sign * (price - mid) / mid
                fq = _future_quote(quote_index.get(symbol), ts + timedelta(minutes=future_horizon_minutes), future_tolerance_seconds)
                if fq is not None:
                    future_mid = (float(fq.bid) + float(fq.ask)) / 2.0
                    realized = 2.0 * sign * (price - future_mid) / mid
                    impact = 2.0 * sign * (future_mid - mid) / mid
            signed_rows.append((sign, size, effective, realized, impact))
        buy = sum(size for sign, size, *_ in signed_rows if sign > 0)
        sell = sum(size for sign, size, *_ in signed_rows if sign < 0)
        signed_count = sum(sign != 0 for sign, *_ in signed_rows)
        signed_volume = buy + sell
        def vw(index: int) -> float | None:
            vals = [(row[index], row[1]) for row in signed_rows if row[index] is not None]
            denom = sum(w for _, w in vals)
            return sum(float(v) * w for v, w in vals) / denom if denom else None
        minute_bar = equity_minute_by.get((symbol, minute))
        out.append(MicrostructureMinute(
            minute_ts_utc=minute,
            symbol=symbol,
            signed_trade_count=signed_count,
            signed_share_volume=signed_volume,
            buy_volume=buy,
            sell_volume=sell,
            taq_absolute_order_imbalance=_fmt(abs(buy - sell) / signed_volume if signed_volume else None),
            mean_effective_spread_pct=_fmt(vw(2)),
            mean_realized_spread_5m_pct=_fmt(vw(3)),
            mean_price_impact_5m_pct=_fmt(vw(4)),
            quoted_spread_pct=(minute_bar.mean_relative_spread if minute_bar else ""),
            realized_spread_uses_future_market_data=1,
            price_impact_uses_future_market_data=1,
        ))
    return out


def load_events(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("historical events file is empty")
    required = {"event_id", "historical_symbol", "first_documented_illicit_trade_ts", "research_use_only"}
    missing = required.difference(rows[0])
    if missing:
        raise ValueError(f"historical events missing columns: {sorted(missing)}")
    for i, row in enumerate(rows, 2):
        if row.get("research_use_only") != "1":
            raise ValueError(f"event row {i}: research_use_only must equal 1")
        _first_trade_to_utc(row["first_documented_illicit_trade_ts"])
    return rows


def load_shares(path: Path | None) -> dict[str, list[tuple[datetime, float]]]:
    if path is None:
        return {}
    out: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"symbol", "effective_at", "shares_outstanding"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"shares file missing columns: {sorted(missing)}")
        for i, row in enumerate(reader, 2):
            symbol = _clean(row["symbol"]).upper()
            dt = _parse_utc(row["effective_at"])
            shares = _parse_float(row["shares_outstanding"], field="shares_outstanding", row_number=i)
            if not symbol or shares <= 0:
                raise ValueError(f"shares row {i}: invalid symbol/shares")
            out[symbol].append((dt, shares))
    for rows in out.values():
        rows.sort(key=lambda x: x[0])
    return dict(out)


def _shares_asof(shares: dict[str, list[tuple[datetime, float]]], symbol: str, ts: datetime) -> float | None:
    rows = shares.get(symbol, [])
    best = None
    for dt, value in rows:
        if dt <= ts:
            best = value
        else:
            break
    return best


def build_event_panel(events: list[dict[str, str]], equity_minutes: list[mda.EquityMinute], option_minutes: list[mda.OptionMinute],
                      order_flow_minutes: list[OrderFlowMinute], micro: list[MicrostructureMinute], *, pre_minutes: int,
                      post_minutes: int, shares: dict[str, list[tuple[datetime, float]]]) -> tuple[list[EventMinutePanelRow], list[EventCoverage]]:
    eq = {(r.symbol, r.minute_ts_utc): r for r in equity_minutes}
    opt = {(r.underlying_symbol, r.minute_ts_utc): r for r in option_minutes}
    of = {(r.symbol, r.minute_ts_utc): r for r in order_flow_minutes}
    ms = {(r.symbol, r.minute_ts_utc): r for r in micro}
    panel: list[EventMinutePanelRow] = []
    coverage: list[EventCoverage] = []

    for e in events:
        symbol = e["historical_symbol"].upper()
        first = _first_trade_to_utc(e["first_documented_illicit_trade_ts"])
        anchor = _minute(first)
        eq_n = opt_n = of_n = eff_n = post_n = 0
        families: set[str] = set()
        for rel in range(-pre_minutes, post_minutes + 1):
            minute_dt = anchor + timedelta(minutes=rel)
            key_ts = _fmt_ts(minute_dt)
            er = eq.get((symbol, key_ts))
            orow = opt.get((symbol, key_ts))
            flow = of.get((symbol, key_ts))
            mic = ms.get((symbol, key_ts))
            if er: eq_n += 1; families.update(er.source_name.split(";"))
            if orow: opt_n += 1; families.update(orow.source_name.split(";"))
            if flow: of_n += 1; families.update(flow.source_name.split(";"))
            if mic and mic.mean_effective_spread_pct: eff_n += 1
            if mic and mic.mean_realized_spread_5m_pct and mic.mean_price_impact_5m_pct: post_n += 1
            share_count = _shares_asof(shares, symbol, minute_dt)
            volume = er.volume if er else None
            turnover = (volume / share_count) if volume is not None and share_count else None
            flow_value = ""
            flow_source = ""
            if flow and flow.absolute_order_imbalance:
                flow_value = flow.absolute_order_imbalance
                flow_source = "ITCH_EXECUTION"
            elif mic and mic.taq_absolute_order_imbalance:
                flow_value = mic.taq_absolute_order_imbalance
                flow_source = "TAQ_INFERRED"
            panel.append(EventMinutePanelRow(
                event_id=e["event_id"],
                historical_symbol=symbol,
                first_trade_ts_utc=_fmt_ts(first),
                minute_ts_utc=key_ts,
                relative_minute=rel,
                equity_trade_count=str(er.trade_count) if er else "",
                share_volume=str(er.volume) if er else "",
                log_share_volume=_fmt(math.log1p(er.volume)) if er else "",
                dollar_volume=_fmt(er.dollar_volume) if er else "",
                share_turnover=_fmt(turnover),
                option_trade_count=str(orow.trade_count) if orow else "",
                option_contract_volume=str(orow.contract_volume) if orow else "",
                log_option_volume=_fmt(math.log1p(orow.contract_volume)) if orow else "",
                option_call_volume=str(orow.call_volume) if orow else "",
                option_put_volume=str(orow.put_volume) if orow else "",
                quoted_spread_pct=(mic.quoted_spread_pct if mic else (er.mean_relative_spread if er else "")),
                effective_spread_pct=(mic.mean_effective_spread_pct if mic else ""),
                realized_spread_5m_pct=(mic.mean_realized_spread_5m_pct if mic else ""),
                price_impact_5m_pct=(mic.mean_price_impact_5m_pct if mic else ""),
                absolute_order_imbalance=flow_value,
                order_flow_source=flow_source,
            ))
        coverage.append(EventCoverage(
            event_id=e["event_id"],
            historical_symbol=symbol,
            first_trade_ts_utc=_fmt_ts(first),
            panel_minute_count=pre_minutes + post_minutes + 1,
            equity_minutes_present=eq_n,
            option_minutes_present=opt_n,
            order_flow_minutes_present=of_n,
            effective_spread_minutes_present=eff_n,
            posthoc_5m_minutes_present=post_n,
            source_families=";".join(sorted(x for x in families if x)),
            non_synthetic_authorized_sources=0,
        ))
    return panel, coverage


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
        for r in records:
            writer.writerow(asdict(r))


def build(contract_path: Path, events_path: Path, output_dir: Path, *, pre_minutes: int = 30,
          post_minutes: int = 30, shares_file: Path | None = None) -> dict:
    if pre_minutes < 0 or post_minutes < 0:
        raise ValueError("pre/post minutes must be >= 0")
    specs, raw_contract = load_contract(contract_path)
    events = load_events(events_path)
    shares = load_shares(shares_file)

    market_events: list[mda.NormalizedMarketEvent] = []
    itch_execs: list[ItchExecution] = []
    for spec in specs:
        market_events.extend(load_market_events(spec))
        itch_execs.extend(load_itch_executions(spec))
    market_events.sort(key=lambda e: (e.event_ts_utc, e.event_kind, e.symbol, e.option_symbol, e.source_row_number))

    equity_minutes = mda.aggregate_equity_minutes(market_events)
    option_minutes = mda.aggregate_option_minutes(market_events)
    order_flow_minutes = aggregate_order_flow_minutes(itch_execs)
    micro = build_microstructure_minutes(market_events)
    panel, coverage = build_event_panel(events, equity_minutes, option_minutes, order_flow_minutes, micro,
                                        pre_minutes=pre_minutes, post_minutes=post_minutes, shares=shares)

    non_synthetic_ids = {s.source_id for s in specs if s.data_classification == NON_SYNTHETIC_CLASS}
    coverage = [EventCoverage(**{**asdict(c), "non_synthetic_authorized_sources": len(non_synthetic_ids)}) for c in coverage]

    output_dir.mkdir(parents=True, exist_ok=True)
    mda.write_records(market_events, output_dir / "normalized_market_events.csv")
    mda.write_records(equity_minutes, output_dir / "equity_minutes.csv")
    mda.write_records(option_minutes, output_dir / "option_minutes.csv")
    write_records(itch_execs, output_dir / "itch_executions.csv")
    write_records(order_flow_minutes, output_dir / "order_flow_minutes.csv")
    write_records(micro, output_dir / "microstructure_minutes.csv")
    write_records(panel, output_dir / "event_minute_panel.csv")
    write_records(coverage, output_dir / "event_coverage.csv")

    eligible = bool(non_synthetic_ids) and any(c.equity_minutes_present > 0 for c in coverage)
    readiness_reasons = []
    if not non_synthetic_ids:
        readiness_reasons.append("no_non_synthetic_authorized_market_source_present")
    if not any(c.equity_minutes_present > 0 for c in coverage):
        readiness_reasons.append("no_equity_minute_coverage_for_historical_events")
    if not any(c.option_minutes_present > 0 for c in coverage):
        readiness_reasons.append("no_option_minute_coverage_for_historical_events")
    if not any(c.order_flow_minutes_present > 0 for c in coverage):
        readiness_reasons.append("no_decoded_itch_order_flow_coverage_for_historical_events")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Authorized historical market-data backfill for MNPI/informed-trading surveillance research; not a trading feed.",
        "contract_sha256": _sha256(contract_path),
        "historical_events_sha256": _sha256(events_path),
        "shares_file_sha256": _sha256(shares_file) if shares_file else None,
        "event_count": len(events),
        "source_count": len(specs),
        "source_contracts": [
            {
                **asdict(s),
                "path": str(Path(s.path).name),
                "sha256": _sha256(Path(s.path)),
                "column_map": s.column_map,
            }
            for s in specs
        ],
        "source_contract_policy": {
            "authorization_required": True,
            "credentials_stored_in_contract": False,
            "explicit_column_mapping": True,
            "raw_itch_binary_policy": "Raw binary is not parsed here; use an authorized decoder and provide decoded events with the ITCH specification version recorded.",
        },
        "alignment": {
            "anchor": "first_documented_illicit_trade_ts",
            "pre_minutes": pre_minutes,
            "post_minutes": post_minutes,
            "public_announcement_alignment": "not_available_until_authorized_exact_release_timestamp_join",
        },
        "outputs": {
            "normalized_market_event_count": len(market_events),
            "equity_minute_count": len(equity_minutes),
            "option_minute_count": len(option_minutes),
            "itch_execution_count": len(itch_execs),
            "order_flow_minute_count": len(order_flow_minutes),
            "event_panel_row_count": len(panel),
        },
        "microstructure_policy": {
            "taq_trade_signing": "quote-midpoint rule with tick-rule fallback; an inferred public-market proxy, not known trader identity",
            "itch_signing": "execution side inferred from resting displayed order side for decoded E/C execution messages",
            "effective_spread_point_in_time": True,
            "realized_spread_5m_posthoc_only": True,
            "price_impact_5m_posthoc_only": True,
            "future_5m_fields_forbidden_from_live_model": True,
        },
        "non_synthetic_comparison_readiness": {
            "eligible_for_real_feature_backfill": eligible,
            "eligible_for_champion_challenger_unlock": eligible and not readiness_reasons,
            "reasons": readiness_reasons or ["authorized_non_synthetic_historical_market_coverage_present"],
            "warning": "Presence of authorized files is not a performance result. Champion/challenger evaluation remains a separate locked step.",
        },
        "prohibited_outputs": ["BUY", "SELL", "expected_return", "target_price", "position_size", "order"],
        "research_use_only": True,
    }
    (output_dir / "historical_market_backfill_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def validate_contract(contract_path: Path) -> dict:
    specs, _ = load_contract(contract_path)
    return {
        "valid": True,
        "source_count": len(specs),
        "source_ids": [s.source_id for s in specs],
        "non_synthetic_authorized_source_count": sum(s.data_classification == NON_SYNTHETIC_CLASS for s in specs),
        "synthetic_source_count": sum(s.data_classification == SYNTHETIC_CLASS for s in specs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorized historical TAQ/ITCH/options backfill layer.")
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate-contract")
    v.add_argument("--contract", type=Path, required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--contract", type=Path, required=True)
    b.add_argument("--events", type=Path, required=True)
    b.add_argument("--output-dir", type=Path, required=True)
    b.add_argument("--shares-file", type=Path)
    b.add_argument("--pre-minutes", type=int, default=30)
    b.add_argument("--post-minutes", type=int, default=30)
    args = parser.parse_args()
    if args.command == "validate-contract":
        report = validate_contract(args.contract)
    else:
        report = build(args.contract, args.events, args.output_dir, pre_minutes=args.pre_minutes,
                       post_minutes=args.post_minutes, shares_file=args.shares_file)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
