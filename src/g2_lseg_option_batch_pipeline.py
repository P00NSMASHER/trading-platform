from __future__ import annotations

import argparse
import json
from pathlib import Path

import g2_lseg_datascope_client as datascope
import g2_lseg_option_contract_validator as validator
import g2_lseg_option_time_and_sales as option_ts


MAX_OPTION_PIPELINE_TASKS = 25


def discover_batch_files(input_dir: Path) -> list[Path]:
    root = datascope.ensure_private_output_path(input_dir)
    if not root.exists():
        raise FileNotFoundError(f"option validation input directory does not exist: {root}")
    files = sorted(
        path for path in root.glob("*.json")
        if path.is_file() and not path.name.endswith(".receipt.json")
    )
    if not files:
        raise ValueError(f"{root}: no combined option validation JSON files found")
    return files


def select_batch(
    input_dir: Path,
    *,
    start: int = 0,
    limit: int = MAX_OPTION_PIPELINE_TASKS,
) -> dict:
    if start < 0:
        raise ValueError("start must be non-negative")
    if limit <= 0 or limit > MAX_OPTION_PIPELINE_TASKS:
        raise ValueError(
            f"limit must be between 1 and {MAX_OPTION_PIPELINE_TASKS}"
        )

    files = discover_batch_files(input_dir)
    selected = files[start : start + limit]
    return {
        "schema_version": "1",
        "input_dir": str(datascope.ensure_private_output_path(input_dir)),
        "queue_size": len(files),
        "start": start,
        "limit": limit,
        "selected_count": len(selected),
        "next_start": start + len(selected) if selected else None,
        "files": selected,
    }


def _contract_output_path(contract_dir: Path, payload: dict) -> Path:
    symbol = str(payload["historical_symbol"])
    trade_date = str(payload["trade_date"])
    return contract_dir / f"{trade_date}_{symbol}.option-contracts.json"


def process_batch(
    batch: dict,
    *,
    contract_dir: Path,
    download_dir: Path | None = None,
    client: datascope.DataScopeClient | None = None,
) -> dict:
    destination = datascope.ensure_private_output_path(contract_dir)
    destination.mkdir(parents=True, exist_ok=True)

    download_destination = None
    if client is not None:
        if download_dir is None:
            raise ValueError("download_dir is required when client is supplied")
        download_destination = datascope.ensure_private_output_path(download_dir)
        download_destination.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, object]] = []
    for input_path in list(batch["files"]):
        try:
            validated = validator.validate_batch_file(input_path)
            public_manifest = validator.public_contract_manifest(validated)
            contract_path = _contract_output_path(destination, public_manifest)
            contract_path.write_text(
                json.dumps(public_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            ready = bool(
                public_manifest["summary"][
                    "historical_contract_set_ready_for_time_and_sales"
                ]
            )
            row: dict[str, object] = {
                "input_path_name": input_path.name,
                "historical_symbol": public_manifest["historical_symbol"],
                "trade_date": public_manifest["trade_date"],
                "contract_path": str(contract_path),
                "historical_contract_count": int(
                    public_manifest["summary"]["historical_chain_candidates"]
                ),
                "contract_ready_for_time_and_sales": ready,
                "validation_promoted": False,
                "g2_coverage_change": 0,
            }

            if not ready:
                row["status"] = "validated_no_historical_contracts"
                results.append(row)
                continue

            if client is None:
                row["status"] = "contract_ready_download_not_requested"
                results.append(row)
                continue

            output_path = (
                download_destination
                / f"{public_manifest['trade_date']}_{public_manifest['historical_symbol']}.options.csv.gz"
            )
            receipt = option_ts.extract_contract_time_and_sales(
                client,
                contract_manifest_path=contract_path,
                output_path=output_path,
            )
            row["status"] = str(receipt["status"])
            row["download_output_path"] = receipt["output_path"]
            row["download_receipt_path"] = receipt["receipt_path"]
            row["download_contract_count"] = receipt["contract_count"]
            results.append(row)
        except (OSError, TypeError, ValueError) as exc:
            results.append(
                {
                    "input_path_name": input_path.name,
                    "status": "validation_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "validation_promoted": False,
                    "g2_coverage_change": 0,
                }
            )

    summary = {
        "schema_version": "1",
        "queue_size": int(batch["queue_size"]),
        "start": int(batch["start"]),
        "selected_count": int(batch["selected_count"]),
        "next_start": batch["next_start"],
        "contract_manifests_written": sum(
            bool(row.get("contract_path")) for row in results
        ),
        "contracts_ready_for_time_and_sales": sum(
            bool(row.get("contract_ready_for_time_and_sales"))
            for row in results
        ),
        "network_downloads_completed": sum(
            row.get("status") == "downloaded_pending_content_validation"
            for row in results
        ),
        "network_downloads_skipped_existing": sum(
            row.get("status") == "skipped_existing_download"
            for row in results
        ),
        "validation_failures": sum(
            row.get("status") == "validation_failed" for row in results
        ),
        "validation_promotions": 0,
        "g2_coverage_change": 0,
        "results": results,
    }
    (destination / "option_batch_pipeline_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a bounded batch of private LSEG option discovery outputs, "
            "materialize public-safe historical contract manifests, and optionally "
            "download Time & Sales for only historical-chain-validated contracts."
        )
    )
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--contract-dir", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=MAX_OPTION_PIPELINE_TASKS)
    parser.add_argument("--execute-downloads", action="store_true")
    parser.add_argument("--download-dir", type=Path)
    args = parser.parse_args()

    batch = select_batch(
        args.input_dir,
        start=args.start,
        limit=args.limit,
    )

    client = None
    if args.execute_downloads:
        if args.download_dir is None:
            raise SystemExit("--download-dir is required with --execute-downloads")
        username, password = datascope._credentials_from_environment()
        client = datascope.DataScopeClient(username, password)

    summary = process_batch(
        batch,
        contract_dir=args.contract_dir,
        download_dir=args.download_dir,
        client=client,
    )
    print(
        json.dumps(
            {
                "selected_count": summary["selected_count"],
                "contracts_ready_for_time_and_sales": summary[
                    "contracts_ready_for_time_and_sales"
                ],
                "network_downloads_completed": summary[
                    "network_downloads_completed"
                ],
                "validation_failures": summary["validation_failures"],
                "next_start": summary["next_start"],
                "g2_coverage_change": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
