from __future__ import annotations

import argparse
import json
from pathlib import Path

import g2_lseg_datascope_client as datascope
import g2_lseg_datascope_execution_plan as execution
import g2_lseg_delivery_normalizer as delivery
import g2_lseg_request_manifest as manifest

ROOT = Path(__file__).resolve().parents[1]
MAX_LIVE_EQUITY_DATES = 5


def _execution_plan() -> dict:
    base = manifest.build_plan(
        manifest._read_csv(ROOT / manifest.DEFAULT_MAPPING),
        manifest._read_csv(ROOT / manifest.DEFAULT_SECONDARY),
        manifest._read_csv(ROOT / manifest.DEFAULT_EVENT_MAPPING),
        manifest._read_csv(ROOT / manifest.DEFAULT_CORE),
        manifest._read_csv(ROOT / manifest.DEFAULT_OPTIONS),
    )
    return execution.build_execution_plan(base)


def build_equity_date_batch(*, start: int = 0, limit: int = 5) -> dict:
    if start < 0:
        raise ValueError("start must be non-negative")
    if limit <= 0:
        raise ValueError("limit must be positive")

    queue = list(_execution_plan()["equity_date_batches"])
    selected = queue[start : start + limit]
    return {
        "schema_version": "1",
        "purpose": (
            "Dry-run-first bounded LSEG equity date acquisition plan. "
            "No network call, credential read, purchase, entitlement assertion, "
            "or G2 coverage mutation occurs while building the plan."
        ),
        "queue_size": len(queue),
        "start": start,
        "requested_limit": limit,
        "selected_count": len(selected),
        "next_start": start + len(selected) if selected else None,
        "tasks": selected,
        "network_execution_enabled": False,
        "g2_coverage_change": 0,
    }


def _completion_matches(path: Path, *, trade_date: str, candidate_rics: list[str]) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    normalization_summary = Path(str(payload.get("normalization_summary_path") or ""))
    return (
        payload.get("trade_date") == trade_date
        and payload.get("candidate_rics") == candidate_rics
        and payload.get("g2_coverage_change") == 0
        and normalization_summary.exists()
    )


def execute_equity_date_batch(
    client: datascope.DataScopeClient,
    batch: dict,
    output_dir: Path,
) -> dict:
    tasks = list(batch["tasks"])
    if len(tasks) > MAX_LIVE_EQUITY_DATES:
        raise ValueError(
            f"live equity acquisition is capped at {MAX_LIVE_EQUITY_DATES} dates per invocation"
        )

    destination = datascope.ensure_private_output_path(output_dir)
    raw_dir = destination / "raw"
    normalized_root = destination / "normalized"
    receipt_dir = destination / "receipts"
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_root.mkdir(parents=True, exist_ok=True)
    receipt_dir.mkdir(parents=True, exist_ok=True)

    receipts: list[dict[str, object]] = []
    for task in tasks:
        trade_date = str(task["trade_date"])
        candidate_rics = [str(value) for value in task["candidate_rics"]]
        raw_path = raw_dir / f"lseg_equity_{trade_date}.csv.gz"
        normalization_dir = normalized_root / trade_date
        completion_path = receipt_dir / f"lseg_equity_{trade_date}.json"

        if (
            raw_path.exists()
            and raw_path.stat().st_size > 0
            and _completion_matches(
                completion_path,
                trade_date=trade_date,
                candidate_rics=candidate_rics,
            )
        ):
            receipts.append(
                {
                    "trade_date": trade_date,
                    "status": "skipped_existing_complete_date",
                    "raw_output_path": str(raw_path),
                    "completion_receipt": str(completion_path),
                    "g2_coverage_change": 0,
                }
            )
            continue

        extraction = client.extract_time_and_sales(
            candidate_rics,
            trade_date,
            raw_path,
        )
        normalization = delivery.normalize_delivery(
            raw_path,
            lane="equity",
            trade_date=trade_date,
            output_dir=normalization_dir,
        )
        completion = {
            "schema_version": "1",
            "trade_date": trade_date,
            "historical_symbols": list(task["historical_symbols"]),
            "candidate_rics": candidate_rics,
            "raw_receipt": extraction,
            "normalization_summary_path": normalization["summary_path"],
            "normalized_rows": normalization["normalized_rows"],
            "rejected_rows": normalization["rejected_rows"],
            "authorization_asserted": False,
            "requires_entitlement_binding": True,
            "requires_production_content_preflight": True,
            "g2_coverage_change": 0,
        }
        completion_path.write_text(
            json.dumps(completion, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipts.append(
            {
                "trade_date": trade_date,
                "status": "downloaded_and_normalized_pending_entitlement_preflight",
                "raw_output_path": str(raw_path),
                "normalization_summary_path": normalization["summary_path"],
                "completion_receipt": str(completion_path),
                "normalized_rows": normalization["normalized_rows"],
                "rejected_rows": normalization["rejected_rows"],
                "g2_coverage_change": 0,
            }
        )

    return {
        "schema_version": "1",
        "selected_count": len(tasks),
        "network_dates_completed": sum(
            row["status"] == "downloaded_and_normalized_pending_entitlement_preflight"
            for row in receipts
        ),
        "skipped_existing_dates": sum(
            row["status"] == "skipped_existing_complete_date"
            for row in receipts
        ),
        "entitlement_promotions": 0,
        "g2_coverage_change": 0,
        "receipts": receipts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run bounded LSEG equity date acquisitions into private normalized outputs."
    )
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    batch = build_equity_date_batch(start=args.start, limit=args.limit)
    if not args.execute:
        print(json.dumps(batch, indent=2, sort_keys=True))
        return

    if batch["selected_count"] > MAX_LIVE_EQUITY_DATES:
        raise SystemExit(
            f"--execute is capped at {MAX_LIVE_EQUITY_DATES} dates per invocation"
        )
    if args.output_dir is None:
        raise SystemExit("--output-dir is required with --execute")

    username, password = datascope._credentials_from_environment()
    client = datascope.DataScopeClient(username, password)
    result = execute_equity_date_batch(client, batch, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
