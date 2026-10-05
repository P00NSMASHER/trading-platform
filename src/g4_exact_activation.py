from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import g4_exchange_reference_completion as exact
import metadata_resolver as resolver

DEFAULT_BASE_CONTRACT = Path("config/metadata_sources.public_progress.json")
PRIVATE_FILES = {
    "nyse": "g4_nyse_exact_shares.csv",
    "nasdaq": "g4_nasdaq_exact_shares.csv",
    "receipt": "g4_exact_materialization_receipt.json",
}
COLUMN_MAP = {
    "historical_symbol": "historical_symbol",
    "target_trade_date": "target_trade_date",
    "fact_date": "fact_date",
    "available_at": "available_at",
    "shares_outstanding": "shares_outstanding",
    "source_reference": "source_reference",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(handle)
        ]


def _nonblank(value: str, name: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{name} must be nonblank")
    return clean


def _expected_counts() -> tuple[int, int, int]:
    nyse = len(exact.NYSE_TARGETS)
    nasdaq = len(exact.NASDAQ_TARGETS)
    return nyse, nasdaq, nyse + nasdaq


def load_private_completion(private_root: Path) -> tuple[list[dict[str, str]], dict, dict]:
    root = private_root.expanduser().resolve()
    nyse_path = root / PRIVATE_FILES["nyse"]
    nasdaq_path = root / PRIVATE_FILES["nasdaq"]
    receipt_path = root / PRIVATE_FILES["receipt"]

    for path in (nyse_path, nasdaq_path, receipt_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    expected_nyse, expected_nasdaq, expected_total = _expected_counts()

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "READY_FOR_PRIVATE_G4_ACTIVATION":
        raise ValueError("G4 materialization receipt is not activation-ready")
    if int(receipt.get("rows_materialized", -1)) != expected_total:
        raise ValueError(f"G4 materialization receipt must contain exactly {expected_total} rows")
    if (
        int(receipt.get("nyse_rows", -1)) != expected_nyse
        or int(receipt.get("nasdaq_rows", -1)) != expected_nasdaq
    ):
        raise ValueError(
            f"G4 materialization receipt must contain {expected_nyse} NYSE + "
            f"{expected_nasdaq} Nasdaq rows"
        )
    target = dict(receipt.get("g4_target_state") or {})
    if target != {
        "required": 3828,
        "exact_resolved": 3828,
        "reviewed_excluded": 0,
        "blocking_unresolved": 0,
    }:
        raise ValueError("G4 materialization receipt target state is not exact 3828/3828")

    nyse_rows = _read_csv(nyse_path)
    nasdaq_rows = _read_csv(nasdaq_path)
    if len(nyse_rows) != expected_nyse or len(nasdaq_rows) != expected_nasdaq:
        raise ValueError("private G4 CSV row counts do not match the activation receipt")

    expected = set(exact.NYSE_TARGETS) | set(exact.NASDAQ_TARGETS)
    combined = nyse_rows + nasdaq_rows
    actual = {
        (row.get("historical_symbol", "").upper(), row.get("target_trade_date", ""))
        for row in combined
    }
    if len(combined) != expected_total or actual != expected:
        raise ValueError(
            f"private G4 completion rows do not match the canonical {expected_total}-row target set"
        )

    for row in combined:
        symbol = row["historical_symbol"].upper()
        target_date = row["target_trade_date"]
        fact_date = row["fact_date"]
        shares = row["shares_outstanding"]
        available_at = row["available_at"]

        if not shares.isdigit() or int(shares) <= 0:
            raise ValueError(f"{symbol}|{target_date}: invalid exact shares value")
        target_day = date.fromisoformat(target_date)
        fact_day = date.fromisoformat(fact_date)
        if fact_day > target_day or (target_day - fact_day).days > 130:
            raise ValueError(f"{symbol}|{target_date}: inadmissible fact date")
        available = datetime.fromisoformat(available_at)
        if available.tzinfo is None:
            raise ValueError(f"{symbol}|{target_date}: available_at must be timezone-aware")
        if available > exact._cutoff(symbol, target_date):
            raise ValueError(f"{symbol}|{target_date}: source availability is after cutoff")
        if not row.get("source_reference", "").strip():
            raise ValueError(f"{symbol}|{target_date}: source_reference is blank")

    audit = {
        "private_root": str(root),
        "nyse_path": str(nyse_path),
        "nyse_sha256": _sha256(nyse_path),
        "nasdaq_path": str(nasdaq_path),
        "nasdaq_sha256": _sha256(nasdaq_path),
        "materialization_receipt_path": str(receipt_path),
        "materialization_receipt_sha256": _sha256(receipt_path),
    }
    return combined, receipt, audit


def build_activation_contract(
    *,
    private_root: Path,
    base_contract: Path,
    output_contract: Path,
    nyse_license_reference: str,
    nasdaq_license_reference: str,
) -> dict[str, Any]:
    _, receipt, audit = load_private_completion(private_root)
    _, _, expected_total = _expected_counts()

    base_path = base_contract.expanduser().resolve()
    raw = json.loads(base_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "1":
        raise ValueError("base metadata contract schema_version must equal '1'")
    if not isinstance(raw.get("sources"), list):
        raise ValueError("base metadata contract sources must be a list")

    existing_exclusions = raw.get("reviewed_share_exclusions")
    if (
        not isinstance(existing_exclusions, dict)
        or int(existing_exclusions.get("expected_count", -1)) != expected_total
    ):
        raise ValueError(
            f"base contract no longer contains the canonical {expected_total}-row G4 exclusion block"
        )
    raw["reviewed_share_exclusions"] = {
        **existing_exclusions,
        "enabled": False,
        "activation_reason": (
            f"Replaced by exact {expected_total}-row exchange-reference completion"
        ),
    }

    root = private_root.expanduser().resolve()
    private_sources = [
        {
            "source_id": "private-g4-nyse-taq-master-exact-completion",
            "record_kind": "shares_outstanding",
            "source_family": "nyse_daily_taq_master",
            "path": str(root / PRIVATE_FILES["nyse"]),
            "enabled": True,
            "authorized": True,
            "data_classification": "authorized_reference_data",
            "license_reference": _nonblank(nyse_license_reference, "nyse_license_reference"),
            "delimiter": ",",
            "encoding": "utf-8",
            "timezone": "America/New_York",
            "column_map": COLUMN_MAP,
            "notes": "Private exact ACO completion generated from historical NYSE Daily TAQ Master files.",
        },
        {
            "source_id": "private-g4-nasdaq-fundamental-exact-completion",
            "record_kind": "shares_outstanding",
            "source_family": "generic_authorized_reference_data",
            "path": str(root / PRIVATE_FILES["nasdaq"]),
            "enabled": True,
            "authorized": True,
            "data_classification": "authorized_reference_data",
            "license_reference": _nonblank(
                nasdaq_license_reference, "nasdaq_license_reference"
            ),
            "delimiter": ",",
            "encoding": "utf-8",
            "timezone": "America/New_York",
            "column_map": COLUMN_MAP,
            "notes": "Private exact CGNX completion generated from historical Nasdaq Fundamental Data.",
        },
    ]

    ids = {str(source.get("source_id", "")) for source in raw["sources"]}
    if any(source["source_id"] in ids for source in private_sources):
        raise ValueError("base contract already contains a G4 exact-completion source")
    raw["sources"].extend(private_sources)

    output = output_contract.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    resolver.load_contract(output)

    return {
        "schema_version": "2",
        "status": "STAGED_EXACT_G4_CONTRACT",
        "base_contract": str(base_path),
        "base_contract_sha256": _sha256(base_path),
        "activation_contract": str(output),
        "activation_contract_sha256": _sha256(output),
        "reviewed_share_exclusions_enabled": False,
        "private_source_count_added": 2,
        "residual_rows_replaced": expected_total,
        "g4_target_state": receipt["g4_target_state"],
        "private_inputs": audit,
        "canonical_outputs_modified": False,
    }


def validate_resolver_output(resolver_dir: Path) -> dict[str, Any]:
    summary_path = resolver_dir / "metadata_readiness_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected = {
        "shares_symbol_dates_resolved": 3828,
        "shares_symbol_dates_excluded": 0,
        "shares_symbol_dates_accounted_for": 3828,
        "shares_symbol_dates_unresolved": 0,
        "ready_g4_shares_outstanding": True,
    }
    actual = {key: summary.get(key) for key in expected}
    if actual != expected:
        raise ValueError(f"G4 resolver did not reach exact 3828/3828: {actual!r}")
    return actual


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Stage an exact private G4 metadata contract after the canonical residual "
            "NYSE/Nasdaq materialization succeeds. This never modifies canonical "
            "metadata outputs by itself."
        )
    )
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--base-contract", type=Path, default=DEFAULT_BASE_CONTRACT)
    parser.add_argument("--output-contract", type=Path, required=True)
    parser.add_argument("--nyse-license-reference", required=True)
    parser.add_argument("--nasdaq-license-reference", required=True)
    parser.add_argument("--receipt-output", type=Path)
    parser.add_argument("--verify-resolver-dir", type=Path)
    args = parser.parse_args()

    result = build_activation_contract(
        private_root=args.private_root,
        base_contract=args.base_contract,
        output_contract=args.output_contract,
        nyse_license_reference=args.nyse_license_reference,
        nasdaq_license_reference=args.nasdaq_license_reference,
    )
    if args.verify_resolver_dir is not None:
        result["resolver_exact_g4"] = validate_resolver_output(args.verify_resolver_dir)
        result["status"] = "VALIDATED_EXACT_G4_3828_OF_3828"

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.receipt_output:
        path = args.receipt_output.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
