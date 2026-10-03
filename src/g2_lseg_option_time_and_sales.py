from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Mapping

import g2_lseg_datascope_client as datascope


MAX_LSEG_CONTRACTS_PER_EXTRACTION = 30000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validated_contract_rics(payload: Mapping[str, object]) -> tuple[str, str, list[str]]:
    if str(payload.get("schema_version") or "") != "1":
        raise ValueError("option contract manifest schema_version must equal '1'")

    historical_symbol = str(payload.get("historical_symbol") or "").strip().upper()
    trade_date = str(payload.get("trade_date") or "").strip()
    if not historical_symbol or not trade_date:
        raise ValueError("option contract manifest is missing historical_symbol/trade_date")
    date.fromisoformat(trade_date)

    summary = dict(payload.get("summary") or {})
    if not bool(summary.get("historical_contract_set_ready_for_time_and_sales")):
        raise ValueError(
            "option contract manifest is not ready for Time & Sales: "
            "historical-chain evidence is required"
        )

    rics: list[str] = []
    for raw in list(payload.get("contracts") or []):
        if not isinstance(raw, Mapping):
            raise ValueError("option contract row must be an object")
        if raw.get("historical_date_evidence") is not True:
            continue
        if str(raw.get("validation_status") or "") != "historical_chain_candidate":
            continue
        row_symbol = str(
            raw.get("historical_symbol") or raw.get("underlying_symbol") or ""
        ).strip().upper()
        if row_symbol != historical_symbol:
            raise ValueError(
                f"historical option contract underlying {row_symbol!r} does not "
                f"match manifest symbol {historical_symbol!r}"
            )
        if str(raw.get("trade_date") or "") != trade_date:
            raise ValueError("historical option contract trade_date drift")
        ric = str(raw.get("source_ric") or "").strip()
        if not ric:
            raise ValueError("historical option contract is missing source_ric")
        rics.append(ric)

    rics = sorted(set(rics))
    if not rics:
        raise ValueError("option contract manifest has no historical-chain contract RICs")
    if len(rics) >= MAX_LSEG_CONTRACTS_PER_EXTRACTION:
        raise ValueError(
            f"validated contract count {len(rics)} reaches/exceeds LSEG's "
            f"{MAX_LSEG_CONTRACTS_PER_EXTRACTION}-instrument expansion limit; "
            "split the extraction before execution"
        )
    return historical_symbol, trade_date, rics


def _receipt_path(output_path: Path) -> Path:
    return Path(str(output_path) + ".receipt.json")


def _completed_receipt(
    receipt_path: Path,
    *,
    contract_sha256: str,
    historical_symbol: str,
    trade_date: str,
    contract_rics: list[str],
    output_path: Path,
) -> bool:
    if not receipt_path.exists() or not output_path.exists():
        return False
    if output_path.stat().st_size <= 0:
        return False
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        payload.get("contract_manifest_sha256") == contract_sha256
        and payload.get("historical_symbol") == historical_symbol
        and payload.get("trade_date") == trade_date
        and payload.get("contract_rics") == contract_rics
        and payload.get("download_completed") is True
    )


def extract_contract_time_and_sales(
    client: datascope.DataScopeClient,
    *,
    contract_manifest_path: Path,
    output_path: Path,
) -> dict:
    contract_path = contract_manifest_path.expanduser().resolve()
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("option contract manifest root must be a JSON object")

    historical_symbol, trade_date, contract_rics = validated_contract_rics(payload)
    destination = datascope.ensure_private_output_path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = _receipt_path(destination)
    contract_sha = sha256_file(contract_path)

    if _completed_receipt(
        receipt_path,
        contract_sha256=contract_sha,
        historical_symbol=historical_symbol,
        trade_date=trade_date,
        contract_rics=contract_rics,
        output_path=destination,
    ):
        return {
            "schema_version": "1",
            "status": "skipped_existing_download",
            "historical_symbol": historical_symbol,
            "trade_date": trade_date,
            "contract_count": len(contract_rics),
            "contract_rics": contract_rics,
            "output_path": str(destination),
            "receipt_path": str(receipt_path),
            "contract_manifest_sha256": contract_sha,
            "download_completed": True,
            "validation_promoted": False,
            "g2_coverage_change": 0,
        }

    vendor_receipt = client.extract_time_and_sales(
        contract_rics,
        trade_date,
        destination,
    )
    receipt = {
        "schema_version": "1",
        "status": "downloaded_pending_content_validation",
        "historical_symbol": historical_symbol,
        "trade_date": trade_date,
        "contract_count": len(contract_rics),
        "contract_rics": contract_rics,
        "output_path": str(destination),
        "receipt_path": str(receipt_path),
        "contract_manifest_path_name": contract_path.name,
        "contract_manifest_sha256": contract_sha,
        "download_completed": True,
        "vendor_receipt": vendor_receipt,
        "validation_promoted": False,
        "g2_coverage_change": 0,
    }
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download LSEG Tick History Time & Sales only for historical-chain-"
            "validated option contracts into a private output path."
        )
    )
    parser.add_argument("--contract-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    username, password = datascope._credentials_from_environment()
    client = datascope.DataScopeClient(username, password)
    receipt = extract_contract_time_and_sales(
        client,
        contract_manifest_path=args.contract_json,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "historical_symbol": receipt["historical_symbol"],
                "trade_date": receipt["trade_date"],
                "contract_count": receipt["contract_count"],
                "output_path": receipt["output_path"],
                "receipt_path": receipt["receipt_path"],
                "validation_promoted": False,
                "g2_coverage_change": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
