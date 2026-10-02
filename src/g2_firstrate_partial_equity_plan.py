from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_TRADE_REQUIREMENTS = Path("data/processed/g2_vendor_requests/tickdata_equity_trades.csv")
DEFAULT_QUOTE_REQUIREMENTS = Path("data/processed/g2_vendor_requests/tickdata_equity_nbbo_quotes.csv")
DEFAULT_SNAPSHOT = Path("data/processed/g2_vendor_requests/firstrate_public_sample_snapshot.json")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"trade_date", "historical_symbols", "symbol_date_pair_count", "record_kind"}
    if not rows:
        raise ValueError(f"{path}: empty requirements")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    return rows


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_plan(trades: list[dict[str, str]], quotes: list[dict[str, str]], snapshot: dict) -> dict:
    if len(trades) != 414 or len(quotes) != 414:
        raise ValueError("expected 414 frozen equity trade rows and 414 equity quote rows")

    by_trade = {r["trade_date"]: r for r in trades}
    by_quote = {r["trade_date"]: r for r in quotes}
    if set(by_trade) != set(by_quote):
        raise ValueError("equity trade/quote date sets differ")

    present = set(snapshot["required_symbol_comparison"]["direct_present_symbols"])
    absent = set(snapshot["required_symbol_comparison"]["direct_absent_symbols"])
    if len(present) != 106 or len(absent) != 40 or present & absent:
        raise ValueError("FirstRate ticker snapshot does not reconcile to 106 present / 40 absent")

    direct_pairs = 0
    missing_pairs = 0
    dates_with_any_direct = 0
    fully_direct_dates = 0
    dates_with_no_direct = 0
    per_date = []

    for day in sorted(by_trade):
        trade = by_trade[day]
        quote = by_quote[day]
        if trade["historical_symbols"] != quote["historical_symbols"]:
            raise ValueError(f"{day}: equity trade/quote symbol sets differ")

        symbols = [s for s in trade["historical_symbols"].split(";") if s]
        direct = sorted(s for s in symbols if s in present)
        missing = sorted(s for s in symbols if s not in present)

        direct_pairs += len(direct)
        missing_pairs += len(missing)
        if direct:
            dates_with_any_direct += 1
        else:
            dates_with_no_direct += 1
        if not missing:
            fully_direct_dates += 1

        per_date.append({
            "trade_date": day,
            "required_symbol_count": len(symbols),
            "direct_present_symbol_count": len(direct),
            "missing_symbol_count": len(missing),
            "direct_present_symbols": direct,
            "missing_symbols": missing,
            "fully_direct": not missing,
        })

    total_pairs = sum(int(r["symbol_date_pair_count"]) for r in trades)
    if total_pairs != 3828 or direct_pairs + missing_pairs != total_pairs:
        raise ValueError("equity pair counts do not reconcile")

    return {
        "schema_version": "1",
        "purpose": (
            "Planning-only FirstRate Data partial equity candidate analysis for G2_CHAMPION_MINIMUM. "
            "Direct active-ticker matches are counted only as sourcing candidates; no authorization, "
            "purchase, delivery, or G2 coverage is claimed."
        ),
        "status": "PARTIAL_CANDIDATE_ONLY",
        "required_equity_source_date_rows": 828,
        "required_equity_symbol_date_pairs_per_record_kind": total_pairs,
        "direct_present_unique_symbols": len(present),
        "direct_absent_unique_symbols": len(absent),
        "direct_symbol_date_pairs_per_record_kind": direct_pairs,
        "missing_symbol_date_pairs_per_record_kind": missing_pairs,
        "direct_record_kind_symbol_date_pairs": direct_pairs * 2,
        "missing_record_kind_symbol_date_pairs": missing_pairs * 2,
        "direct_pair_fraction": direct_pairs / total_pairs,
        "dates_with_any_direct_symbols": dates_with_any_direct,
        "fully_direct_dates": fully_direct_dates,
        "dates_with_no_direct_symbols": dates_with_no_direct,
        "fully_direct_source_date_rows": fully_direct_dates * 2,
        "public_sample_schema_supports_required_quote_sizes": True,
        "delisted_tickers_supported_by_tick_service": False,
        "pricing_structure_fully_resolved": bool(
            snapshot["public_product_facts"]["pricing_structure_fully_resolved"]
        ),
        "policy": {
            "alias_inference_not_counted": True,
            "missing_symbols_require_another_authorized_source": True,
            "partial_files_do_not_count_as_complete_source_dates_by_themselves": True,
            "license_and_production_validation_required": True,
        },
        "per_date": per_date,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FirstRate partial G2 equity candidate plan.")
    parser.add_argument("--trade-requirements", type=Path, default=DEFAULT_TRADE_REQUIREMENTS)
    parser.add_argument("--quote-requirements", type=Path, default=DEFAULT_QUOTE_REQUIREMENTS)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = build_plan(
        _read_csv(args.trade_requirements),
        _read_csv(args.quote_requirements),
        _read_json(args.snapshot),
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
