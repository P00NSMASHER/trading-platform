from __future__ import annotations

from datetime import date, datetime, time
import math
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

import g2_lseg_trth_event_pipeline as event

NASDAQ_LISTING_CODES = {"NAQ", "NMQ", "NSQ"}
NYSE_LISTING_CODES = {"ASQ", "NYQ", "PSQ"}
NASDAQ_PRIMARY_CONTRIBUTORS = {"NAS", "THM"}
NYSE_PRIMARY_CONTRIBUTORS = {"PSE", "NYS", "ASE"}

VOLUME_BINS = (0.0, 100.0, 500.0, 1000.0, math.inf)
VALUE_BINS = (0.0, 1000.0, 5000.0, 50000.0, math.inf)


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


def _float(row: Mapping[str, object], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return float(value)
    raise ValueError(f"missing numeric field; tried {keys}")


def _exchange(row: Mapping[str, object]) -> str:
    return str(row.get("exchange") or row.get("Ex/Cntrb.ID") or "").strip()


def _flags(row: Mapping[str, object]) -> dict[str, bool]:
    return {str(k): bool(v) for k, v in dict(row.get("qualifier_flags") or {}).items()}


def primary_contributor_codes(listing_exchange: str) -> set[str]:
    code = str(listing_exchange or "").strip().upper()
    if code in NASDAQ_LISTING_CODES:
        return set(NASDAQ_PRIMARY_CONTRIBUTORS)
    if code in NYSE_LISTING_CODES:
        return set(NYSE_PRIMARY_CONTRIBUTORS)
    raise ValueError(f"unknown listing exchange code: {listing_exchange!r}")


def after_hours_form_t_features(
    rows: Sequence[Mapping[str, object]],
    *,
    event_timestamp: datetime,
    event_date: date,
    listing_exchange: str,
) -> list[dict[str, object]]:
    """
    Reproduce the original ExtractTradesAfterNewsBeforeOpen.py feature sequence.

    The original workflow:
    - finds the last trade before the announcement for the return baseline,
    - selects Form-T trades strictly after the announcement and before the
      relevant 09:30 open,
    - marks ADF prints as dark,
    - marks listing-exchange primary prints from the original exchange-code map,
    - computes inter-trade duration, log returns, cumulative return, and TradeID.

    Rows are expected to be normalized TRTH trade rows with timestamp, price,
    size/volume, exchange, and qualifier_flags.
    """
    ordered = sorted((dict(row) for row in rows), key=lambda row: _timestamp(row["timestamp"]))
    previous = [row for row in ordered if _timestamp(row["timestamp"]) < event_timestamp]
    previous_price: float | None = None
    if previous:
        previous_price = _float(previous[-1], "price", "Price")
        if previous_price <= 0:
            raise ValueError("pre-announcement baseline trade price must be positive")

    opening = event.research_open_timestamp(event_date, event_timestamp)
    primary_codes = primary_contributor_codes(listing_exchange)
    selected = [
        row
        for row in ordered
        if event_timestamp < _timestamp(row["timestamp"]) < opening
        and _flags(row).get("form_t", False)
    ]
    if not selected:
        return []

    out: list[dict[str, object]] = []
    previous_timestamp = event_timestamp
    previous_log_price = math.log(previous_price) if previous_price is not None else math.nan
    cumulative = 0.0

    for index, row in enumerate(selected, start=1):
        ts = _timestamp(row["timestamp"])
        price = _float(row, "price", "Price")
        volume = _float(row, "size", "volume", "Volume")
        if price <= 0 or volume <= 0:
            raise ValueError("selected Form-T trade price and volume must be positive")

        log_price = math.log(price)
        log_return = (
            log_price - previous_log_price
            if not math.isnan(previous_log_price)
            else math.nan
        )
        if not math.isnan(log_return):
            cumulative += log_return

        flags = _flags(row)
        contributor = _exchange(row)
        out.append(
            {
                "trade_id": index,
                "timestamp": ts.isoformat(timespec="microseconds"),
                "exchange": contributor,
                "price": price,
                "volume": volume,
                "duration_seconds": (ts - previous_timestamp).total_seconds(),
                "log_price": log_price,
                "previous_log_price": previous_log_price,
                "log_return": log_return,
                "cumulative_log_return": cumulative if not math.isnan(log_return) else math.nan,
                "sweep": bool(flags.get("sweep")),
                "odd_lot": bool(flags.get("odd_lot")),
                "dark": contributor == "ADF",
                "primary": contributor in primary_codes,
            }
        )
        previous_timestamp = ts
        previous_log_price = log_price

    return out


def descriptive_sample_dates(
    *,
    event_timestamp: datetime,
    event_date: date,
) -> tuple[date, date]:
    """
    Match the original descriptive-stat script's pre/post sample-day anchors.
    """
    base = pd.Timestamp(event_date)
    if event_timestamp.time() <= time(12, 0):
        base = base - event.US_RESEARCH_BUSINESS_DAY
    pre_date = base.date()
    post_date = (base + event.US_RESEARCH_BUSINESS_DAY).date()
    return pre_date, post_date


def _bin_label(value: float, edges: tuple[float, ...]) -> str:
    for left, right in zip(edges, edges[1:]):
        if left <= value < right:
            right_label = "inf" if math.isinf(right) else str(int(right))
            return f"[{int(left)},{right_label})"
    raise ValueError(f"value {value} did not fit configured bins")


def descriptive_trade_stats(
    rows: Sequence[Mapping[str, object]],
    *,
    event_timestamp: datetime,
    event_date: date,
) -> dict[str, dict[str, object] | None]:
    """
    Reproduce the original pre_all/post_all descriptive trade distributions.

    Only non-Form-T trades are counted. Volume bins are
    [0,100), [100,500), [500,1000), [1000,inf). Dollar-value bins are
    [0,1000), [1000,5000), [5000,50000), [50000,inf).
    """
    pre_date, post_date = descriptive_sample_dates(
        event_timestamp=event_timestamp,
        event_date=event_date,
    )

    def summarize(target: date) -> dict[str, object] | None:
        sample = []
        for raw in rows:
            row = dict(raw)
            if _timestamp(row["timestamp"]).date() != target:
                continue
            if _flags(row).get("form_t", False):
                continue
            price = _float(row, "price", "Price")
            volume = _float(row, "size", "volume", "Volume")
            if price < 0 or volume < 0:
                raise ValueError("trade price and volume must be non-negative")
            sample.append((price, volume))

        if not sample:
            return None

        volume_counts = {f"volume_{_bin_label(left, VOLUME_BINS)}": 0 for left in VOLUME_BINS[:-1]}
        value_counts = {f"value_{_bin_label(left, VALUE_BINS)}": 0 for left in VALUE_BINS[:-1]}

        for price, volume in sample:
            value = price * volume
            volume_counts[f"volume_{_bin_label(volume, VOLUME_BINS)}"] += 1
            value_counts[f"value_{_bin_label(value, VALUE_BINS)}"] += 1

        n = len(sample)
        result: dict[str, object] = {"number_of_trades": n}
        result.update({key: count / n for key, count in volume_counts.items()})
        result.update({key: count / n for key, count in value_counts.items()})
        return result

    return {
        "pre_all": summarize(pre_date),
        "post_all": summarize(post_date),
    }
