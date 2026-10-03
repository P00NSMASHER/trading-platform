from __future__ import annotations

from datetime import date, datetime, time, timedelta
import math
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

US_RESEARCH_BUSINESS_DAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())
EXTENDED_OPEN = time(4, 0)
EXTENDED_CLOSE = time(20, 0)


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value)
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)
    return parsed


def align_utc_partitioned_trade_rows(
    target_date: date,
    current_partition_rows: Iterable[Mapping[str, object]],
    next_partition_rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """
    Reproduce the original TRTH AlignDates.py behavior.

    TRTH raw daily partitions use UTC cutoffs, so a U.S. after-hours trade can
    land in the following UTC-day file. The original research rebuilt an ET
    calendar-day file by retaining rows whose classified Date equals the target
    date from BOTH the current UTC partition and the following UTC partition.
    """
    target = target_date.isoformat()
    out: list[dict[str, object]] = []
    for row in list(current_partition_rows) + list(next_partition_rows):
        if str(row.get("Date", ""))[:10] == target:
            out.append(dict(row))
    return out


def in_extended_hours(timestamp: object) -> bool:
    clock = _timestamp(timestamp).time()
    return EXTENDED_OPEN <= clock <= EXTENDED_CLOSE


def clean_quote_for_original_resample(row: Mapping[str, object]) -> dict[str, object]:
    """
    Match ExtractQuotesAfterEarningsResample.py quote cleaning.

    Bid price becomes missing when bid size is zero, bid price is zero, or the
    original NoQuote qualifier is set. Ask price receives the symmetric rule.
    Sizes remain untouched, matching the source code.
    """
    out = dict(row)
    flags = dict(out.get("qualifier_flags") or {})
    no_quote = bool(flags.get("no_quote"))

    bid = out.get("bid")
    bid_size = out.get("bid_size")
    ask = out.get("ask")
    ask_size = out.get("ask_size")

    if no_quote or float(bid or 0) == 0.0 or float(bid_size or 0) == 0.0:
        out["bid"] = None
    if no_quote or float(ask or 0) == 0.0 or float(ask_size or 0) == 0.0:
        out["ask"] = None
    return out


def keep_regular_trade_for_original_resample(row: Mapping[str, object]) -> bool:
    """
    Match ExtractTradesAfterEarningsResample.py's regular-trade filter.
    """
    flags = dict(row.get("qualifier_flags") or {})
    return not any(
        bool(flags.get(name))
        for name in (
            "next_day",
            "prior_reference_price",
            "derivatively_priced",
            "sold_out_of_sequence",
        )
    )


def research_open_timestamp(event_date: date, event_timestamp: datetime) -> datetime:
    """
    Match the companion scripts' opening-cross anchor.

    The source workflow anchors at 09:30 on event_date. If the announcement is
    after noon, it shifts that anchor by one CustomBusinessDay constructed with
    USFederalHolidayCalendar, exactly as the original code does.
    """
    anchor = datetime.combine(event_date, time(9, 30))
    if event_timestamp.time() > time(12, 0):
        return (pd.Timestamp(anchor) + US_RESEARCH_BUSINESS_DAY).to_pydatetime()
    return anchor


def quote_event_grids(
    event_timestamp: datetime,
    event_date: date,
) -> dict[str, list[datetime]]:
    """
    Reproduce the four quote grids from ExtractQuotesAfterEarningsResample.py.
    """
    opening = research_open_timestamp(event_date, event_timestamp)
    return {
        "announcement_1s": [
            event_timestamp + timedelta(seconds=x) for x in range(-300, 301)
        ],
        "announcement_1m": [
            event_timestamp + timedelta(minutes=x) for x in range(-5, 121)
        ],
        "opening_1s": [
            opening + timedelta(seconds=x) for x in range(-300, 301)
        ],
        "opening_1m": [
            opening + timedelta(minutes=x) for x in range(-5, 121)
        ],
    }


def trade_event_grid(
    event_timestamp: datetime,
    event_date: date,
    *,
    after_open_minutes: int = 30,
) -> list[datetime]:
    """
    Reproduce ExtractTradesAfterEarningsResample.py's one-minute event grid.

    Grid begins five minutes before the announcement and extends through
    30 minutes after the relevant 09:30 opening cross.
    """
    opening = research_open_timestamp(event_date, event_timestamp)
    minutes_to_open = int(
        math.ceil((opening - event_timestamp).total_seconds() / 60)
    )
    max_minute = minutes_to_open + after_open_minutes
    return [
        event_timestamp + timedelta(minutes=x)
        for x in range(-5, max_minute + 1)
    ]


def _rows_frame(rows: Sequence[Mapping[str, object]], value_columns: list[str]) -> pd.DataFrame:
    frame = pd.DataFrame([dict(row) for row in rows])
    if frame.empty:
        empty = pd.DataFrame({"Timestamp": pd.Series(dtype="datetime64[ns]")})
        for column in value_columns:
            empty[column] = pd.Series(dtype="float64")
        return empty[["Timestamp", *value_columns]]
    frame = frame.copy()
    frame["Timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame[["Timestamp", *value_columns]].sort_values("Timestamp")


def resample_quotes_original(
    rows: Sequence[Mapping[str, object]],
    event_timestamp: datetime,
    event_date: date,
) -> dict[str, pd.DataFrame]:
    """
    Apply the source research quote cleaning and backward merge_asof behavior.
    """
    cleaned = [
        clean_quote_for_original_resample(row)
        for row in rows
        if in_extended_hours(row["timestamp"])
    ]
    quotes = _rows_frame(cleaned, ["bid", "bid_size", "ask", "ask_size"])
    grids = quote_event_grids(event_timestamp, event_date)
    outputs: dict[str, pd.DataFrame] = {}

    for name, timestamps in grids.items():
        target = pd.DataFrame({"Timestamp": pd.to_datetime(timestamps)})
        sampled = pd.merge_asof(target, quotes, on="Timestamp")
        if name.endswith("1s"):
            anchor = event_timestamp if name.startswith("announcement") else research_open_timestamp(event_date, event_timestamp)
            sampled["SecondsAfter"] = (
                sampled["Timestamp"] - pd.Timestamp(anchor)
            ).dt.total_seconds().astype(int)
        else:
            anchor = event_timestamp if name.startswith("announcement") else research_open_timestamp(event_date, event_timestamp)
            sampled["MinutesAfter"] = (
                (sampled["Timestamp"] - pd.Timestamp(anchor)).dt.total_seconds() / 60
            ).astype(int)
        outputs[name] = sampled
    return outputs


def resample_trades_original(
    rows: Sequence[Mapping[str, object]],
    event_timestamp: datetime,
    event_date: date,
) -> pd.DataFrame:
    """
    Apply the source research regular-trade filter and one-minute merge_asof.

    The original trade resample uses a one-minute backward tolerance.
    """
    filtered = [
        row
        for row in rows
        if keep_regular_trade_for_original_resample(row)
        and in_extended_hours(row["timestamp"])
    ]
    trades = _rows_frame(filtered, ["price"])
    timestamps = trade_event_grid(event_timestamp, event_date)
    target = pd.DataFrame({"Timestamp": pd.to_datetime(timestamps)})
    sampled = pd.merge_asof(
        target,
        trades,
        on="Timestamp",
        tolerance=pd.Timedelta(minutes=1),
    )
    sampled["MinutesAfter"] = (
        (sampled["Timestamp"] - pd.Timestamp(event_timestamp)).dt.total_seconds() / 60
    ).astype(int)
    opening = research_open_timestamp(event_date, event_timestamp)
    sampled["MinutesAfterOpen"] = (
        (sampled["Timestamp"] - pd.Timestamp(opening)).dt.total_seconds() / 60
    ).astype(int)
    return sampled


def after_hours_form_t_trades(
    rows: Sequence[Mapping[str, object]],
    event_timestamp: datetime,
    event_date: date,
) -> list[dict[str, object]]:
    """
    Match ExtractTradesAfterNewsBeforeOpen.py's event-to-open Form-T selection.
    """
    opening = research_open_timestamp(event_date, event_timestamp)
    return [
        dict(row)
        for row in rows
        if event_timestamp < _timestamp(row["timestamp"]) < opening
        and bool(dict(row.get("qualifier_flags") or {}).get("form_t"))
    ]
