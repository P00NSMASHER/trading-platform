from __future__ import annotations

import argparse
import csv
import gzip
import json
from datetime import date
from pathlib import Path
from typing import TextIO

import g2_lseg_datascope_execution_plan as execution
import g2_lseg_request_manifest as manifest
import g2_lseg_trth_normalizer as trth
from g2_lseg_datascope_client import ensure_private_output_path


ROOT = Path(__file__).resolve().parents[1]

FIELDS = {
    "equity_trade": [
        "timestamp", "symbol", "price", "size", "source_ric", "exchange", "qualifier_flags"
    ],
    "equity_quote": [
        "timestamp", "symbol", "bid", "ask", "bid_size", "ask_size",
        "source_ric", "qualifier_flags"
    ],
    "option_trade": [
        "timestamp", "underlying_symbol", "option_symbol", "expiration", "strike",
        "option_type", "price", "size", "source_ric", "exchange", "qualifier_flags"
    ],
    "option_quote": [
        "timestamp", "underlying_symbol", "option_symbol", "expiration", "strike",
        "option_type", "bid", "ask", "bid_size", "ask_size", "source_ric",
        "qualifier_flags"
    ],
}


def _execution_plan() -> dict:
    base = manifest.build_plan(
        manifest._read_csv(ROOT / manifest.DEFAULT_MAPPING),
        manifest._read_csv(ROOT / manifest.DEFAULT_SECONDARY),
        manifest._read_csv(ROOT / manifest.DEFAULT_EVENT_MAPPING),
        manifest._read_csv(ROOT / manifest.DEFAULT_CORE),
        manifest._read_csv(ROOT / manifest.DEFAULT_OPTIONS),
    )
    return execution.build_execution_plan(base)


def build_equity_ric_symbol_map(plan: dict | None = None) -> dict[str, str]:
    plan = plan or _execution_plan()
    out: dict[str, str] = {}
    for row in plan["equity_symbol_dates"]:
        symbol = str(row["historical_symbol"])
        for ric in row["candidate_rics"]:
            ric = str(ric)
            previous = out.get(ric)
            if previous is not None and previous != symbol:
                raise ValueError(
                    f"RIC {ric!r} maps to multiple historical symbols: "
                    f"{previous!r}, {symbol!r}"
                )
            out[ric] = symbol
    return out


def _open_text(path: Path) -> TextIO:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def _cook(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return value


def _write_rows(path: Path, record_kind: str, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS[record_kind], extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _cook(value) for key, value in row.items()})


def normalize_delivery(
    input_path: Path,
    *,
    lane: str,
    trade_date: str,
    output_dir: Path,
    equity_ric_symbol_map: dict[str, str] | None = None,
) -> dict:
    if lane not in {"equity", "option"}:
        raise ValueError("lane must be equity or option")
    date.fromisoformat(trade_date)

    source = ensure_private_output_path(input_path)
    destination = ensure_private_output_path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    ric_symbols = (
        equity_ric_symbol_map
        if equity_ric_symbol_map is not None
        else build_equity_ric_symbol_map()
    )
    normalized: dict[str, list[dict[str, object]]] = {
        f"{lane}_trade": [],
        f"{lane}_quote": [],
    }
    rejects: list[dict[str, object]] = []
    raw_rows = 0

    with _open_text(source) as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        required = {"#RIC", "Date-Time", "Type"}
        missing = sorted(required - fields)
        if missing:
            raise ValueError("raw LSEG file is missing required fields: " + ", ".join(missing))

        for row_number, row in enumerate(reader, start=2):
            raw_rows += 1
            source_ric = str(row.get("#RIC") or "")
            row_type = str(row.get("Type") or "")
            try:
                if row_type not in {"Trade", "Quote"}:
                    raise ValueError(f"unsupported LSEG row Type: {row_type!r}")

                if lane == "equity":
                    historical_symbol = ric_symbols.get(source_ric)
                    if historical_symbol is None:
                        raise ValueError(
                            f"equity RIC is not in the frozen candidate map: {source_ric!r}"
                        )
                    if row_type == "Trade":
                        record_kind = "equity_trade"
                        out = trth.normalize_equity_trade(row, historical_symbol)
                    else:
                        record_kind = "equity_quote"
                        out = trth.normalize_equity_quote(row, historical_symbol)
                else:
                    if row_type == "Trade":
                        record_kind = "option_trade"
                        out = trth.normalize_option_trade(row)
                    else:
                        record_kind = "option_quote"
                        out = trth.normalize_option_quote(row)

                if str(out["timestamp"])[:10] != trade_date:
                    raise ValueError(
                        f"normalized local trade date {str(out['timestamp'])[:10]} "
                        f"does not match expected {trade_date}"
                    )
                normalized[record_kind].append(out)
            except (KeyError, TypeError, ValueError) as exc:
                rejects.append(
                    {
                        "row_number": row_number,
                        "source_ric": source_ric,
                        "type": row_type,
                        "reason": str(exc),
                    }
                )

    outputs: dict[str, str] = {}
    for record_kind, rows in normalized.items():
        if not rows:
            continue
        path = destination / f"lseg_{trade_date}_{record_kind}.csv"
        _write_rows(path, record_kind, rows)
        outputs[record_kind] = str(path)

    summary = {
        "schema_version": "1",
        "lane": lane,
        "trade_date": trade_date,
        "input_path": str(source),
        "raw_rows": raw_rows,
        "normalized_rows": {
            kind: len(rows) for kind, rows in normalized.items()
        },
        "rejected_rows": len(rejects),
        "rejects": rejects,
        "outputs": outputs,
        "authorization_asserted": False,
        "normalized_rows_are_not_g2_coverage": True,
        "requires_entitlement_binding": True,
        "requires_production_content_preflight": True,
        "g2_coverage_change": 0,
    }
    summary_path = destination / f"lseg_{trade_date}_{lane}_normalization_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary["summary_path"] = str(summary_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize a private LSEG DataScope Time & Sales delivery into canonical "
            "private CSVs for the existing licensed-data intake/preflight pipeline."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--lane", choices=("equity", "option"), required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    summary = normalize_delivery(
        args.input,
        lane=args.lane,
        trade_date=args.trade_date,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "lane": summary["lane"],
                "trade_date": summary["trade_date"],
                "raw_rows": summary["raw_rows"],
                "normalized_rows": summary["normalized_rows"],
                "rejected_rows": summary["rejected_rows"],
                "summary_path": summary["summary_path"],
                "g2_coverage_change": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
