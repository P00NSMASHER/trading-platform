from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_OPTION_PARTITION = Path(
    "data/processed/g2_vendor_requests/cheap_route_partitions/thetadata_options.csv"
)
DEFAULT_EQUITY_PARTITION = Path(
    "data/processed/g2_vendor_requests/cheap_route_partitions/thetadata_equity.csv"
)

FIELDS = [
    "record_kind",
    "trade_date",
    "historical_symbol",
    "endpoint",
    "interval",
    "venue",
    "contract_scope",
    "request_status",
]


def _manifest_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "record_kind",
        "trade_date",
        "historical_symbols",
        "unique_symbol_count",
        "symbol_date_pair_count",
    }
    if not rows:
        raise ValueError(f"{path}: empty partition")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    return rows


def _endpoint_fields(record_kind: str) -> dict[str, str]:
    if record_kind == "option_quote":
        return {
            "endpoint": "option/history/quote",
            "interval": "tick",
            "venue": "",
            "contract_scope": "expiration=*; all contracts for underlying/date",
        }
    if record_kind == "option_trade":
        return {
            "endpoint": "option/history/trade",
            "interval": "",
            "venue": "",
            "contract_scope": "all contracts for underlying/date",
        }
    if record_kind == "equity_quote":
        return {
            "endpoint": "stock/history/quote",
            "interval": "tick",
            "venue": "utp_cta",
            "contract_scope": "merged SIP NBBO for requested UTP symbol/date",
        }
    if record_kind == "equity_trade":
        return {
            "endpoint": "stock/history/trade",
            "interval": "",
            "venue": "",
            "contract_scope": "requested UTP symbol/date",
        }
    raise ValueError(f"unsupported record_kind={record_kind!r}")


def expand_partition(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        symbols = [x for x in row["historical_symbols"].split(";") if x]
        unique_count = int(row["unique_symbol_count"])
        pair_count = int(row["symbol_date_pair_count"])
        if len(symbols) != unique_count or pair_count != unique_count:
            raise ValueError(
                f"{row['trade_date']} {row['record_kind']}: "
                f"symbol count mismatch symbols={len(symbols)} unique={unique_count} pairs={pair_count}"
            )

        endpoint = _endpoint_fields(row["record_kind"])
        for symbol in symbols:
            out.append(
                {
                    "record_kind": row["record_kind"],
                    "trade_date": row["trade_date"],
                    "historical_symbol": symbol,
                    **endpoint,
                    "request_status": "DRY_RUN_ONLY_NOT_AUTHORIZED",
                }
            )

    return sorted(
        out,
        key=lambda x: (
            x["trade_date"],
            x["historical_symbol"],
            x["record_kind"],
        ),
    )


def build_plan(option_partition: Path, equity_partition: Path) -> dict:
    option_requests = expand_partition(_read_csv(option_partition))
    stock_requests = expand_partition(_read_csv(equity_partition))

    option_counts = {
        kind: sum(x["record_kind"] == kind for x in option_requests)
        for kind in ("option_trade", "option_quote")
    }
    stock_counts = {
        kind: sum(x["record_kind"] == kind for x in stock_requests)
        for kind in ("equity_trade", "equity_quote")
    }

    if option_counts != {"option_trade": 3014, "option_quote": 3014}:
        raise ValueError(f"unexpected ThetaData option request counts: {option_counts}")
    if stock_counts != {"equity_trade": 1430, "equity_quote": 1430}:
        raise ValueError(f"unexpected ThetaData stock request counts: {stock_counts}")

    return {
        "schema_version": "1",
        "purpose": (
            "Dry-run-only ThetaData request plan for the frozen G2 cheap-route partitions. "
            "This artifact makes no network call and does not authorize a subscription or G2 coverage."
        ),
        "vendor": "ThetaData",
        "written_reply_source_date": "2026-10-02",
        "subscription": {
            "options_pro_monthly_usd": 160,
            "stock_pro_monthly_usd": 160,
            "one_month_bundle_total_usd": 320,
            "subscription_authorized": False,
            "purchase_authority": False,
        },
        "execution": {
            "network_execution_enabled": False,
            "credentials_required_in_repository": False,
            "max_concurrent_requests_vendor_confirmed": 8,
            "request_status": "DRY_RUN_ONLY_NOT_AUTHORIZED",
        },
        "option_requests": {
            "trade_requests": option_counts["option_trade"],
            "quote_requests": option_counts["option_quote"],
            "total_requests": len(option_requests),
            "source_partition": _manifest_path(option_partition),
            "output_file": "thetadata_option_requests.csv",
        },
        "stock_requests": {
            "trade_requests": stock_counts["equity_trade"],
            "quote_requests": stock_counts["equity_quote"],
            "total_requests": len(stock_requests),
            "source_partition": _manifest_path(equity_partition),
            "output_file": "thetadata_stock_requests.csv",
        },
        "total_requests": len(option_requests) + len(stock_requests),
        "retention_plan": "data/processed/g2_vendor_requests/thetadata_retention_plan.json",
        "guardrails": {
            "candidate_is_not_coverage": True,
            "dry_run_is_not_purchase_authority": True,
            "network_execution_requires_explicit_user_authorization": True,
            "raw_retention_plan_must_be_applied_before_bulk_acquisition": True,
            "g2_release_gate_unchanged": True,
        },
        "_option_rows": option_requests,
        "_stock_rows": stock_requests,
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_plan(option_partition: Path, equity_partition: Path, output_dir: Path) -> dict:
    payload = build_plan(option_partition, equity_partition)
    option_rows = payload.pop("_option_rows")
    stock_rows = payload.pop("_stock_rows")

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "thetadata_option_requests.csv", option_rows)
    _write_csv(output_dir / "thetadata_stock_requests.csv", stock_rows)
    (output_dir / "thetadata_request_summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build dry-run ThetaData request manifests.")
    parser.add_argument("--option-partition", type=Path, default=DEFAULT_OPTION_PARTITION)
    parser.add_argument("--equity-partition", type=Path, default=DEFAULT_EQUITY_PARTITION)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    payload = write_plan(args.option_partition, args.equity_partition, args.output_dir)
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
