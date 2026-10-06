from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class SymbolPermnoLead:
    request_id: str
    historical_symbol: str
    trade_date: str
    permno: str
    gvkey_hint: str
    lead_source: str
    identity_status: str
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    return fields, rows


def _normalize_permno(value: str) -> str:
    raw = str(value or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw


def _request_id(symbol: str, trade_date: str, permno: str) -> str:
    payload = f"{symbol}|{trade_date}|{permno}|SYMBOL_HISTORY_LEAD".encode("utf-8")
    return "G5SIDLEAD-" + hashlib.sha256(payload).hexdigest()[:16].upper()


def _samplefirms_symbol_maps(
    samplefirms_path: Path,
) -> tuple[
    dict[str, str],
    dict[str, str],
    set[str],
]:
    fields, rows = _read_csv(samplefirms_path)
    required = {"PERMNO", "GVKEY", "SYMBOL", "date"}
    missing = required.difference(fields)
    if missing:
        raise ValueError(f"SampleFirms missing columns: {sorted(missing)}")

    permnos_by_symbol: dict[str, set[str]] = {}
    gvkeys_by_symbol: dict[str, set[str]] = {}
    for row_no, row in enumerate(rows, 2):
        symbol = row["SYMBOL"].upper()
        permno = _normalize_permno(row["PERMNO"])
        gvkey = row["GVKEY"]
        if not symbol:
            continue
        if not permno:
            raise ValueError(
                f"SampleFirms row {row_no}: blank PERMNO for {symbol}"
            )
        permnos_by_symbol.setdefault(symbol, set()).add(permno)
        if gvkey:
            gvkeys_by_symbol.setdefault(symbol, set()).add(gvkey)

    unique_permno: dict[str, str] = {}
    unique_gvkey: dict[str, str] = {}
    ambiguous_symbols: set[str] = set()
    for symbol, permnos in permnos_by_symbol.items():
        if len(permnos) == 1:
            unique_permno[symbol] = next(iter(permnos))
        else:
            ambiguous_symbols.add(symbol)
    for symbol, gvkeys in gvkeys_by_symbol.items():
        if len(gvkeys) == 1:
            unique_gvkey[symbol] = next(iter(gvkeys))
    return unique_permno, unique_gvkey, ambiguous_symbols


def build(
    *,
    identity_queue_path: Path,
    samplefirms_path: Path,
    output_dir: Path,
) -> dict:
    queue_fields, queue_rows = _read_csv(identity_queue_path)
    required_queue = {
        "historical_symbol",
        "trade_date",
        "identity_status",
        "canonical_permno",
        "samplefirms_permno",
        "research_use_only",
    }
    missing = required_queue.difference(queue_fields)
    if missing:
        raise ValueError(f"identity queue missing columns: {sorted(missing)}")
    if not queue_rows:
        raise ValueError("identity queue is empty")

    unique_permno, unique_gvkey, ambiguous_symbols = _samplefirms_symbol_maps(
        samplefirms_path
    )

    leads: list[SymbolPermnoLead] = []
    unresolved: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    eligible_no_hint_count = 0
    ambiguous_symbol_count = 0
    absent_symbol_count = 0

    for row_no, row in enumerate(queue_rows, 2):
        symbol = row["historical_symbol"].upper()
        trade_date = row["trade_date"][:10]
        if not symbol or not trade_date:
            raise ValueError(
                f"identity queue row {row_no}: historical_symbol/trade_date required"
            )
        if row["research_use_only"] != "1":
            raise ValueError(
                f"identity queue row {row_no}: research_use_only must equal 1"
            )
        pair = (symbol, trade_date)
        if pair in seen_pairs:
            raise ValueError(
                f"duplicate identity requirement: {symbol}|{trade_date}"
            )
        seen_pairs.add(pair)

        canonical = _normalize_permno(row["canonical_permno"])
        exact_sample = _normalize_permno(row["samplefirms_permno"])
        if canonical or exact_sample:
            continue

        eligible_no_hint_count += 1
        if symbol in ambiguous_symbols:
            ambiguous_symbol_count += 1
            item = dict(row)
            item["lead_status"] = "AMBIGUOUS_SYMBOL_LEVEL_PERMNO_HISTORY"
            unresolved.append(item)
            continue

        permno = unique_permno.get(symbol, "")
        if not permno:
            absent_symbol_count += 1
            item = dict(row)
            item["lead_status"] = "NO_SYMBOL_LEVEL_PERMNO_HISTORY"
            unresolved.append(item)
            continue

        leads.append(
            SymbolPermnoLead(
                request_id=_request_id(symbol, trade_date, permno),
                historical_symbol=symbol,
                trade_date=trade_date,
                permno=permno,
                gvkey_hint=unique_gvkey.get(symbol, ""),
                lead_source="SAMPLEFIRMS_SAME_SYMBOL_UNIQUE_PERMNO_HISTORY",
                identity_status=row["identity_status"],
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    lead_path = output_dir / "g5_control_identity_symbol_permno_leads.csv"
    unresolved_path = output_dir / "g5_control_identity_symbol_permno_unresolved.csv"

    with lead_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(SymbolPermnoLead.__dataclass_fields__),
        )
        writer.writeheader()
        for row in leads:
            writer.writerow(asdict(row))

    unresolved_fields = list(queue_fields)
    if "lead_status" not in unresolved_fields:
        unresolved_fields.append("lead_status")
    with unresolved_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=unresolved_fields)
        writer.writeheader()
        writer.writerows(unresolved)

    if len(leads) + len(unresolved) != eligible_no_hint_count:
        raise ValueError("symbol-level PERMNO lead accounting does not reconcile")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Generate non-evidence PERMNO acquisition leads for G5 control identity "
            "requirements that lack both canonical and exact-date SampleFirms PERMNO "
            "hints. A lead is emitted only when the same historical symbol maps to "
            "exactly one PERMNO anywhere in the SampleFirms planning universe. "
            "Authorized dated Stocknames/security-master validation remains mandatory."
        ),
        "research_use_only": True,
        "eligible_no_hint_requirement_count": eligible_no_hint_count,
        "symbol_level_permno_lead_count": len(leads),
        "unresolved_no_hint_requirement_count": len(unresolved),
        "ambiguous_symbol_level_permno_history_count": ambiguous_symbol_count,
        "no_symbol_level_permno_history_count": absent_symbol_count,
        "request_ids_unique": len({row.request_id for row in leads}) == len(leads),
        "inputs": {
            "identity_queue": {
                "path": str(identity_queue_path),
                "sha256": _sha256(identity_queue_path),
            },
            "samplefirms": {
                "path": str(samplefirms_path),
                "sha256": _sha256(samplefirms_path),
            },
        },
        "outputs": {
            "symbol_permno_leads": str(lead_path),
            "unresolved_no_hint": str(unresolved_path),
        },
        "policy": {
            "retrospective_labels_used": False,
            "future_or_prior_rows_may_supply_acquisition_hint_only": True,
            "symbol_level_lead_is_identity_evidence": False,
            "continuous_symbol_identity_assumed": False,
            "authorized_dated_validation_still_required": True,
            "ambiguous_symbol_to_permno_mapping_fails_closed": True,
            "lead_rows_change_g5_readiness": False,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_control_identity_symbol_permno_lead_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate non-evidence same-symbol PERMNO leads for unresolved G5 "
            "control identity requirements."
        )
    )
    parser.add_argument("--identity-queue", type=Path, required=True)
    parser.add_argument("--samplefirms", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        identity_queue_path=args.identity_queue,
        samplefirms_path=args.samplefirms,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
