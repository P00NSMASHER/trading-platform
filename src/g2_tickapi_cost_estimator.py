from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_TRADES = Path("data/processed/g2_vendor_requests/tickdata_equity_trades.csv")
DEFAULT_QUOTES = Path("data/processed/g2_vendor_requests/tickdata_equity_nbbo_quotes.csv")

PRICING_SOURCE_URL = "https://www.tickdata.com/data-delivery/tickapi"
PRICING_AS_OF = "2026-10-02"

# Published Global Equity Data schedule, progressive tiers by cumulative unique symbol-months.
EQUITY_TIERS = (
    (600, 2.33),
    (1200, 2.00),
    (3000, 1.33),
    (6000, 1.00),
    (12000, 0.67),
    (30000, 0.53),
    (60000, 0.47),
    (120000, 0.29),
    (300000, 0.23),
    (600000, 0.20),
)
REQUEST_FEE_USD = 0.03
MONTHLY_MINIMUM_USD = 250.0
ANNUAL_SUPPORT_FEE_USD = 250.0
MINIMUM_TERM_MONTHS = 12


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"trade_date", "historical_symbols"}
    if not rows:
        raise ValueError(f"{path}: empty manifest")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    return rows


def _date_symbol_sets(rows: list[dict[str, str]]) -> dict[str, tuple[str, ...]]:
    out = {}
    for row in rows:
        day = row["trade_date"]
        symbols = tuple(s for s in row["historical_symbols"].split(";") if s)
        if day in out and out[day] != symbols:
            raise ValueError(f"{day}: inconsistent symbol sets")
        out[day] = symbols
    return out


def unique_symbol_months(
    trade_rows: list[dict[str, str]],
    quote_rows: list[dict[str, str]],
) -> tuple[set[tuple[str, str]], set[str]]:
    trades = _date_symbol_sets(trade_rows)
    quotes = _date_symbol_sets(quote_rows)
    if trades != quotes:
        raise ValueError("trade and quote request manifests must have identical date/symbol coverage")

    pairs: set[tuple[str, str]] = set()
    months: set[str] = set()
    for day, symbols in trades.items():
        month = day[:7]
        months.add(month)
        for symbol in symbols:
            pairs.add((symbol, month))
    return pairs, months


def progressive_data_cost(symbol_months: int) -> float:
    if symbol_months < 0:
        raise ValueError("symbol_months must be >= 0")
    remaining = symbol_months
    previous_cap = 0
    total = 0.0
    for cap, rate in EQUITY_TIERS:
        width = cap - previous_cap
        take = min(remaining, width)
        if take > 0:
            total += take * rate
            remaining -= take
        previous_cap = cap
        if remaining == 0:
            break
    if remaining:
        raise ValueError("symbol-month count exceeds published pricing schedule")
    return round(total, 2)


def estimate(
    trade_rows: list[dict[str, str]],
    quote_rows: list[dict[str, str]],
) -> dict:
    pairs, months = unique_symbol_months(trade_rows, quote_rows)
    data_cost = progressive_data_cost(len(pairs))

    # /download supports multiple symbols. Use one monthly request if a single request can
    # return both needed data kinds, or two per month as a conservative separate-data-kind case.
    combined_requests = len(months)
    separate_requests = 2 * len(months)
    combined_request_fees = round(combined_requests * REQUEST_FEE_USD, 2)
    separate_request_fees = round(separate_requests * REQUEST_FEE_USD, 2)

    idle_month_minimum = (MINIMUM_TERM_MONTHS - 1) * MONTHLY_MINIMUM_USD
    first_year_combined = round(
        data_cost + combined_request_fees + idle_month_minimum + ANNUAL_SUPPORT_FEE_USD,
        2,
    )
    first_year_separate = round(
        data_cost + separate_request_fees + idle_month_minimum + ANNUAL_SUPPORT_FEE_USD,
        2,
    )

    return {
        "schema_version": "1",
        "purpose": (
            "Planning-only TickAPI estimate for the frozen G2_CHAMPION_MINIMUM equity scope. "
            "No API call, subscription, order, or purchase is performed."
        ),
        "pricing_source_url": PRICING_SOURCE_URL,
        "pricing_as_of": PRICING_AS_OF,
        "unique_symbol_months": len(pairs),
        "unique_calendar_months": len(months),
        "published_data_usage_cost_usd": data_cost,
        "combined_request_count": combined_requests,
        "combined_request_fees_usd": combined_request_fees,
        "separate_trade_quote_request_count": separate_requests,
        "separate_trade_quote_request_fees_usd": separate_request_fees,
        "monthly_minimum_usd": MONTHLY_MINIMUM_USD,
        "minimum_term_months": MINIMUM_TERM_MONTHS,
        "annual_support_fee_usd": ANNUAL_SUPPORT_FEE_USD,
        "estimated_first_year_minimum_combined_requests_usd": first_year_combined,
        "estimated_first_year_minimum_separate_requests_usd": first_year_separate,
        "excludes": ["sales tax", "pricing changes", "flat-rate/custom discounts", "other data usage"],
        "note": (
            "Published TickAPI pricing says additional calls for symbols/dates already requested "
            "within the same billing period are not charged again for data, only the request fee. "
            "Actual commercial terms must be verified before any purchase."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Estimate TickAPI cost for frozen G2 equities.")
    parser.add_argument("--trades", type=Path, default=DEFAULT_TRADES)
    parser.add_argument("--quotes", type=Path, default=DEFAULT_QUOTES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = estimate(_read(args.trades), _read(args.quotes))
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
