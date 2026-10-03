from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

from g2_lseg_historical_ric_validator import row_trade_date
from g2_lseg_trth_normalizer import (
    normalize_equity_quote,
    normalize_equity_trade,
    normalize_option_quote,
    normalize_option_trade,
    quote_qualifier_flags,
)


EQUITY_TRADE_FIELDS = [
    "timestamp", "symbol", "price", "size", "exchange", "conditions",
]
EQUITY_QUOTE_FIELDS = [
    "timestamp", "symbol", "bid", "ask", "bid_size", "ask_size",
    "exchange", "conditions",
]
OPTION_TRADE_FIELDS = [
    "timestamp", "symbol", "underlying_symbol", "option_symbol",
    "expiration", "strike", "option_type", "price", "size",
    "exchange", "conditions",
]
OPTION_QUOTE_FIELDS = [
    "timestamp", "symbol", "underlying_symbol", "option_symbol",
    "expiration", "strike", "option_type", "bid", "ask",
    "bid_size", "ask_size", "exchange", "conditions",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_text(path: Path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def read_rows(path: Path) -> list[dict[str, str]]:
    with _open_text(path) as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def equity_ric_map(validation_payload: Mapping[str, object]) -> dict[str, str]:
    results = list(validation_payload.get("results") or [])
    selected: dict[str, str] = {}
    ric_owner: dict[str, str] = {}

    for raw in results:
        row = dict(raw)
        if row.get("validation_status") != "validated_single_candidate":
            continue
        symbol = str(row.get("historical_symbol") or "").strip().upper()
        ric = str(row.get("selected_ric") or "").strip()
        if not symbol or not ric:
            raise ValueError("validated equity mapping is missing symbol or selected RIC")
        other = ric_owner.get(ric)
        if other and other != symbol:
            raise ValueError(f"equity RIC {ric} maps to multiple historical symbols")
        ric_owner[ric] = symbol
        selected[ric] = symbol

    if not selected:
        raise ValueError("equity validation payload contains no validated RICs")
    return selected


def option_contract_map(contract_payload: Mapping[str, object]) -> dict[str, dict[str, object]]:
    summary = dict(contract_payload.get("summary") or {})
    if not bool(summary.get("historical_contract_set_ready_for_time_and_sales")):
        raise ValueError("option contract manifest is not backed by historical-chain evidence")

    contracts: dict[str, dict[str, object]] = {}
    for raw in list(contract_payload.get("contracts") or []):
        row = dict(raw)
        if not bool(row.get("historical_date_evidence")):
            continue
        if row.get("validation_status") != "historical_chain_candidate":
            continue
        ric = str(row.get("source_ric") or "").strip()
        if not ric:
            raise ValueError("historical option contract is missing source_ric")
        metadata = {
            "underlying_symbol": str(row.get("historical_symbol") or row.get("underlying_symbol") or "").strip().upper(),
            "option_symbol": str(row.get("option_symbol") or "").strip(),
            "expiration": str(row.get("expiration") or "").strip(),
            "strike": row.get("strike"),
            "option_type": row.get("option_type"),
        }
        if not metadata["underlying_symbol"]:
            raise ValueError(f"{ric}: missing historical underlying symbol")
        contracts[ric] = metadata

    if not contracts:
        raise ValueError("option contract manifest contains no historical-chain contracts")
    return contracts


def _quote_rejection_reason(row: Mapping[str, object]) -> str | None:
    flags = quote_qualifier_flags(row.get("Qualifiers"))
    if flags["no_quote"]:
        return "no_quote_qualifier"

    def number(key: str) -> float | None:
        raw = row.get(key)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    bid = number("Bid Price")
    ask = number("Ask Price")
    bid_size = number("Bid Size")
    ask_size = number("Ask Size")

    if None in (bid, ask, bid_size, ask_size):
        return "missing_or_non_numeric_quote_field"
    if bid < 0 or ask <= 0:
        return "invalid_quote_price"
    if bid_size < 0 or ask_size < 0:
        return "invalid_quote_size"
    if bid == 0 or bid_size == 0:
        return "original_research_zero_bid"
    if ask == 0 or ask_size == 0:
        return "original_research_zero_ask"
    if bid > ask:
        return "crossed_quote"
    return None


def _canonical_equity_trade(row: Mapping[str, object], symbol: str) -> dict[str, object]:
    normalized = normalize_equity_trade(row, symbol)
    return {
        "timestamp": normalized["timestamp"],
        "symbol": normalized["symbol"],
        "price": normalized["price"],
        "size": normalized["size"],
        "exchange": normalized.get("exchange", ""),
        "conditions": str(row.get("Qualifiers") or ""),
    }


def _canonical_equity_quote(row: Mapping[str, object], symbol: str) -> dict[str, object]:
    normalized = normalize_equity_quote(row, symbol)
    return {
        "timestamp": normalized["timestamp"],
        "symbol": normalized["symbol"],
        "bid": normalized["bid"],
        "ask": normalized["ask"],
        "bid_size": normalized["bid_size"],
        "ask_size": normalized["ask_size"],
        "exchange": str(row.get("Ex/Cntrb.ID") or ""),
        "conditions": str(row.get("Qualifiers") or ""),
    }


def _canonical_option_trade(
    row: Mapping[str, object],
    metadata: Mapping[str, object],
) -> dict[str, object]:
    normalized = normalize_option_trade(row, metadata)
    return {
        "timestamp": normalized["timestamp"],
        "symbol": normalized["option_symbol"],
        "underlying_symbol": normalized["underlying_symbol"],
        "option_symbol": normalized["option_symbol"],
        "expiration": normalized["expiration"],
        "strike": normalized["strike"],
        "option_type": normalized["option_type"],
        "price": normalized["price"],
        "size": normalized["size"],
        "exchange": normalized.get("exchange", ""),
        "conditions": str(row.get("Qualifiers") or ""),
    }


def _canonical_option_quote(
    row: Mapping[str, object],
    metadata: Mapping[str, object],
) -> dict[str, object]:
    normalized = normalize_option_quote(row, metadata)
    return {
        "timestamp": normalized["timestamp"],
        "symbol": normalized["option_symbol"],
        "underlying_symbol": normalized["underlying_symbol"],
        "option_symbol": normalized["option_symbol"],
        "expiration": normalized["expiration"],
        "strike": normalized["strike"],
        "option_type": normalized["option_type"],
        "bid": normalized["bid"],
        "ask": normalized["ask"],
        "bid_size": normalized["bid_size"],
        "ask_size": normalized["ask_size"],
        "exchange": str(row.get("Ex/Cntrb.ID") or ""),
        "conditions": str(row.get("Qualifiers") or ""),
    }


def adapt_equity_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    trade_date: str,
    validation_payload: Mapping[str, object],
) -> dict:
    requested = date.fromisoformat(trade_date)
    ric_to_symbol = equity_ric_map(validation_payload)

    trades: list[dict[str, object]] = []
    quotes: list[dict[str, object]] = []
    ignored = Counter()
    per_symbol = defaultdict(Counter)

    for raw in rows:
        row = dict(raw)
        ric = str(row.get("#RIC") or row.get("RIC") or "").strip()
        if ric not in ric_to_symbol:
            ignored["unknown_or_unvalidated_ric"] += 1
            continue
        parsed_date = row_trade_date(row)
        if parsed_date != requested:
            ignored["wrong_or_unparseable_date"] += 1
            continue

        symbol = ric_to_symbol[ric]
        kind = str(row.get("Type") or "").strip().lower()
        if kind == "trade":
            canonical = _canonical_equity_trade(row, symbol)
            trades.append(canonical)
            per_symbol[symbol]["trade"] += 1
        elif kind == "quote":
            reason = _quote_rejection_reason(row)
            if reason:
                ignored[f"quote:{reason}"] += 1
                continue
            canonical = _canonical_equity_quote(row, symbol)
            quotes.append(canonical)
            per_symbol[symbol]["quote"] += 1
        else:
            ignored["unsupported_row_type"] += 1

    expected_symbols = sorted(set(ric_to_symbol.values()))
    missing_trade = [s for s in expected_symbols if per_symbol[s]["trade"] == 0]
    missing_quote = [s for s in expected_symbols if per_symbol[s]["quote"] == 0]

    return {
        "schema_version": "1",
        "lane": "equity",
        "trade_date": trade_date,
        "equity_trades": trades,
        "equity_quotes": quotes,
        "summary": {
            "validated_ric_count": len(ric_to_symbol),
            "expected_symbol_count": len(expected_symbols),
            "trade_rows": len(trades),
            "quote_rows": len(quotes),
            "symbols_missing_trade_rows": missing_trade,
            "symbols_missing_quote_rows": missing_quote,
            "all_selected_symbols_have_trade_and_quote_rows": not missing_trade and not missing_quote,
            "ignored_rows": dict(sorted(ignored.items())),
            "g2_coverage_change": False,
        },
    }


def adapt_option_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    trade_date: str,
    contract_payload: Mapping[str, object],
) -> dict:
    requested = date.fromisoformat(trade_date)
    ric_to_meta = option_contract_map(contract_payload)

    trades: list[dict[str, object]] = []
    quotes: list[dict[str, object]] = []
    ignored = Counter()
    observed_contracts = defaultdict(Counter)

    for raw in rows:
        row = dict(raw)
        ric = str(row.get("#RIC") or row.get("RIC") or "").strip()
        metadata = ric_to_meta.get(ric)
        if metadata is None:
            ignored["unknown_or_nonhistorical_contract_ric"] += 1
            continue
        parsed_date = row_trade_date(row)
        if parsed_date != requested:
            ignored["wrong_or_unparseable_date"] += 1
            continue

        kind = str(row.get("Type") or "").strip().lower()
        if kind == "trade":
            trades.append(_canonical_option_trade(row, metadata))
            observed_contracts[ric]["trade"] += 1
        elif kind == "quote":
            reason = _quote_rejection_reason(row)
            if reason:
                ignored[f"quote:{reason}"] += 1
                continue
            quotes.append(_canonical_option_quote(row, metadata))
            observed_contracts[ric]["quote"] += 1
        else:
            ignored["unsupported_row_type"] += 1

    expected_contracts = sorted(ric_to_meta)
    contracts_with_trade = sorted(
        ric for ric in expected_contracts if observed_contracts[ric]["trade"] > 0
    )
    contracts_with_quote = sorted(
        ric for ric in expected_contracts if observed_contracts[ric]["quote"] > 0
    )

    return {
        "schema_version": "1",
        "lane": "options",
        "trade_date": trade_date,
        "option_trades": trades,
        "option_quotes": quotes,
        "summary": {
            "historical_contract_count": len(expected_contracts),
            "trade_rows": len(trades),
            "quote_rows": len(quotes),
            "contracts_with_trade_rows": len(contracts_with_trade),
            "contracts_with_quote_rows": len(contracts_with_quote),
            "contracts_without_trade_rows": sorted(set(expected_contracts) - set(contracts_with_trade)),
            "contracts_without_quote_rows": sorted(set(expected_contracts) - set(contracts_with_quote)),
            "ignored_rows": dict(sorted(ignored.items())),
            "g2_coverage_change": False,
        },
    }


def write_adaptation(
    payload: dict,
    *,
    output_dir: Path,
    input_path: Path | None = None,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    lane = payload["lane"]

    if lane == "equity":
        _write_csv(output_dir / "equity_trades.csv", payload["equity_trades"], EQUITY_TRADE_FIELDS)
        _write_csv(output_dir / "equity_quotes.csv", payload["equity_quotes"], EQUITY_QUOTE_FIELDS)
    else:
        _write_csv(output_dir / "option_trades.csv", payload["option_trades"], OPTION_TRADE_FIELDS)
        _write_csv(output_dir / "option_quotes.csv", payload["option_quotes"], OPTION_QUOTE_FIELDS)

    summary = dict(payload["summary"])
    receipt = {
        "schema_version": "1",
        "lane": lane,
        "trade_date": payload["trade_date"],
        "summary": summary,
    }
    if input_path is not None:
        resolved = input_path.expanduser().resolve()
        receipt["input_receipt"] = {
            "path_name": resolved.name,
            "size_bytes": resolved.stat().st_size,
            "sha256": _sha256(resolved),
        }

    (output_dir / "lseg_adaptation_receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert authorized LSEG Tick History Time & Sales results into the "
            "canonical CSV lanes consumed by market_data_adapter.py."
        )
    )
    sub = parser.add_subparsers(dest="lane", required=True)

    equity = sub.add_parser("equity")
    equity.add_argument("--input", type=Path, required=True)
    equity.add_argument("--date", required=True)
    equity.add_argument("--validation-json", type=Path, required=True)
    equity.add_argument("--output-dir", type=Path, required=True)

    options = sub.add_parser("options")
    options.add_argument("--input", type=Path, required=True)
    options.add_argument("--date", required=True)
    options.add_argument("--contract-json", type=Path, required=True)
    options.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args()
    rows = read_rows(args.input)

    if args.lane == "equity":
        validation = json.loads(args.validation_json.read_text(encoding="utf-8"))
        payload = adapt_equity_rows(
            rows,
            trade_date=args.date,
            validation_payload=validation,
        )
    else:
        contracts = json.loads(args.contract_json.read_text(encoding="utf-8"))
        payload = adapt_option_rows(
            rows,
            trade_date=args.date,
            contract_payload=contracts,
        )

    receipt = write_adaptation(
        payload,
        output_dir=args.output_dir,
        input_path=args.input,
    )
    print(json.dumps(receipt["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
