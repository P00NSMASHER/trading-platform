from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = "1"

STOCKNAMES_QUEUE_FIELDS = [
    "request_id",
    "permno",
    "historical_symbol",
    "trade_date",
    "hint_source",
    "identity_status",
    "research_use_only",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    return fields, rows


def _request_id(symbol: str, trade_date: str, permno: str) -> str:
    raw = f"{symbol}|{trade_date}|{permno}".encode("utf-8")
    return "G5SID-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def _load_symbol_permno_leads(
    path: Path | None,
) -> dict[tuple[str, str], dict[str, str]]:
    if path is None:
        return {}

    fields, rows = _read_csv(path)
    required = {
        "historical_symbol",
        "trade_date",
        "permno",
        "lead_source",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise ValueError(
            f"symbol PERMNO lead file missing columns: {sorted(missing)}"
        )

    out: dict[tuple[str, str], dict[str, str]] = {}
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        trade_date = row["trade_date"][:10]
        permno = row["permno"]
        if not symbol or not trade_date or not permno:
            raise ValueError(
                f"symbol PERMNO lead row {row_no}: symbol/date/PERMNO required"
            )
        if row["research_use_only"] != "1":
            raise ValueError(
                f"symbol PERMNO lead row {row_no}: research_use_only must equal 1"
            )
        if row["lead_source"] != "SAMPLEFIRMS_SAME_SYMBOL_UNIQUE_PERMNO_HISTORY":
            raise ValueError(
                f"symbol PERMNO lead row {row_no}: unexpected lead_source"
            )
        key = (symbol, trade_date)
        if key in out:
            raise ValueError(
                f"duplicate symbol PERMNO lead: {symbol}|{trade_date}"
            )

        normalized = dict(row)
        normalized["historical_symbol"] = symbol
        normalized["trade_date"] = trade_date
        out[key] = normalized
    return out


def build(
    *,
    identity_queue_path: Path,
    output_dir: Path,
    symbol_permno_leads_path: Path | None = None,
) -> dict:
    fields, rows = _read_csv(identity_queue_path)
    required = {
        "historical_symbol",
        "trade_date",
        "identity_status",
        "canonical_permno",
        "samplefirms_permno",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise ValueError(f"identity queue missing columns: {sorted(missing)}")
    if not rows:
        raise ValueError("identity queue is empty")

    symbol_leads = _load_symbol_permno_leads(symbol_permno_leads_path)
    ready: list[dict[str, str]] = []
    no_hint: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    consumed_symbol_leads: set[tuple[str, str]] = set()

    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        trade_date = row["trade_date"][:10]
        canonical = row["canonical_permno"]
        sample = row["samplefirms_permno"]
        if not symbol or not trade_date:
            raise ValueError(
                f"identity row {row_no}: historical_symbol/trade_date required"
            )
        if row["research_use_only"] != "1":
            raise ValueError(
                f"identity row {row_no}: research_use_only must equal 1"
            )

        key = (symbol, trade_date)
        if key in seen:
            raise ValueError(
                f"duplicate identity requirement: {symbol}|{trade_date}"
            )
        seen.add(key)

        if canonical and sample and canonical != sample:
            raise ValueError(
                f"PERMNO hint conflict for {symbol}|{trade_date}: "
                f"{canonical} != {sample}"
            )

        symbol_lead = symbol_leads.get(key)
        if symbol_lead is not None and (canonical or sample):
            raise ValueError(
                "symbol-level PERMNO lead is out of scope for already-hinted row "
                f"{symbol}|{trade_date}"
            )

        permno = canonical or sample
        hint_source = ""
        if canonical:
            hint_source = "CANONICAL_G2_PERMNO"
        elif sample:
            hint_source = "SAMPLEFIRMS_EXACT_DATE_PERMNO_LEAD"
        elif symbol_lead is not None:
            permno = symbol_lead["permno"]
            hint_source = "SAMPLEFIRMS_SAME_SYMBOL_UNIQUE_PERMNO_HISTORY_LEAD"
            consumed_symbol_leads.add(key)

        if not permno:
            no_hint.append(dict(row))
            continue

        ready.append(
            {
                "request_id": _request_id(symbol, trade_date, permno),
                "permno": permno,
                "historical_symbol": symbol,
                "trade_date": trade_date,
                "hint_source": hint_source,
                "identity_status": row["identity_status"],
                "research_use_only": "1",
            }
        )

    unused_symbol_leads = sorted(set(symbol_leads) - consumed_symbol_leads)
    if unused_symbol_leads:
        sample = ", ".join(
            f"{symbol}|{trade_date}"
            for symbol, trade_date in unused_symbol_leads[:5]
        )
        raise ValueError(
            f"symbol-level PERMNO leads do not match eligible no-hint rows: {sample}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    ready_path = output_dir / "g5_control_identity_stocknames_ready_queue.csv"
    no_hint_path = output_dir / "g5_control_identity_no_permno_hint.csv"

    with ready_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=STOCKNAMES_QUEUE_FIELDS)
        writer.writeheader()
        writer.writerows(ready)

    no_hint_fields = list(fields)
    with no_hint_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=no_hint_fields)
        writer.writeheader()
        writer.writerows(no_hint)

    if len(ready) + len(no_hint) != len(rows):
        raise ValueError("stocknames handoff accounting does not reconcile")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Convert unresolved G5 control identity rows with a known PERMNO hint "
            "into the exact queue schema consumed by the existing authorized "
            "stocknames stable-ID adapter. Optional same-symbol PERMNO history "
            "leads may fill only otherwise no-hint rows, and remain non-evidence "
            "until dated Stocknames validation succeeds."
        ),
        "research_use_only": True,
        "identity_queue_count": len(rows),
        "stocknames_ready_request_count": len(ready),
        "no_permno_hint_request_count": len(no_hint),
        "canonical_permno_hint_request_count": sum(
            row["hint_source"] == "CANONICAL_G2_PERMNO"
            for row in ready
        ),
        "samplefirms_permno_lead_request_count": sum(
            row["hint_source"] == "SAMPLEFIRMS_EXACT_DATE_PERMNO_LEAD"
            for row in ready
        ),
        "symbol_level_permno_lead_request_count": sum(
            row["hint_source"]
            == "SAMPLEFIRMS_SAME_SYMBOL_UNIQUE_PERMNO_HISTORY_LEAD"
            for row in ready
        ),
        "request_ids_unique": len({row["request_id"] for row in ready}) == len(ready),
        "inputs": {
            "identity_queue_path": str(identity_queue_path),
            "identity_queue_sha256": _sha256(identity_queue_path),
            "symbol_permno_leads_path": (
                str(symbol_permno_leads_path)
                if symbol_permno_leads_path is not None
                else None
            ),
            "symbol_permno_leads_sha256": (
                _sha256(symbol_permno_leads_path)
                if symbol_permno_leads_path is not None
                else None
            ),
        },
        "outputs": {
            "stocknames_ready_queue": str(ready_path),
            "no_permno_hint_queue": str(no_hint_path),
        },
        "policy": {
            "samplefirms_hint_is_identity_evidence": False,
            "symbol_level_permno_lead_is_identity_evidence": False,
            "symbol_level_permno_lead_may_only_fill_no_hint_rows": True,
            "authorized_stocknames_validation_still_required": True,
            "requested_date_must_be_inside_authorized_name_interval": True,
            "historical_symbol_must_match_authorized_name_interval": True,
            "rows_without_permno_hint_fail_closed": True,
            "handoff_rows_are_g5_evidence": False,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_control_identity_stocknames_handoff_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare unresolved G5 control identity rows for the authorized "
            "stocknames stable-ID adapter."
        )
    )
    parser.add_argument("--identity-queue", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--symbol-permno-leads",
        type=Path,
        help=(
            "Optional non-evidence same-symbol PERMNO lead file produced by "
            "g5_control_identity_symbol_permno_leads."
        ),
    )
    args = parser.parse_args()

    result = build(
        identity_queue_path=args.identity_queue,
        output_dir=args.output_dir,
        symbol_permno_leads_path=args.symbol_permno_leads,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
