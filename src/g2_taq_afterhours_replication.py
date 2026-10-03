from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

import g2_lseg_trth_event_pipeline as trth_event

EXCLUDED_TRADE_CONDITIONS = {"L", "P", "U", "Z", "4"}
AFTER_HOURS_TRADE_CONDITION = "T"
CLOSING_QUOTE_CONDITION = "C"


def condition_codes(value: object) -> set[str]:
    """
    Normalize TAQ condition fields into individual non-separator condition codes.

    TAQ sale/quote conditions are historically represented as compact or
    separator-delimited character fields. The replication instructions identify
    single-character codes, so compact strings such as "TZ" and delimited
    strings such as "T;Z" are treated equivalently.
    """
    raw = str(value or "").strip()
    return {
        char
        for char in raw
        if not char.isspace() and char not in {",", ";", "|", "/"}
    }


def trade_rejection_reason(row: Mapping[str, object]) -> str | None:
    """
    Apply the exact companion-repo TAQ trade exclusions.

    Exclude L, P, U, Z, and 4 under tr_scon. The after-hours marker T is not
    itself an exclusion and is exposed separately.
    """
    codes = condition_codes(row.get("tr_scon"))
    bad = sorted(codes & EXCLUDED_TRADE_CONDITIONS)
    if bad:
        return "excluded_tr_scon:" + "".join(bad)
    return None


def is_after_hours_trade(row: Mapping[str, object]) -> bool:
    return AFTER_HOURS_TRADE_CONDITION in condition_codes(row.get("tr_scon"))


def keep_trade_for_replication(row: Mapping[str, object]) -> bool:
    return trade_rejection_reason(row) is None


def quote_replication_flags(row: Mapping[str, object]) -> dict[str, bool]:
    """
    Annotate the quote states that the companion README says must NOT be deleted.

    These flags are evidence for research cleaning; they are not canonical quote
    validation and do not imply G2 coverage.
    """
    bid = row.get("Bid", row.get("Best_Bid"))
    ask = row.get("Ask", row.get("Best_Ask"))
    bid_size = row.get("Bidsiz", row.get("Best_Bidsiz"))
    ask_size = row.get("Asksiz", row.get("Best_Asksiz"))

    def number(value: object) -> float | None:
        if value in (None, "", "."):
            return None
        return float(value)

    b = number(bid)
    a = number(ask)
    bs = number(bid_size)
    a_s = number(ask_size)

    bid_missing_or_withdrawn = b is None or b <= 0 or bs is None or bs <= 0
    ask_missing_or_withdrawn = a is None or a <= 0 or a_s is None or a_s <= 0

    crossed = b is not None and a is not None and b > a
    spread = None if b is None or a is None else a - b
    wide_spread = spread is not None and spread > 5

    return {
        "closing_condition": CLOSING_QUOTE_CONDITION
        in condition_codes(row.get("qu_cond")),
        "empty_quote": bid_missing_or_withdrawn and ask_missing_or_withdrawn,
        "withdrawn_bid": bid_missing_or_withdrawn,
        "withdrawn_ask": ask_missing_or_withdrawn,
        "crossed_market": crossed,
        "wide_spread_over_5": wide_spread,
        "retain_for_after_hours_replication": True,
    }


def keep_quote_for_replication(row: Mapping[str, object]) -> bool:
    """
    The paper's TAQ replication instructions explicitly retain problematic quote
    updates in after-hours analysis instead of deleting them.

    Therefore this function returns True for empty, crossed, wide-spread, and
    withdrawn quotes. Downstream NBBO construction and canonical validation stay
    fail-closed and separate.
    """
    quote_replication_flags(row)
    return True


def in_research_extended_hours(timestamp: object) -> bool:
    """
    Use the 04:00-20:00 extended-hours window recovered from the original TRTH
    processing scripts so the TAQ parity route uses the same event-time envelope.
    """
    return trth_event.in_extended_hours(timestamp)


def filter_trade_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    extended_hours_only: bool = False,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for raw in rows:
        row = dict(raw)
        if not keep_trade_for_replication(row):
            continue
        if extended_hours_only:
            timestamp = row.get("timestamp")
            if timestamp in (None, "") or not in_research_extended_hours(timestamp):
                continue
        row["after_hours_condition_T"] = is_after_hours_trade(row)
        row["taq_replication_rejection_reason"] = None
        out.append(row)
    return out


def annotate_quote_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    extended_hours_only: bool = False,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for raw in rows:
        row = dict(raw)
        if extended_hours_only:
            timestamp = row.get("timestamp")
            if timestamp in (None, "") or not in_research_extended_hours(timestamp):
                continue
        row["taq_replication_flags"] = quote_replication_flags(row)
        row["taq_replication_retained"] = True
        row["g2_coverage_claim"] = False
        out.append(row)
    return out


def replication_policy_summary() -> dict[str, object]:
    return {
        "schema_version": "1",
        "trade_excluded_tr_scon": sorted(EXCLUDED_TRADE_CONDITIONS),
        "after_hours_trade_condition": AFTER_HOURS_TRADE_CONDITION,
        "quote_valid_condition_addition": CLOSING_QUOTE_CONDITION,
        "quote_deletions_disabled": [
            "empty_quotes",
            "wide_spreads",
            "crossed_markets",
            "withdrawn_quotes",
        ],
        "extended_hours_window": "04:00-20:00 America/New_York",
        "nbbo_required_before_g2_quote_coverage": True,
        "g2_coverage_claim": False,
    }
