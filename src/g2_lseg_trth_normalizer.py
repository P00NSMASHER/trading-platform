from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Mapping

EARLY_CLOSE_DATES = {
    date(2011, 11, 25),
    date(2012, 7, 3),
    date(2012, 11, 23),
    date(2012, 12, 24),
    date(2013, 7, 3),
    date(2013, 11, 29),
    date(2013, 12, 24),
    date(2014, 7, 3),
    date(2014, 11, 28),
    date(2014, 12, 24),
    date(2015, 11, 27),
    date(2015, 12, 24),
}

OPRA_NONROOT_LEN = 10
OPRA_EXCHANGE_CODE = "U"
CALL_MONTH_CODES = "ABCDEFGHIJKL"
PUT_MONTH_CODES = "MNOPQRSTUVWX"


def parse_tick_history_timestamp(value: object) -> datetime:
    """
    Parse modern LSEG Tick History `Date-Time` values.

    Live DataScope/Tick History exports are expected to carry an explicit UTC
    offset (or trailing Z). Fail closed on naive timestamps so the downstream
    market-data adapter never has to guess a timezone.
    """
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("missing Tick History Date-Time")
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"unsupported Tick History Date-Time: {raw!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("Tick History Date-Time must include a timezone offset")
    return parsed


def parse_opra_option_ric(value: object) -> dict[str, object]:
    """
    Decode the historical OPRA RIC layout used by LSEG/Refinitiv.

    The public datascope-cli parser documents a 10-character non-root suffix:
    month/type code, expiration day, two-digit year, and five-digit strike.
    Uppercase month codes encode strikes below 1000 at /100 precision; lower-
    case month codes encode strikes >=1000 at /10 precision.
    """
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("missing option RIC")
    try:
        body, exchange_code = raw.rsplit(".", 1)
    except ValueError as exc:
        raise ValueError(f"option RIC missing exchange suffix: {raw!r}") from exc
    if exchange_code != OPRA_EXCHANGE_CODE:
        raise ValueError(f"unsupported option RIC exchange suffix: {exchange_code!r}")
    if len(body) <= OPRA_NONROOT_LEN:
        raise ValueError(f"option RIC too short: {raw!r}")

    root = body[:-OPRA_NONROOT_LEN]
    month_code_raw = body[-10]
    month_code = month_code_raw.upper()
    expiry_day = int(body[-9:-7])
    year_2 = int(body[-7:-5])
    expiry_year = 2000 + year_2 if year_2 <= 72 else 1900 + year_2

    if month_code in CALL_MONTH_CODES:
        option_type = "call"
        expiry_month = CALL_MONTH_CODES.index(month_code) + 1
    elif month_code in PUT_MONTH_CODES:
        option_type = "put"
        expiry_month = PUT_MONTH_CODES.index(month_code) + 1
    else:
        raise ValueError(f"unsupported option month/type code: {month_code_raw!r}")

    expiry = date(expiry_year, expiry_month, expiry_day).isoformat()
    try:
        strike_raw = float(body[-5:])
    except ValueError as exc:
        raise ValueError(f"invalid option RIC strike: {raw!r}") from exc
    strike = strike_raw / (10.0 if month_code_raw.islower() else 100.0)
    if strike <= 0:
        raise ValueError("option strike must be positive")

    return {
        "underlying_symbol": root,
        "option_symbol": body,
        "expiration": expiry,
        "strike": strike,
        "option_type": option_type,
        "source_ric": raw,
    }


def parse_trth_date(value: str) -> datetime:
    value = str(value or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(f"unsupported TRTH date: {value!r}")


def parse_trth_time(value: str) -> timedelta:
    value = str(value or "").strip()
    if not value:
        raise ValueError("missing TRTH time")
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(f"unsupported TRTH time: {value!r}")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    whole = int(seconds)
    micros = round((seconds - whole) * 1_000_000)
    return timedelta(hours=hours, minutes=minutes, seconds=whole, microseconds=micros)


def _offset_hours(value: object) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def reconstruct_quote_timestamp(row: Mapping[str, object]) -> datetime:
    """
    Reproduce the original research quote timestamp rule.

    Quote Time is preferred; Time[G] is the fallback. The difference between
    Time[G] and Quote Time is wrapped across midnight when it exceeds 23 hours,
    then GMT Offset is applied exactly as in the source research code.
    """
    trth_time = parse_trth_time(str(row.get("Time[G]", "")))
    source_raw = row.get("Quote Time")
    source_time = parse_trth_time(str(source_raw if source_raw not in (None, "") else row.get("Time[G]", "")))
    diff = trth_time - source_time
    if diff > timedelta(hours=23):
        diff -= timedelta(hours=24)
    elif diff < timedelta(hours=-23):
        diff += timedelta(hours=24)

    return (
        parse_trth_date(str(row.get("Date[G]", "")))
        + trth_time
        - diff
        + timedelta(hours=_offset_hours(row.get("GMT Offset")))
    )


def reconstruct_trade_timestamp(row: Mapping[str, object]) -> datetime:
    """
    Reproduce the original research trade timestamp rule.

    Trd/Qte Date is preferred; Date[G] is the fallback. Exch Time supplies the
    clock and GMT Offset is then applied.
    """
    raw_date = row.get("Trd/Qte Date")
    date_value = raw_date if raw_date not in (None, "") else row.get("Date[G]", "")
    return (
        parse_trth_date(str(date_value))
        + parse_trth_time(str(row.get("Exch Time", "")))
        + timedelta(hours=_offset_hours(row.get("GMT Offset")))
    )


def _float(row: Mapping[str, object], key: str) -> float:
    value = row.get(key)
    if value in (None, ""):
        raise ValueError(f"missing {key}")
    return float(value)


def quote_qualifier_flags(value: object) -> dict[str, bool]:
    pieces = [p.strip() for p in str(value or "").split(";") if p.strip()]

    def has(code: str) -> bool:
        for piece in pieces:
            if piece.endswith("[PRC_QL_CD]") and piece[:-11].strip() == code:
                return True
            if piece.endswith("[PRC_QL3]") and piece[:-9].strip() == code:
                return True
        return False

    return {
        "regular": has("R"),
        "opening": has("OQ"),
        "closing": has("CQ"),
        "no_quote": has("NQ"),
    }


def trade_qualifier_flags(value: object) -> dict[str, bool]:
    pieces = [p.strip() for p in str(value or "").split(";") if p.strip()]

    def contains(code: str) -> bool:
        for piece in pieces:
            if piece.endswith("_TEXT]") and code in piece[:-10]:
                return True
            if piece.endswith("[LSTSALCOND]") and code in piece[:-12]:
                return True
        return False

    return {
        "form_t": contains("T"),
        "opening": contains("O") or "O [CTS_QUAL]" in pieces,
        "closing": contains("6"),
        "cross": contains("X"),
        "sweep": contains("F"),
        "next_day": contains("N"),
        "bunched": contains("B"),
        "prior_reference_price": contains("P"),
        "extended_hours_soos": contains("U"),
        "derivatively_priced": contains("4"),
        "average_trade_price": contains("W"),
        "cash_sale": contains("C"),
        "sold_out_of_sequence": contains("Z"),
        "odd_lot": any(p in {"ODT[IRGCOND]", "ODD[IRGCOND]"} for p in pieces),
    }


def is_early_close(day: date | datetime) -> bool:
    value = day.date() if isinstance(day, datetime) else day
    return value in EARLY_CLOSE_DATES


def normalize_equity_trade(row: Mapping[str, object], historical_symbol: str) -> dict[str, object]:
    if str(row.get("Type", "Trade")) != "Trade":
        raise ValueError("row is not a Trade")
    price = _float(row, "Price")
    size = _float(row, "Volume")
    if price <= 0 or size <= 0:
        raise ValueError("trade price and volume must be positive")
    timestamp = (
        parse_tick_history_timestamp(row.get("Date-Time"))
        if row.get("Date-Time") not in (None, "")
        else reconstruct_trade_timestamp(row)
    )
    return {
        "timestamp": timestamp.isoformat(timespec="microseconds"),
        "symbol": historical_symbol,
        "price": price,
        "size": size,
        "source_ric": str(row.get("#RIC", "")),
        "exchange": str(row.get("Ex/Cntrb.ID", "") or ""),
        "qualifier_flags": trade_qualifier_flags(row.get("Qualifiers")),
    }


def normalize_equity_quote(row: Mapping[str, object], historical_symbol: str) -> dict[str, object]:
    if str(row.get("Type", "Quote")) != "Quote":
        raise ValueError("row is not a Quote")
    bid = _float(row, "Bid Price")
    ask = _float(row, "Ask Price")
    bid_size = _float(row, "Bid Size")
    ask_size = _float(row, "Ask Size")
    if bid < 0 or ask <= 0 or bid > ask or bid_size < 0 or ask_size < 0:
        raise ValueError("invalid quote economics")
    timestamp = (
        parse_tick_history_timestamp(row.get("Date-Time"))
        if row.get("Date-Time") not in (None, "")
        else reconstruct_quote_timestamp(row)
    )
    return {
        "timestamp": timestamp.isoformat(timespec="microseconds"),
        "symbol": historical_symbol,
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "source_ric": str(row.get("#RIC", "")),
        "qualifier_flags": quote_qualifier_flags(row.get("Qualifiers")),
    }


def _option_metadata(
    metadata: Mapping[str, object] | None,
    row: Mapping[str, object] | None = None,
) -> dict[str, object]:
    supplied = dict(metadata or {})
    if row is not None and any(
        supplied.get(key) in (None, "")
        for key in ("underlying_symbol", "option_symbol", "expiration", "strike", "option_type")
    ):
        try:
            parsed = parse_opra_option_ric(row.get("#RIC"))
        except ValueError:
            if metadata:
                parsed = {}
            else:
                raise
        for key in ("underlying_symbol", "option_symbol", "expiration", "strike", "option_type"):
            if supplied.get(key) in (None, "") and key in parsed:
                supplied[key] = parsed[key]

    required = ("underlying_symbol", "option_symbol", "expiration", "strike", "option_type")
    missing = [key for key in required if supplied.get(key) in (None, "")]
    if missing:
        raise ValueError(f"missing option metadata: {', '.join(missing)}")
    metadata = supplied
    strike = float(metadata["strike"])
    if strike <= 0:
        raise ValueError("option strike must be positive")
    option_type = str(metadata["option_type"]).strip().lower()
    option_type = {"c": "call", "p": "put"}.get(option_type, option_type)
    if option_type not in {"call", "put"}:
        raise ValueError("option_type must be call or put")
    return {
        "underlying_symbol": str(metadata["underlying_symbol"]),
        "option_symbol": str(metadata["option_symbol"]),
        "expiration": str(metadata["expiration"]),
        "strike": strike,
        "option_type": option_type,
    }


def normalize_option_trade(
    row: Mapping[str, object],
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    meta = _option_metadata(metadata, row)
    base = normalize_equity_trade(row, historical_symbol=str(meta["option_symbol"]))
    base.update(meta)
    base["symbol"] = meta["option_symbol"]
    return base


def normalize_option_quote(
    row: Mapping[str, object],
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    meta = _option_metadata(metadata, row)
    base = normalize_equity_quote(row, historical_symbol=str(meta["option_symbol"]))
    base.update(meta)
    base["symbol"] = meta["option_symbol"]
    return base
