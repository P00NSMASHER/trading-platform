from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

import security_identity_gate as identity


DEFAULT_EVENTS = identity.DEFAULT_EVENTS
OUTPUT_FIELDS = identity.IDENTITY_EVIDENCE_FIELDS


class LsegIdentityBridgeError(ValueError):
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


def _symbol_to_permno(events: Iterable[Mapping[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for i, row in enumerate(events, 2):
        symbol = str(row.get("historical_symbol") or "").strip().upper()
        permno = str(row.get("permno") or "").strip()
        if not symbol or not permno:
            raise LsegIdentityBridgeError(
                f"event row {i}: historical_symbol and permno are required"
            )
        prior = result.get(symbol)
        if prior is not None and prior != permno:
            raise LsegIdentityBridgeError(
                f"event row {i}: historical_symbol {symbol} maps to multiple PERMNOs"
            )
        result[symbol] = permno
    if not result:
        raise LsegIdentityBridgeError("historical events are empty")
    return result


def _validated_receipt(summary: Mapping[str, object]) -> tuple[str, str, str]:
    trade_date = str(summary.get("trade_date") or "").strip()
    try:
        date.fromisoformat(trade_date)
    except ValueError as exc:
        raise LsegIdentityBridgeError(
            "validator summary must contain an ISO trade_date"
        ) from exc

    receipt = summary.get("input_receipt")
    if not isinstance(receipt, Mapping):
        raise LsegIdentityBridgeError(
            "validator summary must contain an input_receipt"
        )

    path_name = str(receipt.get("path_name") or "").strip()
    digest = str(receipt.get("sha256") or "").strip().lower()
    try:
        size_bytes = int(receipt.get("size_bytes") or 0)
    except (TypeError, ValueError) as exc:
        raise LsegIdentityBridgeError(
            "input_receipt.size_bytes must be a positive integer"
        ) from exc

    if not path_name or Path(path_name).name != path_name:
        raise LsegIdentityBridgeError(
            "input_receipt.path_name must be a plain nonblank filename"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise LsegIdentityBridgeError(
            "input_receipt.sha256 must be a lowercase SHA-256"
        )
    if size_bytes <= 0:
        raise LsegIdentityBridgeError(
            "input_receipt.size_bytes must be a positive integer"
        )

    return trade_date, path_name, digest


def _candidate_rics(raw: object) -> set[str]:
    if isinstance(raw, list):
        return {str(value).strip() for value in raw if str(value).strip()}
    return {
        value.strip()
        for value in str(raw or "").split(";")
        if value.strip()
    }


def _evidence_id(
    permno: str,
    trade_date: str,
    selected_ric: str,
    source_sha256: str,
) -> str:
    payload = f"{permno}|{trade_date}|{selected_ric}|{source_sha256}".encode("utf-8")
    return "LSEG-SID-" + hashlib.sha256(payload).hexdigest()[:20].upper()


def build_identity_evidence(
    validation_rows: Iterable[Mapping[str, object]],
    summary: Mapping[str, object],
    events: Iterable[Mapping[str, str]],
    *,
    authorization_reference: str,
) -> list[dict[str, str]]:
    authorization_reference = str(authorization_reference or "").strip()
    if not authorization_reference:
        raise LsegIdentityBridgeError("authorization_reference is required")

    expected_date, path_name, source_sha256 = _validated_receipt(summary)
    symbol_to_permno = _symbol_to_permno(events)

    by_key: dict[tuple[str, str], dict[str, str]] = {}
    for i, raw in enumerate(validation_rows, 2):
        status = str(raw.get("validation_status") or "").strip()
        if status != "validated_single_candidate":
            continue

        trade_date = str(raw.get("trade_date") or "").strip()
        if trade_date != expected_date:
            raise LsegIdentityBridgeError(
                f"validation row {i}: trade_date does not match validator summary"
            )

        symbol = str(raw.get("historical_symbol") or "").strip().upper()
        permno = symbol_to_permno.get(symbol)
        if permno is None:
            raise LsegIdentityBridgeError(
                f"validation row {i}: unknown historical_symbol {symbol!r}"
            )

        selected_ric = str(raw.get("selected_ric") or "").strip()
        if not selected_ric:
            raise LsegIdentityBridgeError(
                f"validation row {i}: validated row is missing selected_ric"
            )

        candidates = _candidate_rics(raw.get("candidate_rics"))
        if candidates and selected_ric not in candidates:
            raise LsegIdentityBridgeError(
                f"validation row {i}: selected_ric is not in candidate_rics"
            )

        if not (
            _truthy(raw.get("trade_lane_observed"))
            or _truthy(raw.get("quote_lane_observed"))
        ):
            raise LsegIdentityBridgeError(
                f"validation row {i}: validated row has no observed trade/quote lane"
            )

        evidence = {
            "evidence_id": _evidence_id(
                permno,
                trade_date,
                selected_ric,
                source_sha256,
            ),
            "permno": permno,
            "historical_symbol": symbol,
            "market_identifier": selected_ric,
            "valid_from": trade_date,
            "valid_through": trade_date,
            "evidence_lane": "AUTHORIZED_MARKET_SECURITY_MASTER",
            "source_reference": (
                f"lseg-timesales-receipt:{path_name}#sha256={source_sha256}"
            ),
            "authorization_reference": authorization_reference,
            "research_use_only": "1",
        }

        key = (permno, trade_date)
        prior = by_key.get(key)
        if prior is not None and prior != evidence:
            raise LsegIdentityBridgeError(
                f"conflicting validated evidence for PERMNO/date {permno}/{trade_date}"
            )
        by_key[key] = evidence

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
            "Convert exact-date LSEG RIC validation receipts into dated security "
            "identity evidence accepted by the fail-closed stable-ID gate."
        )
    )
    parser.add_argument("--validation-csv", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = build_identity_evidence(
        _read_csv(args.validation_csv),
        _read_json(args.summary_json),
        _read_csv(args.events),
        authorization_reference=args.authorization_reference,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_csv(rows), encoding="utf-8")
    print(json.dumps({"validated_permno_dates": len(rows)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
