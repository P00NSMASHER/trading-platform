from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Mapping

import pandas as pd

import g2_lseg_trth_event_pipeline as event


def _as_timestamp(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def event_slice_window(
    event_timestamp: datetime | str,
    ibes_timestamp: datetime | str,
    *,
    lane: str,
) -> dict[str, object]:
    """
    Reproduce the original AroundEarnings source-day window.

    Quote script:
      start = min(EA, IBES) - 1 research business day
      end   = max(EA, IBES) + 2 research business days

    Trade script:
      start = min(EA, IBES) - 1 research business day
      end   = max(EA, IBES) + 1 research business day

    The original code then iterates every calendar day in that inclusive span
    and consumes only source files that exist for those dates.
    """
    if lane not in {"quotes", "trades"}:
        raise ValueError("lane must be quotes or trades")

    ea = pd.Timestamp(_as_timestamp(event_timestamp))
    ibes = pd.Timestamp(_as_timestamp(ibes_timestamp))
    earlier = min(ea, ibes)
    later = max(ea, ibes)

    start = earlier - event.US_RESEARCH_BUSINESS_DAY
    end = later + (2 if lane == "quotes" else 1) * event.US_RESEARCH_BUSINESS_DAY

    calendar_dates = [
        ts.date()
        for ts in pd.date_range(start.normalize(), end.normalize(), freq="D")
    ]
    return {
        "lane": lane,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "calendar_dates": [d.isoformat() for d in calendar_dates],
    }


def source_filename(exchange: str, trade_date: date | str, *, lane: str) -> str:
    d = trade_date if isinstance(trade_date, date) else date.fromisoformat(str(trade_date))
    exch = str(exchange).strip()
    if not exch:
        raise ValueError("exchange is required")
    if lane == "quotes":
        return f"{exch}-Quotes-{d.isoformat()}.csv.gz"
    if lane == "trades":
        return f"{exch}-TradesParsed-{d.isoformat()}.csv.gz"
    raise ValueError("lane must be quotes or trades")


def event_output_filename(
    exchange: str,
    event_date: date | str,
    permno: int | str,
    *,
    lane: str,
) -> str:
    d = event_date if isinstance(event_date, date) else date.fromisoformat(str(event_date))
    exch = str(exchange).strip()
    if not exch:
        raise ValueError("exchange is required")
    p = str(permno).strip()
    if not p:
        raise ValueError("permno is required")
    if lane == "quotes":
        return f"{exch}-QuotesAroundEvent-{d.isoformat()}_{p}.csv.gz"
    if lane == "trades":
        return f"{exch}-TradesAroundEvent-{d.isoformat()}_{p}.csv.gz"
    raise ValueError("lane must be quotes or trades")


def filter_rows_to_ric(
    rows: Iterable[Mapping[str, object]],
    ric: str,
) -> list[dict[str, object]]:
    target = str(ric).strip()
    if not target:
        raise ValueError("ric is required")
    return [
        dict(row)
        for row in rows
        if str(row.get("#RIC") or row.get("RIC") or "").strip() == target
    ]


def build_event_slice_plan(
    *,
    permno: int | str,
    ric: str,
    exchange: str,
    event_timestamp: datetime | str,
    ibes_timestamp: datetime | str,
) -> dict[str, object]:
    ea = _as_timestamp(event_timestamp)
    quote_window = event_slice_window(ea, ibes_timestamp, lane="quotes")
    trade_window = event_slice_window(ea, ibes_timestamp, lane="trades")

    return {
        "schema_version": "1",
        "permno": str(permno),
        "ric": str(ric),
        "exchange": str(exchange),
        "event_timestamp": ea.isoformat(timespec="microseconds"),
        "ibes_timestamp": _as_timestamp(ibes_timestamp).isoformat(timespec="microseconds"),
        "quotes": {
            **quote_window,
            "source_files": [
                source_filename(exchange, d, lane="quotes")
                for d in quote_window["calendar_dates"]
            ],
            "output_file": event_output_filename(
                exchange, ea.date(), permno, lane="quotes"
            ),
        },
        "trades": {
            **trade_window,
            "source_files": [
                source_filename(exchange, d, lane="trades")
                for d in trade_window["calendar_dates"]
            ],
            "output_file": event_output_filename(
                exchange, ea.date(), permno, lane="trades"
            ),
        },
        "coverage_claim": False,
    }
