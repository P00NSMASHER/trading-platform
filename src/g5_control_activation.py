from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import metadata_resolver as resolver


DEFAULT_BASE_CONTRACT = Path("config/metadata_sources.public_progress.json")
DEFAULT_EVENTS = Path("data/processed/historical_events.csv")


class G5ControlActivationError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path, *, delimiter: str = ",", encoding: str = "utf-8") -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    return fields, rows


def _parse_date(value: str, *, label: str) -> str:
    raw = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise G5ControlActivationError(
            f"{label} must be a valid YYYY-MM-DD date"
        ) from exc


def _event_context(events_path: Path) -> tuple[dict[str, int], dict[str, Any]]:
    fields, rows = _read_csv(events_path)
    if "first_documented_illicit_trade_ts" not in fields:
        raise G5ControlActivationError(
            "historical events missing first_documented_illicit_trade_ts"
        )
    counts: dict[str, int] = {}
    cutoffs: dict[str, Any] = {}
    for row_no, row in enumerate(rows, 2):
        raw_ts = row["first_documented_illicit_trade_ts"]
        trade_date = _parse_date(raw_ts[:10], label=f"historical event row {row_no}")
        cutoff = resolver._event_trade_dt(raw_ts)
        counts[trade_date] = counts.get(trade_date, 0) + 1
        prior = cutoffs.get(trade_date)
        if prior is None or cutoff < prior:
            cutoffs[trade_date] = cutoff
    if not counts:
        raise G5ControlActivationError("historical events contain no event dates")
    return counts, cutoffs


def _load_current_exclusions(
    base_contract: Path,
    *,
    event_counts: dict[str, int],
) -> tuple[dict[str, Any], dict[str, Any], Path, dict[str, dict[str, Any]]]:
    base_path = base_contract.expanduser().resolve()
    raw = json.loads(base_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "1":
        raise G5ControlActivationError("base metadata contract schema_version must equal '1'")
    if not isinstance(raw.get("sources"), list):
        raise G5ControlActivationError("base metadata contract sources must be a list")

    spec = raw.get("reviewed_control_exclusions")
    if not isinstance(spec, dict) or not bool(spec.get("enabled", False)):
        raise G5ControlActivationError(
            "base contract must contain an enabled reviewed_control_exclusions block"
        )
    if spec.get("mode") != "reviewed_fail_closed_exclusions":
        raise G5ControlActivationError(
            "reviewed_control_exclusions mode must be reviewed_fail_closed_exclusions"
        )

    raw_path = str(spec.get("path", "")).strip()
    expected_sha = str(spec.get("expected_sha256", "")).strip().lower()
    expected_count = int(spec.get("expected_count", -1))
    if not raw_path or len(expected_sha) != 64:
        raise G5ControlActivationError("reviewed control exclusion path/hash is invalid")

    receipt_path = Path(raw_path)
    if not receipt_path.is_absolute():
        receipt_path = (base_path.parent.parent / receipt_path).resolve()
    if not receipt_path.is_file():
        raise FileNotFoundError(receipt_path)
    if _sha256(receipt_path) != expected_sha:
        raise G5ControlActivationError("reviewed control exclusion receipt SHA-256 mismatch")

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema_version") != "1" or receipt.get("research_use_only") is not True:
        raise G5ControlActivationError("reviewed control exclusion receipt is not admissible")
    rows = receipt.get("exclusions")
    if not isinstance(rows, list):
        raise G5ControlActivationError("reviewed control exclusion receipt exclusions must be a list")
    if len(rows) != expected_count:
        raise G5ControlActivationError(
            f"reviewed control exclusion count mismatch: expected {expected_count}, got {len(rows)}"
        )

    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise G5ControlActivationError("reviewed control exclusion row must be an object")
        event_date = _parse_date(str(row.get("event_date", "")), label="reviewed control exclusion event_date")
        if event_date in by_date:
            raise G5ControlActivationError(f"duplicate reviewed control exclusion: {event_date}")
        if event_date not in event_counts:
            raise G5ControlActivationError(f"reviewed control exclusion references non-event date: {event_date}")
        if int(row.get("event_count", -1)) != event_counts[event_date]:
            raise G5ControlActivationError(f"reviewed control exclusion event_count mismatch: {event_date}")
        if str(row.get("resolution_status", "")).strip() != str(spec.get("require_resolution_status", "")).strip():
            raise G5ControlActivationError(f"reviewed control exclusion status mismatch: {event_date}")
        by_date[event_date] = dict(row)

    return raw, spec, receipt_path, by_date


def _load_source_manifest(
    manifest_path: Path,
    *,
    required_event_dates: set[str],
    event_cutoffs: dict[str, Any],
    currently_excluded_dates: set[str],
    activated_dates: set[str],
    existing_source_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    path = manifest_path.expanduser().resolve()
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema_version") != "1":
        raise G5ControlActivationError("control source manifest schema_version must equal '1'")
    if obj.get("research_use_only") is not True:
        raise G5ControlActivationError("control source manifest must set research_use_only=true")
    raw_sources = obj.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise G5ControlActivationError("control source manifest must contain at least one source")

    contract_sources: list[dict[str, Any]] = []
    source_audit: list[dict[str, Any]] = []
    observed_dates: set[str] = set()
    seen_ids: set[str] = set()

    for index, raw_source in enumerate(raw_sources, 1):
        if not isinstance(raw_source, dict):
            raise G5ControlActivationError(f"control source {index} must be an object")
        for key in raw_source:
            lowered = str(key).lower()
            if any(token in lowered for token in ("password", "secret", "api_key", "token", "credential")):
                raise G5ControlActivationError(f"credential-like field prohibited in source manifest: {key}")

        source_id = str(raw_source.get("source_id", "")).strip()
        if not source_id or source_id in seen_ids or source_id in existing_source_ids:
            raise G5ControlActivationError(
                f"control source {index}: source_id must be unique and new"
            )
        seen_ids.add(source_id)

        file_value = str(raw_source.get("path", "")).strip()
        expected_sha = str(raw_source.get("expected_sha256", "")).strip().lower()
        license_reference = str(raw_source.get("license_reference", "")).strip()
        timezone = str(raw_source.get("timezone", "America/New_York")).strip()
        delimiter = str(raw_source.get("delimiter", ","))
        encoding = str(raw_source.get("encoding", "utf-8")).strip() or "utf-8"
        column_map = raw_source.get("column_map")
        if not file_value or len(expected_sha) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha):
            raise G5ControlActivationError(f"control source {source_id}: path/expected_sha256 is invalid")
        if not license_reference:
            raise G5ControlActivationError(f"control source {source_id}: license_reference must be nonblank")
        if not timezone:
            raise G5ControlActivationError(f"control source {source_id}: timezone must be nonblank")
        if not isinstance(column_map, dict):
            raise G5ControlActivationError(f"control source {source_id}: column_map must be an object")

        required_map = {"event_date", "historical_symbol"}
        if not required_map.issubset(column_map):
            raise G5ControlActivationError(
                f"control source {source_id}: column_map must include event_date and historical_symbol"
            )
        if not ({"available_at", "effective_ts_utc"} & set(column_map)):
            raise G5ControlActivationError(
                f"control source {source_id}: column_map must include available_at or effective_ts_utc"
            )
        if not (set(resolver.CONTROL_COVARIATES) & set(column_map)):
            raise G5ControlActivationError(
                f"control source {source_id}: column_map must include at least one control covariate"
            )

        source_path = Path(file_value)
        if not source_path.is_absolute():
            source_path = (path.parent / source_path).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        actual_sha = _sha256(source_path)
        if actual_sha != expected_sha:
            raise G5ControlActivationError(
                f"control source {source_id}: SHA-256 mismatch"
            )

        delim = resolver._delim(delimiter)
        fields, rows = _read_csv(source_path, delimiter=delim, encoding=encoding)
        date_column = str(column_map["event_date"])
        symbol_column = str(column_map["historical_symbol"])
        availability_column = str(
            column_map.get("effective_ts_utc") or column_map.get("available_at")
        )
        declared_covariates = [
            covariate
            for covariate in resolver.CONTROL_COVARIATES
            if covariate in column_map
        ]
        mapped_required = [date_column, symbol_column, availability_column]
        mapped_required.extend(str(column_map[covariate]) for covariate in declared_covariates)
        missing_columns = sorted({name for name in mapped_required if name not in fields})
        if missing_columns:
            raise G5ControlActivationError(
                f"control source {source_id}: data file missing mapped columns {missing_columns}"
            )
        if not rows:
            raise G5ControlActivationError(f"control source {source_id}: data file is empty")

        source_dates: set[str] = set()
        for row_no, row in enumerate(rows, 2):
            event_date = _parse_date(
                row.get(date_column, ""),
                label=f"control source {source_id} row {row_no} event_date",
            )
            if event_date not in required_event_dates:
                raise G5ControlActivationError(
                    f"control source {source_id}: non-required event date {event_date}"
                )
            if event_date in currently_excluded_dates and event_date not in activated_dates:
                raise G5ControlActivationError(
                    f"control source {source_id}: contains evidence for still-excluded date {event_date}"
                )
            symbol = str(row.get(symbol_column, "")).strip().upper()
            if not symbol:
                raise G5ControlActivationError(
                    f"control source {source_id} row {row_no}: historical symbol is blank"
                )
            try:
                available = resolver._parse_aware(
                    row.get(availability_column, ""),
                    field=f"control source {source_id} row {row_no} availability",
                    default_timezone=timezone,
                )
            except ValueError as exc:
                raise G5ControlActivationError(str(exc)) from exc
            if available > event_cutoffs[event_date]:
                raise G5ControlActivationError(
                    f"control source {source_id} row {row_no}: availability is after first event cutoff"
                )
            source_dates.add(event_date)
        observed_dates.update(source_dates)

        contract_sources.append(
            {
                "source_id": source_id,
                "record_kind": "control_universe",
                "source_family": "generic_authorized_reference_data",
                "path": str(source_path),
                "enabled": True,
                "authorized": True,
                "data_classification": "authorized_reference_data",
                "license_reference": license_reference,
                "delimiter": delimiter,
                "encoding": encoding,
                "timezone": timezone,
                "column_map": {str(k): str(v) for k, v in column_map.items()},
                "notes": str(raw_source.get("notes", "")).strip(),
            }
        )
        source_audit.append(
            {
                "source_id": source_id,
                "path": str(source_path),
                "sha256": actual_sha,
                "row_count": len(rows),
                "event_dates": sorted(source_dates),
                "license_reference_present": True,
            }
        )

    missing_activation_dates = sorted(activated_dates - observed_dates)
    if missing_activation_dates:
        raise G5ControlActivationError(
            "activated dates are absent from all staged control sources: "
            + ", ".join(missing_activation_dates)
        )
    return contract_sources, source_audit, observed_dates


def build_activation_contract(
    *,
    source_manifest: Path,
    activate_dates: list[str],
    output_contract: Path,
    replacement_exclusions_output: Path,
    base_contract: Path = DEFAULT_BASE_CONTRACT,
    events_path: Path = DEFAULT_EVENTS,
) -> dict[str, Any]:
    event_counts, event_cutoffs = _event_context(events_path)
    required_dates = set(event_counts)
    raw, exclusion_spec, current_receipt_path, current_exclusions = _load_current_exclusions(
        base_contract,
        event_counts=event_counts,
    )

    normalized_dates = [_parse_date(value, label="activate_date") for value in activate_dates]
    if not normalized_dates or len(normalized_dates) != len(set(normalized_dates)):
        raise G5ControlActivationError("activate_dates must be nonempty and unique")
    activated = set(normalized_dates)
    missing = sorted(activated - set(current_exclusions))
    if missing:
        raise G5ControlActivationError(
            "activation dates are not currently reviewed exclusions: " + ", ".join(missing)
        )

    existing_source_ids = {
        str(source.get("source_id", "")).strip()
        for source in raw.get("sources", [])
        if isinstance(source, dict)
    }
    staged_sources, source_audit, _ = _load_source_manifest(
        source_manifest,
        required_event_dates=required_dates,
        event_cutoffs=event_cutoffs,
        currently_excluded_dates=set(current_exclusions),
        activated_dates=activated,
        existing_source_ids=existing_source_ids,
    )

    remaining_rows = [
        current_exclusions[event_date]
        for event_date in sorted(current_exclusions)
        if event_date not in activated
    ]
    replacement = {
        "schema_version": "1",
        "purpose": (
            "Staged reviewed-control exclusion receipt after removing only dates selected "
            "for G5 resolver validation. Removal from this staged receipt is not a readiness "
            "claim; canonical resolver and quality outputs must independently prove activation."
        ),
        "research_use_only": True,
        "base_exclusion_receipt": {
            "path": str(current_receipt_path),
            "sha256": _sha256(current_receipt_path),
            "excluded_date_count": len(current_exclusions),
        },
        "activation_scope": {
            "activated_dates": sorted(activated),
            "activated_date_count": len(activated),
            "remaining_excluded_date_count": len(remaining_rows),
            "required_event_date_count": len(required_dates),
        },
        "exclusions": remaining_rows,
        "completion_rule": (
            "Every date removed from this staged exclusion receipt must resolve through the "
            "canonical metadata resolver with at least three live timestamped candidates and "
            "at least three conflict-free candidates containing every required control covariate "
            "before the first event cutoff. Staging alone changes no canonical readiness."
        ),
    }

    replacement_path = replacement_exclusions_output.expanduser().resolve()
    replacement_path.parent.mkdir(parents=True, exist_ok=True)
    replacement_path.write_text(
        json.dumps(replacement, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    updated_spec = dict(exclusion_spec)
    updated_spec["enabled"] = bool(remaining_rows)
    updated_spec["path"] = str(replacement_path)
    updated_spec["expected_sha256"] = _sha256(replacement_path)
    updated_spec["expected_count"] = len(remaining_rows)
    updated_spec["activation_reason"] = (
        f"Staged G5 activation for {len(activated)} date(s); "
        f"{len(remaining_rows)} reviewed exclusions remain."
    )
    raw["reviewed_control_exclusions"] = updated_spec
    raw["sources"].extend(staged_sources)

    output_path = output_contract.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(raw, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    resolver.load_contract(output_path)

    expected_resolved = len(required_dates) - len(remaining_rows)
    return {
        "schema_version": "1",
        "status": (
            "STAGED_EXACT_G5_ACTIVATION"
            if not remaining_rows
            else "STAGED_PARTIAL_G5_ACTIVATION"
        ),
        "research_use_only": True,
        "base_contract": str(base_contract.expanduser().resolve()),
        "base_contract_sha256": _sha256(base_contract.expanduser().resolve()),
        "source_manifest": str(source_manifest.expanduser().resolve()),
        "source_manifest_sha256": _sha256(source_manifest.expanduser().resolve()),
        "activation_contract": str(output_path),
        "activation_contract_sha256": _sha256(output_path),
        "replacement_exclusion_receipt": str(replacement_path),
        "replacement_exclusion_receipt_sha256": _sha256(replacement_path),
        "activated_dates": sorted(activated),
        "activated_date_count": len(activated),
        "remaining_excluded_date_count": len(remaining_rows),
        "required_event_date_count": len(required_dates),
        "expected_control_dates_resolved_after_validation": expected_resolved,
        "private_sources": source_audit,
        "canonical_outputs_modified": False,
        "control_readiness_promoted": False,
        "model_evaluation_ready_claimed": False,
    }


def validate_resolver_output(
    resolver_dir: Path,
    *,
    required_event_date_count: int,
    remaining_excluded_date_count: int,
) -> dict[str, Any]:
    summary_path = resolver_dir / "metadata_readiness_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    expected_resolved = required_event_date_count - remaining_excluded_date_count
    expected = {
        "event_date_count": required_event_date_count,
        "control_dates_resolved": expected_resolved,
        "control_dates_excluded": remaining_excluded_date_count,
        "control_dates_accounted_for": required_event_date_count,
        "control_dates_partial": 0,
        "control_dates_unresolved": 0,
        "ready_g5_matched_control_universe": True,
        "ready_g5_model_evaluation_controls": remaining_excluded_date_count == 0,
    }
    actual = {key: summary.get(key) for key in expected}
    if actual != expected:
        raise G5ControlActivationError(
            f"G5 resolver activation state mismatch: expected {expected!r}, got {actual!r}"
        )
    return actual


def validate_quality_output(
    quality_dir: Path,
    *,
    remaining_excluded_date_count: int,
) -> dict[str, Any]:
    summary_path = quality_dir / "metadata_quality_summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(summary_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    domains = {
        str(row.get("domain", "")): row
        for row in summary.get("domain_quality", [])
        if isinstance(row, dict)
    }
    control = domains.get("control_universe")
    if not control:
        raise G5ControlActivationError("metadata quality summary missing control_universe domain")
    expected_status = (
        "QUALITY_CLEAR"
        if remaining_excluded_date_count == 0
        else "READY_WITH_REVIEWED_EXCLUSIONS"
    )
    actual = {
        "quarantined_control_dates": summary.get("quarantined_control_dates"),
        "control_domain_status": control.get("status"),
        "reviewed_control_exclusion_count": summary.get("reviewed_control_exclusion_count"),
    }
    expected = {
        "quarantined_control_dates": 0,
        "control_domain_status": expected_status,
        "reviewed_control_exclusion_count": remaining_excluded_date_count,
    }
    if actual != expected:
        raise G5ControlActivationError(
            f"G5 quality activation state mismatch: expected {expected!r}, got {actual!r}"
        )
    return actual


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage a hash-bound G5 control activation contract. Dates are removed from "
            "reviewed exclusions only in the staged contract and are not considered active "
            "until canonical resolver and quality outputs independently pass."
        )
    )
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--activate-date", action="append", required=True)
    parser.add_argument("--base-contract", type=Path, default=DEFAULT_BASE_CONTRACT)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--output-contract", type=Path, required=True)
    parser.add_argument("--replacement-exclusions-output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path)
    parser.add_argument("--verify-resolver-dir", type=Path)
    parser.add_argument("--verify-quality-dir", type=Path)
    args = parser.parse_args()

    result = build_activation_contract(
        source_manifest=args.source_manifest,
        activate_dates=args.activate_date,
        output_contract=args.output_contract,
        replacement_exclusions_output=args.replacement_exclusions_output,
        base_contract=args.base_contract,
        events_path=args.events,
    )
    if args.verify_resolver_dir is not None:
        result["resolver_validation"] = validate_resolver_output(
            args.verify_resolver_dir,
            required_event_date_count=result["required_event_date_count"],
            remaining_excluded_date_count=result["remaining_excluded_date_count"],
        )
    if args.verify_quality_dir is not None:
        result["quality_validation"] = validate_quality_output(
            args.verify_quality_dir,
            remaining_excluded_date_count=result["remaining_excluded_date_count"],
        )
    if "resolver_validation" in result and "quality_validation" in result:
        result["status"] = (
            "VALIDATED_EXACT_G5_72_OF_72"
            if result["remaining_excluded_date_count"] == 0
            else "VALIDATED_PARTIAL_G5_ACTIVATION"
        )

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.receipt_output:
        receipt_path = args.receipt_output.expanduser().resolve()
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
