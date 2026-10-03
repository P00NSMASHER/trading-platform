from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping

import g2_lseg_datascope_client as datascope
import g2_lseg_historical_ric_validator as ric_validator
import g2_lseg_result_adapter as adapter


MAX_EQUITY_DATE_TASKS = 25


def build_batch(
    *,
    start: int = 0,
    limit: int = MAX_EQUITY_DATE_TASKS,
    execution_plan: Mapping[str, object] | None = None,
) -> dict:
    if start < 0:
        raise ValueError("start must be non-negative")
    if limit <= 0 or limit > MAX_EQUITY_DATE_TASKS:
        raise ValueError(
            f"limit must be between 1 and {MAX_EQUITY_DATE_TASKS}"
        )

    plan = datascope._execution_plan() if execution_plan is None else execution_plan
    queue = list(plan["equity_date_batches"])
    selected = queue[start : start + limit]
    return {
        "schema_version": "1",
        "queue_size": len(queue),
        "start": start,
        "limit": limit,
        "selected_count": len(selected),
        "next_start": start + len(selected) if selected else None,
        "tasks": selected,
        "network_execution_enabled": False,
    }


def _raw_receipt_path(raw_path: Path) -> Path:
    return Path(str(raw_path) + ".receipt.json")


def _raw_download_complete(
    raw_path: Path,
    *,
    trade_date: str,
    candidate_rics: list[str],
) -> bool:
    receipt_path = _raw_receipt_path(raw_path)
    if not raw_path.exists() or raw_path.stat().st_size <= 0:
        return False
    if not receipt_path.exists():
        return False
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        payload.get("trade_date") == trade_date
        and payload.get("candidate_rics") == candidate_rics
        and payload.get("download_completed") is True
    )


def _download_equity_date(
    client: datascope.DataScopeClient,
    *,
    trade_date: str,
    candidate_rics: list[str],
    raw_path: Path,
) -> dict:
    if _raw_download_complete(
        raw_path,
        trade_date=trade_date,
        candidate_rics=candidate_rics,
    ):
        return {
            "status": "skipped_existing_download",
            "trade_date": trade_date,
            "candidate_rics": candidate_rics,
            "raw_path": str(raw_path),
            "receipt_path": str(_raw_receipt_path(raw_path)),
            "validation_promoted": False,
            "g2_coverage_change": 0,
        }

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    vendor_receipt = client.extract_time_and_sales(
        candidate_rics,
        trade_date,
        raw_path,
    )
    receipt = {
        "schema_version": "1",
        "status": "downloaded_pending_historical_ric_validation",
        "trade_date": trade_date,
        "candidate_rics": candidate_rics,
        "raw_path": str(raw_path),
        "receipt_path": str(_raw_receipt_path(raw_path)),
        "download_completed": True,
        "vendor_receipt": vendor_receipt,
        "validation_promoted": False,
        "g2_coverage_change": 0,
    }
    _raw_receipt_path(raw_path).write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def process_batch(
    batch: Mapping[str, object],
    *,
    raw_dir: Path,
    validation_dir: Path,
    adapted_dir: Path,
    client: datascope.DataScopeClient | None = None,
    validation_plan: dict | None = None,
) -> dict:
    raw_root = datascope.ensure_private_output_path(raw_dir)
    validation_root = datascope.ensure_private_output_path(validation_dir)
    adapted_root = datascope.ensure_private_output_path(adapted_dir)
    raw_root.mkdir(parents=True, exist_ok=True)
    validation_root.mkdir(parents=True, exist_ok=True)
    adapted_root.mkdir(parents=True, exist_ok=True)

    plan = ric_validator._plan() if validation_plan is None else validation_plan
    results: list[dict[str, object]] = []

    for raw_task in list(batch["tasks"]):
        task = dict(raw_task)
        trade_date = str(task["trade_date"])
        candidate_rics = [str(x) for x in list(task["candidate_rics"])]
        raw_path = raw_root / trade_date / "equity.csv.gz"
        row: dict[str, object] = {
            "trade_date": trade_date,
            "candidate_ric_count": len(candidate_rics),
            "raw_path": str(raw_path),
            "validation_promoted": False,
            "g2_coverage_change": 0,
        }

        if client is not None:
            download = _download_equity_date(
                client,
                trade_date=trade_date,
                candidate_rics=candidate_rics,
                raw_path=raw_path,
            )
            row["download_status"] = download["status"]
            row["raw_receipt_path"] = download["receipt_path"]
        elif not raw_path.exists():
            row["status"] = "raw_missing_download_not_requested"
            results.append(row)
            continue
        else:
            row["download_status"] = "existing_raw_input"

        if not raw_path.exists() or raw_path.stat().st_size <= 0:
            row["status"] = "raw_delivery_missing_or_empty"
            results.append(row)
            continue

        try:
            validation = ric_validator.validate_file(
                raw_path,
                trade_date=trade_date,
                plan=plan,
            )
            validation_path = validation_root / f"{trade_date}.json"
            validation_path.write_text(
                json.dumps(validation, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            row["validation_path"] = str(validation_path)

            adapted = adapter.adapt_equity_rows(
                adapter.read_rows(raw_path),
                trade_date=trade_date,
                validation_payload=validation,
            )
            date_adapted_dir = adapted_root / trade_date / "equity"
            adaptation_receipt = adapter.write_adaptation(
                adapted,
                output_dir=date_adapted_dir,
                input_path=raw_path,
            )
            row["adapted_dir"] = str(date_adapted_dir)
            row["adaptation_receipt_path"] = str(
                date_adapted_dir / "lseg_adaptation_receipt.json"
            )

            validation_summary = dict(validation["summary"])
            adaptation_summary = dict(adaptation_receipt["summary"])
            expected = int(validation_summary["expected_historical_symbols"])
            validated = int(validation_summary["validated_single_candidate"])
            all_mappings_validated = expected > 0 and validated == expected
            all_lanes_observed = bool(
                adaptation_summary["all_selected_symbols_have_trade_and_quote_rows"]
            )
            ready = all_mappings_validated and all_lanes_observed

            row["expected_historical_symbols"] = expected
            row["validated_single_candidate"] = validated
            row["all_historical_mappings_validated"] = all_mappings_validated
            row["all_selected_symbols_have_trade_and_quote_rows"] = (
                all_lanes_observed
            )
            row["date_ready_for_source_contract"] = ready
            row["status"] = (
                "adapted_complete_pending_production_content_preflight"
                if ready
                else "adapted_incomplete_validation"
            )
        except (OSError, TypeError, ValueError) as exc:
            row["status"] = "validation_or_adaptation_failed"
            row["error_type"] = type(exc).__name__
            row["error"] = str(exc)

        results.append(row)

    summary = {
        "schema_version": "1",
        "queue_size": int(batch["queue_size"]),
        "start": int(batch["start"]),
        "selected_count": int(batch["selected_count"]),
        "next_start": batch["next_start"],
        "network_downloads_completed": sum(
            row.get("download_status")
            == "downloaded_pending_historical_ric_validation"
            for row in results
        ),
        "network_downloads_skipped_existing": sum(
            row.get("download_status") == "skipped_existing_download"
            for row in results
        ),
        "dates_ready_for_source_contract": sum(
            bool(row.get("date_ready_for_source_contract"))
            for row in results
        ),
        "dates_incomplete_or_failed": sum(
            row.get("status")
            not in {"adapted_complete_pending_production_content_preflight"}
            for row in results
        ),
        "validation_promotions": 0,
        "g2_coverage_change": 0,
        "results": results,
    }
    (adapted_root / "equity_date_pipeline_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Process bounded LSEG full-date equity Time & Sales batches through "
            "historical RIC validation and canonical G2 adaptation."
        )
    )
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--validation-dir", type=Path, required=True)
    parser.add_argument("--adapted-dir", type=Path, required=True)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=MAX_EQUITY_DATE_TASKS)
    parser.add_argument("--execute-downloads", action="store_true")
    args = parser.parse_args()

    batch = build_batch(start=args.start, limit=args.limit)

    client = None
    if args.execute_downloads:
        username, password = datascope._credentials_from_environment()
        client = datascope.DataScopeClient(username, password)

    summary = process_batch(
        batch,
        raw_dir=args.raw_dir,
        validation_dir=args.validation_dir,
        adapted_dir=args.adapted_dir,
        client=client,
    )
    print(
        json.dumps(
            {
                "selected_count": summary["selected_count"],
                "network_downloads_completed": summary[
                    "network_downloads_completed"
                ],
                "dates_ready_for_source_contract": summary[
                    "dates_ready_for_source_contract"
                ],
                "dates_incomplete_or_failed": summary[
                    "dates_incomplete_or_failed"
                ],
                "next_start": summary["next_start"],
                "g2_coverage_change": 0,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
