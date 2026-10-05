from __future__ import annotations

import argparse
import csv
import io
import json
import re
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

import security_identity_gate as identity


SCHEMA_VERSION = "1"
DEFAULT_EVENTS = identity.DEFAULT_EVENTS
OUTPUT_FIELDS = [
    "permno",
    "historical_symbol",
    "trade_date",
    "market_identifier",
    "source_family",
    "source_reference",
    "source_sha256",
    "validation_status",
    "research_use_only",
]


class SecurityIdentityBridgeError(ValueError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {str(k): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(handle)
        ]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _truthy(value: object) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _event_symbol_to_permno(events: Iterable[Mapping[str, str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for i, row in enumerate(events, 2):
        symbol = str(row.get("historical_symbol") or "").strip().upper()
        permno = str(row.get("permno") or "").strip()
        if not symbol or not permno:
            raise SecurityIdentityBridgeError(
                f"event row {i}: historical_symbol and permno are required"
            )
        prior = mapping.get(symbol)
        if prior is not None and prior != permno:
            raise SecurityIdentityBridgeError(
                f"event row {i}: historical_symbol {symbol} maps to multiple PERMNOs"
            )
        mapping[symbol] = permno
    if not mapping:
        raise SecurityIdentityBridgeError("historical events are empty")
    return mapping


def _receipt(summary: Mapping[str, object]) -> tuple[str, str, str]:
    trade_date = str(summary.get("trade_date") or "").strip()
    try:
        date.fromisoformat(trade_date)
    except ValueError as exc:
        raise SecurityIdentityBridgeError(
            "validator summary must contain an ISO trade_date"
        ) from exc

    receipt = summary.get("input_receipt")
    if not isinstance(receipt, Mapping):
        raise SecurityIdentityBridgeError(
            "validator summary must contain an input_receipt"
        )
    path_name = str(receipt.get("path_name") or "").strip()
    digest = str(receipt.get("sha256") or "").strip().lower()
    if not path_name or Path(path_name).name != path_name:
        raise SecurityIdentityBridgeError(
            "input_receipt.path_name must be a plain nonblank filename"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SecurityIdentityBridgeError(
            "input_receipt.sha256 must be a lowercase SHA-256"
        )
    return trade_date, path_name, digest


def build_dated_evidence(
    validation_rows: Iterable[Mapping[str, object]],
    summary: Mapping[str, object],
    events: Iterable[Mapping[str, str]],
) -> list[dict[str, str]]:
    expected_date, path_name, source_sha256 = _receipt(summary)
    symbol_to_permno = _event_symbol_to_permno(events)

    by_key: dict[tuple[str, str], dict[str, str]] = {}
    for i, raw in enumerate(validation_rows, 2):
        status = str(raw.get("validation_status") or "").strip()
        if status != "validated_single_candidate":
            continue

        trade_date = str(raw.get("trade_date") or "").strip()
        if trade_date != expected_date:
            raise SecurityIdentityBridgeError(
                f"validation row {i}: trade_date does not match validator summary"
            )
        symbol = str(raw.get("historical_symbol") or "").strip().upper()
        if symbol not in symbol_to_permno:
            raise SecurityIdentityBridgeError(
                f"validation row {i}: unknown historical_symbol {symbol!r}"
            )

        selected_ric = str(raw.get("selected_ric") or "").strip()
        if not selected_ric:
            raise SecurityIdentityBridgeError(
                f"validation row {i}: validated row is missing selected_ric"
            )
        if not (
            _truthy(raw.get("trade_lane_observed"))
            or _truthy(raw.get("quote_lane_observed"))
        ):
            raise SecurityIdentityBridgeError(
                f"validation row {i}: validated row has no observed trade/quote lane"
            )

        permno = symbol_to_permno[symbol]
        row = {
            "permno": permno,
            "historical_symbol": symbol,
            "trade_date": trade_date,
            "market_identifier": selected_ric,
            "source_family": "authorized_historical_lseg_timesales",
            "source_reference": f"lseg-timesales-receipt:{path_name}",
            "source_sha256": source_sha256,
            "validation_status": identity.DATED_EVIDENCE_STATUS,
            "research_use_only": "1",
        }
        key = (permno, trade_date)
        prior = by_key.get(key)
        if prior is not None and prior != row:
            raise SecurityIdentityBridgeError(
                f"conflicting validated evidence for PERMNO/date {permno}/{trade_date}"
            )
        by_key[key] = row

    return [by_key[key] for key in sorted(by_key)]


def render_csv(rows: Iterable[Mapping[str, str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: str(row.get(field) or "") for field in OUTPUT_FIELDS})
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bridge public-safe date-specific LSEG RIC validation receipts into "
            "strict stable-security-identity evidence."
        )
    )
    parser.add_argument("--validation-csv", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = build_dated_evidence(
        _read_csv(args.validation_csv),
        _read_json(args.summary_json),
        _read_csv(args.events),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_csv(rows), encoding="utf-8")
    print(json.dumps({"validated_permno_dates": len(rows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
