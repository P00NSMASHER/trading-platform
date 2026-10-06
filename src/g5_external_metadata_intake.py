from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import g5_external_metadata_adapter as external_adapter

SCHEMA_VERSION = "1"
MANIFEST_SCHEMA_VERSION = "1"
SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

EXTERNAL_FIELDS = tuple(
    dict.fromkeys(
        field
        for lane_fields in external_adapter.LANE_FIELDS.values()
        for field in lane_fields
    )
)

COMBINED_FIELDS = (
    "target_kind",
    "event_id",
    "event_date",
    "symbol",
    "effective_ts_utc",
    *EXTERNAL_FIELDS,
    "source_name",
    "authorization_reference",
    "source_id",
    "research_use_only",
)


class G5ExternalMetadataIntakeError(ValueError):
    pass


@dataclass(frozen=True)
class ExternalMetadataGap:
    target_kind: str
    event_id: str
    event_date: str
    symbol: str
    complete_field_count: int
    required_field_count: int
    missing_fields: str
    conflicted_fields: str
    source_names: str
    latest_effective_ts_utc: str
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


def _parse_aware(value: str, *, label: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise G5ExternalMetadataIntakeError(f"{label} is blank")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G5ExternalMetadataIntakeError(
            f"{label} is not a valid ISO timestamp"
        ) from exc
    if dt.tzinfo is None:
        raise G5ExternalMetadataIntakeError(
            f"{label} must include a timezone"
        )
    return dt.astimezone(timezone.utc)


def _fmt_ts(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _load_targets(
    path: Path,
    *,
    target_kind: str,
) -> tuple[
    dict[tuple[str, str], dict[str, str]],
    dict[tuple[str, str], datetime],
]:
    fields, rows = _read_csv(path)
    required = {
        "event_date",
        "candidate_symbol",
        "latest_acceptable_effective_ts_utc",
    }
    missing = required.difference(fields)
    if missing:
        raise G5ExternalMetadataIntakeError(
            f"{target_kind} target file missing columns: {sorted(missing)}"
        )
    if target_kind == "treated" and "event_id" not in fields:
        raise G5ExternalMetadataIntakeError(
            "treated target file must include event_id"
        )
    if not rows:
        raise G5ExternalMetadataIntakeError(
            f"{target_kind} target file is empty"
        )

    targets: dict[tuple[str, str], dict[str, str]] = {}
    cutoffs: dict[tuple[str, str], datetime] = {}
    for row_no, row in enumerate(rows, 2):
        event_date = row["event_date"][:10]
        symbol = row["candidate_symbol"].upper()
        event_id = row.get("event_id", "").strip()
        if not event_date or not symbol:
            raise G5ExternalMetadataIntakeError(
                f"{target_kind} target row {row_no}: event_date/symbol required"
            )
        if target_kind == "treated" and not event_id:
            raise G5ExternalMetadataIntakeError(
                f"treated target row {row_no}: event_id required"
            )
        if row.get("research_use_only", "1") not in {"", "1"}:
            raise G5ExternalMetadataIntakeError(
                f"{target_kind} target row {row_no}: research_use_only must equal 1"
            )
        key = (event_date, symbol)
        if key in targets:
            raise G5ExternalMetadataIntakeError(
                f"duplicate {target_kind} target: {event_date}|{symbol}"
            )
        cutoff = _parse_aware(
            row["latest_acceptable_effective_ts_utc"],
            label=f"{target_kind} target row {row_no} cutoff",
        )
        targets[key] = {
            "target_kind": target_kind,
            "event_id": event_id,
            "event_date": event_date,
            "symbol": symbol,
        }
        cutoffs[key] = cutoff
    return targets, cutoffs


def _resolve_source_path(manifest_path: Path, raw: str) -> Path:
    value = Path(str(raw or "").strip())
    if not str(value):
        raise G5ExternalMetadataIntakeError("source path is blank")
    if not value.is_absolute():
        value = manifest_path.parent / value
    value = value.resolve()
    if not value.is_file():
        raise G5ExternalMetadataIntakeError(
            f"source file does not exist: {value}"
        )
    return value


def _load_manifest(
    manifest_path: Path,
) -> list[dict[str, str | Path]]:
    path = manifest_path.expanduser().resolve()
    if not path.is_file():
        raise G5ExternalMetadataIntakeError(
            f"source manifest does not exist: {path}"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise G5ExternalMetadataIntakeError(
            "source manifest is not valid JSON"
        ) from exc
    if not isinstance(raw, dict):
        raise G5ExternalMetadataIntakeError(
            "source manifest must be a JSON object"
        )
    if str(raw.get("schema_version") or "") != MANIFEST_SCHEMA_VERSION:
        raise G5ExternalMetadataIntakeError(
            f"source manifest schema_version must equal {MANIFEST_SCHEMA_VERSION}"
        )
    items = raw.get("sources")
    if not isinstance(items, list) or not items:
        raise G5ExternalMetadataIntakeError(
            "source manifest sources must be a non-empty list"
        )

    seen_ids: set[str] = set()
    out: list[dict[str, str | Path]] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise G5ExternalMetadataIntakeError(
                f"source manifest item {index} must be an object"
            )
        source_id = str(item.get("source_id") or "").strip()
        if not source_id or not SOURCE_ID_RE.fullmatch(source_id):
            raise G5ExternalMetadataIntakeError(
                f"source manifest item {index}: invalid source_id"
            )
        if source_id in seen_ids:
            raise G5ExternalMetadataIntakeError(
                f"duplicate source_id: {source_id}"
            )
        seen_ids.add(source_id)

        target_kind = str(item.get("target_kind") or "").strip().lower()
        if target_kind not in {"control", "treated"}:
            raise G5ExternalMetadataIntakeError(
                f"source {source_id}: target_kind must be control or treated"
            )
        lane = str(item.get("lane") or "").strip().lower()
        if lane not in external_adapter.LANE_FIELDS:
            raise G5ExternalMetadataIntakeError(
                f"source {source_id}: unsupported lane {lane!r}"
            )
        expected_sha256 = str(
            item.get("expected_sha256") or ""
        ).strip().lower()
        if len(expected_sha256) != 64 or any(
            char not in "0123456789abcdef"
            for char in expected_sha256
        ):
            raise G5ExternalMetadataIntakeError(
                f"source {source_id}: expected_sha256 must be 64 hex characters"
            )
        authorization_reference = str(
            item.get("authorization_reference") or ""
        ).strip()
        source_name = str(item.get("source_name") or "").strip()
        if not authorization_reference or not source_name:
            raise G5ExternalMetadataIntakeError(
                f"source {source_id}: authorization_reference and source_name are required"
            )

        out.append(
            {
                "source_id": source_id,
                "target_kind": target_kind,
                "lane": lane,
                "path": _resolve_source_path(
                    path, str(item.get("path") or "")
                ),
                "expected_sha256": expected_sha256,
                "authorization_reference": authorization_reference,
                "source_name": source_name,
            }
        )
    return out


def build(
    *,
    control_targets_path: Path,
    treated_targets_path: Path,
    source_manifest_path: Path,
    output_dir: Path,
) -> dict:
    control_targets, _control_cutoffs = _load_targets(
        control_targets_path,
        target_kind="control",
    )
    treated_targets, _treated_cutoffs = _load_targets(
        treated_targets_path,
        target_kind="treated",
    )
    targets = {
        "control": control_targets,
        "treated": treated_targets,
    }
    source_specs = _load_manifest(source_manifest_path)

    output_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir = output_dir / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)

    state: dict[
        tuple[str, str, str],
        dict[str, object],
    ] = {}
    target_meta: dict[
        tuple[str, str, str],
        dict[str, str],
    ] = {}
    for target_kind, by_pair in targets.items():
        for pair, target in by_pair.items():
            key = (target_kind, pair[0], pair[1])
            state[key] = {
                "latest": {},
                "conflicts": set(),
                "sources": set(),
                "latest_ts": None,
            }
            target_meta[key] = target

    combined_rows: list[dict[str, str]] = []
    source_receipts: list[dict[str, object]] = []
    source_counts_by_lane: dict[str, int] = defaultdict(int)
    source_counts_by_kind: dict[str, int] = defaultdict(int)

    for spec in source_specs:
        source_id = str(spec["source_id"])
        target_kind = str(spec["target_kind"])
        lane = str(spec["lane"])
        source_path = Path(spec["path"])
        target_path = (
            control_targets_path
            if target_kind == "control"
            else treated_targets_path
        )

        normalized, summary = external_adapter.normalize(
            lane=lane,
            candidate_path=target_path,
            source_path=source_path,
            expected_source_sha256=str(spec["expected_sha256"]),
            authorization_reference=str(
                spec["authorization_reference"]
            ),
            source_name=str(spec["source_name"]),
        )

        normalized_path = normalized_dir / f"{source_id}.csv"
        normalized_summary_path = (
            normalized_dir / f"{source_id}.summary.json"
        )
        external_adapter.write_outputs(
            normalized,
            summary,
            output_path=normalized_path,
            summary_path=normalized_summary_path,
        )

        source_counts_by_lane[lane] += 1
        source_counts_by_kind[target_kind] += 1
        source_receipts.append(
            {
                "source_id": source_id,
                "target_kind": target_kind,
                "lane": lane,
                "source_path": str(source_path),
                "source_sha256": _sha256(source_path),
                "normalized_path": str(normalized_path),
                "normalized_sha256": _sha256(normalized_path),
                "normalized_row_count": len(normalized),
                "covered_candidate_symbol_dates": int(
                    summary["covered_candidate_symbol_dates"]
                ),
            }
        )

        for row in normalized:
            event_date = row["event_date"][:10]
            symbol = row["symbol"].upper()
            pair = (event_date, symbol)
            target = targets[target_kind].get(pair)
            if target is None:
                raise G5ExternalMetadataIntakeError(
                    f"normalized source {source_id} contains unknown target "
                    f"{target_kind}:{event_date}|{symbol}"
                )
            key = (target_kind, event_date, symbol)
            bucket = state[key]
            effective = _parse_aware(
                row["effective_ts_utc"],
                label=f"normalized source {source_id} effective_ts_utc",
            )
            bucket["sources"].add(row["source_name"])
            prior_latest_ts = bucket["latest_ts"]
            if prior_latest_ts is None or effective > prior_latest_ts:
                bucket["latest_ts"] = effective

            latest = bucket["latest"]
            conflicts = bucket["conflicts"]
            for field in EXTERNAL_FIELDS:
                value = row.get(field, "").strip()
                if not value:
                    continue
                previous = latest.get(field)
                if previous is None or effective > previous["ts"]:
                    latest[field] = {
                        "ts": effective,
                        "value": value,
                        "source": row["source_name"],
                    }
                    conflicts.discard(field)
                elif (
                    effective == previous["ts"]
                    and value != previous["value"]
                ):
                    conflicts.add(field)

            combined = {
                field: ""
                for field in COMBINED_FIELDS
            }
            combined.update(row)
            combined["target_kind"] = target_kind
            combined["event_id"] = target["event_id"]
            combined["source_id"] = source_id
            combined["research_use_only"] = "1"
            combined_rows.append(combined)

    gaps: list[ExternalMetadataGap] = []
    complete_by_kind: dict[str, int] = defaultdict(int)
    missing_field_counts: dict[str, int] = defaultdict(int)
    conflict_field_counts: dict[str, int] = defaultdict(int)
    observed_target_field_count = 0

    for key, bucket in sorted(state.items()):
        target = target_meta[key]
        latest = bucket["latest"]
        conflicts = set(bucket["conflicts"])
        present = {
            field
            for field in EXTERNAL_FIELDS
            if field in latest and field not in conflicts
        }
        observed_target_field_count += len(present)
        missing = sorted(set(EXTERNAL_FIELDS) - present)
        for field in missing:
            missing_field_counts[field] += 1
        for field in conflicts:
            conflict_field_counts[field] += 1

        if not missing and not conflicts:
            complete_by_kind[target["target_kind"]] += 1
            continue

        gaps.append(
            ExternalMetadataGap(
                target_kind=target["target_kind"],
                event_id=target["event_id"],
                event_date=target["event_date"],
                symbol=target["symbol"],
                complete_field_count=len(present),
                required_field_count=len(EXTERNAL_FIELDS),
                missing_fields=";".join(missing),
                conflicted_fields=";".join(sorted(conflicts)),
                source_names=";".join(
                    sorted(bucket["sources"])
                ),
                latest_effective_ts_utc=_fmt_ts(
                    bucket["latest_ts"]
                ),
            )
        )

    combined_rows.sort(
        key=lambda row: (
            row["target_kind"],
            row["event_date"],
            row["symbol"],
            row["effective_ts_utc"],
            row["source_id"],
        )
    )

    combined_path = output_dir / "g5_external_metadata_normalized.csv"
    gap_path = output_dir / "g5_external_metadata_gaps.csv"
    summary_path = output_dir / "g5_external_metadata_intake_summary.json"

    with combined_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(COMBINED_FIELDS),
        )
        writer.writeheader()
        writer.writerows(combined_rows)

    with gap_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(
                ExternalMetadataGap.__dataclass_fields__
            ),
        )
        writer.writeheader()
        for row in gaps:
            writer.writerow(asdict(row))

    control_count = len(control_targets)
    treated_count = len(treated_targets)
    total_count = control_count + treated_count
    required_field_count = total_count * len(EXTERNAL_FIELDS)
    complete_control_count = complete_by_kind["control"]
    complete_treated_count = complete_by_kind["treated"]

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "One deterministic intake path for authorized/public point-in-time "
            "G5 external metadata across control and treated targets. Each source "
            "is hash-bound and normalized through the canonical lane adapter; "
            "latest pre-cutoff values are fused only for completeness reporting."
        ),
        "research_use_only": True,
        "control_target_count": control_count,
        "treated_target_count": treated_count,
        "total_target_count": total_count,
        "external_fields": list(EXTERNAL_FIELDS),
        "external_field_count_per_target": len(EXTERNAL_FIELDS),
        "external_field_requirement_count": required_field_count,
        "observed_nonconflicted_target_field_count": (
            observed_target_field_count
        ),
        "missing_target_field_count": (
            required_field_count - observed_target_field_count
        ),
        "normalized_source_count": len(source_specs),
        "normalized_row_count": len(combined_rows),
        "source_counts_by_lane": dict(
            sorted(source_counts_by_lane.items())
        ),
        "source_counts_by_target_kind": dict(
            sorted(source_counts_by_kind.items())
        ),
        "externally_complete_control_target_count": (
            complete_control_count
        ),
        "externally_complete_treated_target_count": (
            complete_treated_count
        ),
        "externally_complete_target_count": (
            complete_control_count + complete_treated_count
        ),
        "external_gap_target_count": len(gaps),
        "missing_field_counts": dict(
            sorted(missing_field_counts.items())
        ),
        "conflict_field_counts": dict(
            sorted(conflict_field_counts.items())
        ),
        "all_external_metadata_complete": (
            complete_control_count == control_count
            and complete_treated_count == treated_count
            and not gaps
        ),
        "inputs": {
            "control_targets": {
                "path": str(control_targets_path),
                "sha256": _sha256(control_targets_path),
            },
            "treated_targets": {
                "path": str(treated_targets_path),
                "sha256": _sha256(treated_targets_path),
            },
            "source_manifest": {
                "path": str(source_manifest_path),
                "sha256": _sha256(source_manifest_path),
            },
            "sources": source_receipts,
        },
        "outputs": {
            "combined_normalized_external_metadata": str(
                combined_path
            ),
            "external_metadata_gaps": str(gap_path),
            "normalized_source_directory": str(normalized_dir),
        },
        "policy": {
            "source_hash_and_authorization_are_required": True,
            "canonical_lane_normalization_is_reused": True,
            "target_cutoffs_are_enforced_by_lane_adapter": True,
            "unknown_targets_fail_closed": True,
            "equal_timestamp_field_conflicts_fail_target_closed": True,
            "partial_external_metadata_may_be_reported": True,
            "intake_changes_canonical_g5_readiness": False,
        },
        "canonical_g5_readiness_changed": False,
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }

    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize and fuse point-in-time G5 external metadata sources "
            "for control and treated targets."
        )
    )
    parser.add_argument(
        "--control-targets",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--treated-targets",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    args = parser.parse_args()

    result = build(
        control_targets_path=args.control_targets,
        treated_targets_path=args.treated_targets,
        source_manifest_path=args.source_manifest,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
