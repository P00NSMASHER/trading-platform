from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

import g2_lseg_datascope_execution_plan as execution
import g2_lseg_request_manifest as manifest
from g2_lseg_trth_normalizer import parse_opra_option_ric

ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plan() -> dict:
    base = manifest.build_plan(
        manifest._read_csv(ROOT / manifest.DEFAULT_MAPPING),
        manifest._read_csv(ROOT / manifest.DEFAULT_SECONDARY),
        manifest._read_csv(ROOT / manifest.DEFAULT_EVENT_MAPPING),
        manifest._read_csv(ROOT / manifest.DEFAULT_CORE),
        manifest._read_csv(ROOT / manifest.DEFAULT_OPTIONS),
    )
    return execution.build_execution_plan(base)


def expected_task(plan: dict, *, historical_symbol: str, trade_date: str) -> dict:
    date.fromisoformat(trade_date)
    rows = [
        row
        for row in plan["option_underlying_dates"]
        if str(row["historical_symbol"]) == historical_symbol
        and str(row["trade_date"]) == trade_date
    ]
    if len(rows) != 1:
        raise ValueError(
            f"{historical_symbol} {trade_date}: expected exactly one frozen "
            f"option-underlying task, found {len(rows)}"
        )
    return rows[0]


def extract_identifier_strings(payload: object) -> set[str]:
    """
    Recursively collect identifier-like strings from DataScope discovery JSON.

    This intentionally does not assume one response schema because
    FuturesAndOptionsSearch and HistoricalChainResolution nest identifiers
    differently.
    """
    found: set[str] = set()

    def walk(value: object, key: str = "") -> None:
        if isinstance(value, Mapping):
            for child_key, child_value in value.items():
                walk(child_value, str(child_key))
            return
        if isinstance(value, list):
            for child in value:
                walk(child, key)
            return
        if not isinstance(value, str):
            return

        lowered = key.lower()
        if lowered in {
            "identifier",
            "ric",
            "#ric",
            "instrumentidentifier",
        }:
            found.add(value.strip())

    walk(payload)
    return {value for value in found if value}


def _parse_contracts(
    identifiers: Iterable[str],
    *,
    historical_symbol: str,
    trade_date: str,
    evidence_method: str,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    requested_date = date.fromisoformat(trade_date)
    contracts: list[dict[str, object]] = []
    rejected: list[dict[str, str]] = []

    for ric in sorted(set(str(value).strip() for value in identifiers if value)):
        if not ric.endswith(".U"):
            continue
        try:
            parsed = parse_opra_option_ric(ric)
        except ValueError as exc:
            rejected.append(
                {
                    "source_ric": ric,
                    "reason": f"unparseable_option_ric: {exc}",
                }
            )
            continue

        if str(parsed["underlying_symbol"]).upper() != historical_symbol.upper():
            rejected.append(
                {
                    "source_ric": ric,
                    "reason": (
                        "underlying_root_mismatch: "
                        f"{parsed['underlying_symbol']} != {historical_symbol}"
                    ),
                }
            )
            continue

        expiration = date.fromisoformat(str(parsed["expiration"]))
        if expiration < requested_date:
            rejected.append(
                {
                    "source_ric": ric,
                    "reason": (
                        f"expired_before_trade_date: {expiration.isoformat()} "
                        f"< {trade_date}"
                    ),
                }
            )
            continue

        contracts.append(
            {
                **parsed,
                "trade_date": trade_date,
                "historical_symbol": historical_symbol,
                "evidence_method": evidence_method,
                "historical_date_evidence": (
                    evidence_method == "historical_chain_resolution"
                ),
                "validation_status": (
                    "historical_chain_candidate"
                    if evidence_method == "historical_chain_resolution"
                    else "search_candidate_requires_historical_confirmation"
                ),
            }
        )

    return contracts, rejected


def validate_discovery(
    *,
    plan: dict,
    historical_symbol: str,
    trade_date: str,
    search_payload: object | None = None,
    historical_chain_payload: object | None = None,
) -> dict:
    task = expected_task(
        plan,
        historical_symbol=historical_symbol,
        trade_date=trade_date,
    )

    search_contracts: list[dict[str, object]] = []
    chain_contracts: list[dict[str, object]] = []
    rejected: list[dict[str, str]] = []

    if search_payload is not None:
        search_contracts, search_rejected = _parse_contracts(
            extract_identifier_strings(search_payload),
            historical_symbol=historical_symbol,
            trade_date=trade_date,
            evidence_method="futures_and_options_search",
        )
        rejected.extend(search_rejected)

    if historical_chain_payload is not None:
        chain_contracts, chain_rejected = _parse_contracts(
            extract_identifier_strings(historical_chain_payload),
            historical_symbol=historical_symbol,
            trade_date=trade_date,
            evidence_method="historical_chain_resolution",
        )
        rejected.extend(chain_rejected)

    search_by_ric = {str(row["source_ric"]): row for row in search_contracts}
    chain_by_ric = {str(row["source_ric"]): row for row in chain_contracts}

    all_rics = sorted(set(search_by_ric) | set(chain_by_ric))
    contracts: list[dict[str, object]] = []

    for ric in all_rics:
        if ric in chain_by_ric:
            row = dict(chain_by_ric[ric])
            row["also_seen_in_search"] = ric in search_by_ric
        else:
            row = dict(search_by_ric[ric])
            row["also_seen_in_search"] = True
        contracts.append(row)

    historical_candidates = [
        row for row in contracts if bool(row["historical_date_evidence"])
    ]
    search_only = [
        row for row in contracts if not bool(row["historical_date_evidence"])
    ]

    return {
        "schema_version": "1",
        "purpose": (
            "Convert authorized LSEG option-discovery responses into a public-safe "
            "contract candidate manifest. Historical-chain membership is treated as "
            "date-specific candidate evidence; search-only results remain fail-closed."
        ),
        "trade_date": trade_date,
        "historical_symbol": historical_symbol,
        "underlying_candidate_rics": list(task["candidate_rics"]),
        "mapping_class": str(task["mapping_class"]),
        "summary": {
            "parsed_contracts": len(contracts),
            "historical_chain_candidates": len(historical_candidates),
            "search_only_candidates": len(search_only),
            "rejected_identifiers": len(rejected),
            "historical_contract_set_ready_for_time_and_sales": (
                historical_chain_payload is not None
                and len(historical_candidates) > 0
            ),
            "g2_coverage_change": False,
        },
        "contracts": contracts,
        "rejected": rejected,
    }


def validate_files(
    *,
    search_path: Path | None,
    chain_path: Path | None,
    historical_symbol: str,
    trade_date: str,
    plan: dict | None = None,
) -> dict:
    if search_path is None and chain_path is None:
        raise ValueError("at least one discovery input is required")

    search_payload = None
    chain_payload = None
    receipts: list[dict[str, object]] = []

    if search_path is not None:
        resolved = search_path.expanduser().resolve()
        search_payload = json.loads(resolved.read_text(encoding="utf-8"))
        receipts.append(
            {
                "kind": "futures_and_options_search",
                "path_name": resolved.name,
                "size_bytes": resolved.stat().st_size,
                "sha256": sha256_file(resolved),
            }
        )

    if chain_path is not None:
        resolved = chain_path.expanduser().resolve()
        chain_payload = json.loads(resolved.read_text(encoding="utf-8"))
        receipts.append(
            {
                "kind": "historical_chain_resolution",
                "path_name": resolved.name,
                "size_bytes": resolved.stat().st_size,
                "sha256": sha256_file(resolved),
            }
        )

    payload = validate_discovery(
        plan=_plan() if plan is None else plan,
        historical_symbol=historical_symbol,
        trade_date=trade_date,
        search_payload=search_payload,
        historical_chain_payload=chain_payload,
    )
    payload["input_receipts"] = receipts
    return payload


def public_contract_manifest(payload: dict) -> dict:
    return {
        "schema_version": payload["schema_version"],
        "purpose": payload["purpose"],
        "trade_date": payload["trade_date"],
        "historical_symbol": payload["historical_symbol"],
        "underlying_candidate_rics": payload["underlying_candidate_rics"],
        "mapping_class": payload["mapping_class"],
        "summary": payload["summary"],
        "input_receipts": payload.get("input_receipts", []),
        "contracts": payload["contracts"],
        "rejected": payload["rejected"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate authorized LSEG option discovery results into a "
            "public-safe historical contract candidate manifest."
        )
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--search-json", type=Path)
    parser.add_argument("--historical-chain-json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = validate_files(
        search_path=args.search_json,
        chain_path=args.historical_chain_json,
        historical_symbol=args.symbol,
        trade_date=args.date,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(public_contract_manifest(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
