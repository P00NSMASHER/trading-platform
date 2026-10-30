from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_TRADES = Path("data/processed/g2_vendor_requests/tickdata_equity_trades.csv")
DEFAULT_QUOTES = Path("data/processed/g2_vendor_requests/tickdata_equity_nbbo_quotes.csv")
SWITCH_DATE = "2013-01-01"


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path}: empty manifest")
    return rows


def _symbols(row: dict[str, str]) -> list[str]:
    return [s for s in row["historical_symbols"].split(";") if s]


def build_requests(trade_rows: list[dict[str, str]], quote_rows: list[dict[str, str]]) -> dict:
    if len(trade_rows) != len(quote_rows):
        raise ValueError("trade/quote row-count mismatch")

    pairs: list[dict[str, str]] = []
    unique_symbols: set[str] = set()

    for trade, quote in zip(trade_rows, quote_rows):
        if trade["trade_date"] != quote["trade_date"]:
            raise ValueError("trade/quote date mismatch")
        if trade["historical_symbols"] != quote["historical_symbols"]:
            raise ValueError(f"{trade['trade_date']}: trade/quote symbol mismatch")
        symbols = _symbols(trade)
        if len(symbols) != int(trade["symbol_date_pair_count"]):
            raise ValueError(f"{trade['trade_date']}: trade pair-count mismatch")
        if len(symbols) != int(quote["symbol_date_pair_count"]):
            raise ValueError(f"{quote['trade_date']}: quote pair-count mismatch")

        for symbol in symbols:
            pairs.append({"smbl": symbol, "dates": trade["trade_date"].replace("-", "")})
            unique_symbols.add(symbol)

    if len({(p["smbl"], p["dates"]) for p in pairs}) != len(pairs):
        raise ValueError("duplicate symbol/date pair in frozen G2 manifest")

    legacy = [p for p in pairs if p["dates"] < SWITCH_DATE.replace("-", "")]
    msec = [p for p in pairs if p["dates"] >= SWITCH_DATE.replace("-", "")]

    return {
        "schema_version": "2",
        "access_contract": {
            "personal_direct_wrds_access": false,
            "execution_requires": "current institution/entity WRDS authorization and applicable TAQ entitlement",
            "support_ticket": "WRDS #157666 (2026-10-05): no individual subscriptions; no alternative-platform referral",
            "coverage_authority": false,
        },
        "purpose": (
            "Dry-run WRDS TAQ request manifest derived from the frozen G2 equity scope. "
            "This artifact performs no WRDS login, query, download, or coverage claim."
        ),
        "source_logic": {
            "upstream_reference": "https://github.com/gen-li/Extract_TAQ_from_WRDS_Cloud",
            "legacy_tables": ["taq.ct_YYYYMMDD", "taq.cq_YYYYMMDD"],
            "millisecond_tables": ["taqmsec.ctm_YYYYMMDD", "taqmsec.cqm_YYYYMMDD"],
            "switch_date": SWITCH_DATE,
            "note": (
                "Consolidated quote rows are quote inputs; strict NBBO coverage must be "
                "constructed or validated downstream before G2 coverage is counted."
            ),
        },
        "source_date_rows": len(trade_rows),
        "symbol_date_pairs": len(pairs),
        "unique_symbols": len(unique_symbols),
        "legacy_symbol_date_pairs": len(legacy),
        "millisecond_symbol_date_pairs": len(msec),
        "legacy": legacy,
        "millisecond": msec,
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["smbl", "dates"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build dry-run WRDS TAQ symbol/date request manifests.")
    parser.add_argument("--trades", type=Path, default=DEFAULT_TRADES)
    parser.add_argument("--quotes", type=Path, default=DEFAULT_QUOTES)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    payload = build_requests(_read(args.trades), _read(args.quotes))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.output_dir / "legacy_symbol_dates.csv", payload["legacy"])
    _write_csv(args.output_dir / "millisecond_symbol_dates.csv", payload["millisecond"])

    summary = {k: v for k, v in payload.items() if k not in {"legacy", "millisecond"}}
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
