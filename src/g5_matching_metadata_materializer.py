from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from metadata_resolver import CONTROL_COVARIATES

SCHEMA_VERSION = "1"


class G5MatchingMetadataMaterializationError(ValueError):
    pass


@dataclass(frozen=True)
class MaterializedMetadataRow:
    event_date: str
    symbol: str
    effective_ts_utc: str
    sector: str
    index_bucket: str
    market_cap: str
    price: str
    trailing_21d_vol: str
    normal_minute_volume: str
    normal_minute_turnover: str
    normal_relative_spread: str
    option_liquidity: str
    institutional_ownership: str
    analyst_coverage: str
    borrow_cost: str
    pre_event_return: str
    source_name: str
    target_kind: str
    event_id: str
    research_use_only: int = 1


@dataclass(frozen=True)
class MetadataGapRow:
    target_kind: str
    event_id: str
    event_date: str
    symbol: str
    missing_fields: str
    conflicted_fields: str
    source_names: str
    latest_effective_ts_utc: str
    research_use_only: int = 1


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


def _parse_ts(value: str, *, label: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise G5MatchingMetadataMaterializationError(f"{label} is blank")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G5MatchingMetadataMaterializationError(
            f"{label} is not a valid ISO timestamp"
        ) from exc
    if dt.tzinfo is None:
        raise G5MatchingMetadataMaterializationError(
            f"{label} must include a timezone"
        )
    return dt.astimezone(timezone.utc)


def _fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _load_targets(path: Path, *, target_kind: str) -> list[dict[str, object]]:
    fields, rows = _read_csv(path)
    required = {
        "event_date",
        "candidate_symbol",
        "latest_acceptable_effective_ts_utc",
    }
    missing = required.difference(fields)
    if missing:
        raise G5MatchingMetadataMaterializationError(
            f"{target_kind} target file missing columns: {sorted(missing)}"
        )
    if target_kind == "treated" and "event_id" not in fields:
        raise G5MatchingMetadataMaterializationError(
            "treated target file must include event_id"
        )
    if not rows:
        raise G5MatchingMetadataMaterializationError(
            f"{target_kind} target file is empty"
        )

    out: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row_no, row in enumerate(rows, 2):
        event_date = row["event_date"][:10]
        symbol = row["candidate_symbol"].upper()
        event_id = row.get("event_id", "").strip()
        if not event_date or not symbol:
            raise G5MatchingMetadataMaterializationError(
                f"{target_kind} target row {row_no}: event_date/symbol required"
            )
        if target_kind == "treated" and not event_id:
            raise G5MatchingMetadataMaterializationError(
                f"treated target row {row_no}: event_id required"
            )
        key = (event_date, symbol)
        if key in seen:
            raise G5MatchingMetadataMaterializationError(
                f"duplicate {target_kind} target: {event_date}|{symbol}"
            )
        seen.add(key)
        out.append(
            {
                "target_kind": target_kind,
                "event_id": event_id,
                "event_date": event_date,
                "symbol": symbol,
                "cutoff": _parse_ts(
                    row["latest_acceptable_effective_ts_utc"],
                    label=f"{target_kind} target row {row_no} cutoff",
                ),
            }
        )
    return out


def build(
    *,
    control_targets_path: Path,
    treated_targets_path: Path,
    source_paths: list[Path],
    output_path: Path,
    gap_path: Path,
    summary_path: Path,
    minimum_controls_per_date: int = 3,
) -> dict:
    if minimum_controls_per_date < 1:
        raise G5MatchingMetadataMaterializationError(
            "minimum_controls_per_date must be positive"
        )
    if not source_paths:
        raise G5MatchingMetadataMaterializationError(
            "at least one normalized metadata source is required"
        )

    controls = _load_targets(control_targets_path, target_kind="control")
    treated = _load_targets(treated_targets_path, target_kind="treated")
    targets = [*controls, *treated]

    by_pair: dict[tuple[str, str], dict[str, object]] = {}
    state: dict[tuple[str, str], dict[str, object]] = {}
    for target in targets:
        pair = (str(target["event_date"]), str(target["symbol"]))
        if pair in by_pair:
            prior = by_pair[pair]
            raise G5MatchingMetadataMaterializationError(
                "treated/control target collision for "
                f"{pair[0]}|{pair[1]}: {prior['target_kind']} and {target['target_kind']}"
            )
        by_pair[pair] = target
        state[pair] = {
            "latest": {},
            "conflicts": set(),
            "sources": set(),
            "latest_ts": None,
        }

    source_receipts = []
    for source_path in source_paths:
        fields, rows = _read_csv(source_path)
        required = {"event_date", "symbol", "effective_ts_utc", "source_name"}
        missing = required.difference(fields)
        if missing:
            raise G5MatchingMetadataMaterializationError(
                f"source {source_path} missing columns: {sorted(missing)}"
            )
        source_receipts.append(
            {
                "path": str(source_path),
                "sha256": _sha256(source_path),
                "row_count": len(rows),
            }
        )

        for row_no, row in enumerate(rows, 2):
            event_date = row["event_date"][:10]
            symbol = row["symbol"].upper()
            pair = (event_date, symbol)
            target = by_pair.get(pair)
            if target is None:
                raise G5MatchingMetadataMaterializationError(
                    f"source {source_path} row {row_no}: unknown target {event_date}|{symbol}"
                )
            if "research_use_only" in fields and row.get("research_use_only", "") != "1":
                raise G5MatchingMetadataMaterializationError(
                    f"source {source_path} row {row_no}: research_use_only must equal 1"
                )
            source_name = row["source_name"].strip()
            if not source_name:
                raise G5MatchingMetadataMaterializationError(
                    f"source {source_path} row {row_no}: source_name is blank"
                )
            effective = _parse_ts(
                row["effective_ts_utc"],
                label=f"source {source_path} row {row_no} effective_ts_utc",
            )
            cutoff = target["cutoff"]
            assert isinstance(cutoff, datetime)
            if effective > cutoff:
                raise G5MatchingMetadataMaterializationError(
                    f"source {source_path} row {row_no}: timestamp exceeds target cutoff"
                )

            bucket = state[pair]
            sources = bucket["sources"]
            assert isinstance(sources, set)
            sources.add(source_name)
            latest_ts = bucket["latest_ts"]
            if latest_ts is None or effective > latest_ts:
                bucket["latest_ts"] = effective

            populated = 0
            latest = bucket["latest"]
            conflicts = bucket["conflicts"]
            assert isinstance(latest, dict)
            assert isinstance(conflicts, set)
            for field in CONTROL_COVARIATES:
                value = row.get(field, "").strip()
                if not value:
                    continue
                populated += 1
                previous = latest.get(field)
                if previous is None or effective > previous["ts"]:
                    latest[field] = {
                        "ts": effective,
                        "value": value,
                        "source": source_name,
                    }
                    conflicts.discard(field)
                elif effective == previous["ts"] and value != previous["value"]:
                    conflicts.add(field)
            if populated == 0:
                raise G5MatchingMetadataMaterializationError(
                    f"source {source_path} row {row_no}: no G5 matching covariates populated"
                )

    materialized: list[MaterializedMetadataRow] = []
    gaps: list[MetadataGapRow] = []
    complete_controls_by_date: dict[str, int] = defaultdict(int)
    missing_counts: dict[str, int] = defaultdict(int)
    conflict_counts: dict[str, int] = defaultdict(int)
    complete_by_kind: dict[str, int] = defaultdict(int)

    for pair, target in sorted(
        by_pair.items(), key=lambda item: (item[0][0], item[0][1], str(item[1]["target_kind"]))
    ):
        bucket = state[pair]
        latest = bucket["latest"]
        conflicts = set(bucket["conflicts"])
        sources = set(bucket["sources"])
        assert isinstance(latest, dict)

        present = {
            field
            for field in CONTROL_COVARIATES
            if field in latest and field not in conflicts
        }
        missing = sorted(set(CONTROL_COVARIATES) - present)
        for field in missing:
            missing_counts[field] += 1
        for field in conflicts:
            conflict_counts[field] += 1

        if missing or conflicts:
            gaps.append(
                MetadataGapRow(
                    target_kind=str(target["target_kind"]),
                    event_id=str(target["event_id"]),
                    event_date=pair[0],
                    symbol=pair[1],
                    missing_fields=";".join(missing),
                    conflicted_fields=";".join(sorted(conflicts)),
                    source_names=";".join(sorted(sources)),
                    latest_effective_ts_utc=_fmt_ts(bucket["latest_ts"]),
                )
            )
            continue

        selected_ts = max(latest[field]["ts"] for field in CONTROL_COVARIATES)
        selected_sources = {
            str(latest[field]["source"])
            for field in CONTROL_COVARIATES
        }
        values = {field: str(latest[field]["value"]) for field in CONTROL_COVARIATES}
        materialized.append(
            MaterializedMetadataRow(
                event_date=pair[0],
                symbol=pair[1],
                effective_ts_utc=_fmt_ts(selected_ts),
                source_name=";".join(sorted(selected_sources)),
                target_kind=str(target["target_kind"]),
                event_id=str(target["event_id"]),
                **values,
            )
        )
        kind = str(target["target_kind"])
        complete_by_kind[kind] += 1
        if kind == "control":
            complete_controls_by_date[pair[0]] += 1

    control_dates = sorted({str(target["event_date"]) for target in controls})
    ready_control_dates = [
        value
        for value in control_dates
        if complete_controls_by_date[value] >= minimum_controls_per_date
    ]
    treated_complete = complete_by_kind["treated"] == len(treated)
    matcher_input_ready = (
        treated_complete
        and len(ready_control_dates) == len(control_dates)
        and not gaps
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    gap_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(MaterializedMetadataRow.__dataclass_fields__)
        )
        writer.writeheader()
        for row in materialized:
            writer.writerow(asdict(row))
    with gap_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(MetadataGapRow.__dataclass_fields__)
        )
        writer.writeheader()
        for row in gaps:
            writer.writerow(asdict(row))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Fail-closed materialization of the exact point-in-time metadata rows consumed "
            "by matched_control_generator. Latest admissible covariates may be fused across "
            "normalized G5 sources, but incomplete or conflicted targets are excluded."
        ),
        "research_use_only": True,
        "required_covariates": list(CONTROL_COVARIATES),
        "required_covariate_count": len(CONTROL_COVARIATES),
        "control_target_count": len(controls),
        "treated_target_count": len(treated),
        "total_target_count": len(targets),
        "materialized_control_count": complete_by_kind["control"],
        "materialized_treated_count": complete_by_kind["treated"],
        "materialized_target_count": len(materialized),
        "gap_target_count": len(gaps),
        "minimum_controls_per_date": minimum_controls_per_date,
        "control_event_date_count": len(control_dates),
        "control_dates_with_minimum_complete_metadata": len(ready_control_dates),
        "control_ready_event_dates": ready_control_dates,
        "all_treated_metadata_complete": treated_complete,
        "missing_field_counts": dict(sorted(missing_counts.items())),
        "conflict_field_counts": dict(sorted(conflict_counts.items())),
        "matcher_input_ready": matcher_input_ready,
        "inputs": {
            "control_targets": {
                "path": str(control_targets_path),
                "sha256": _sha256(control_targets_path),
            },
            "treated_targets": {
                "path": str(treated_targets_path),
                "sha256": _sha256(treated_targets_path),
            },
            "normalized_sources": source_receipts,
        },
        "outputs": {
            "matcher_metadata": str(output_path),
            "metadata_gaps": str(gap_path),
        },
        "policy": {
            "latest_value_must_not_exceed_target_cutoff": True,
            "equal_timestamp_conflicts_fail_target_closed": True,
            "incomplete_targets_are_omitted_from_matcher_metadata": True,
            "source_rows_may_not_create_unknown_targets": True,
            "materialization_changes_canonical_g5_readiness": False,
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
        description="Materialize complete point-in-time G5 matcher metadata."
    )
    parser.add_argument("--control-targets", type=Path, required=True)
    parser.add_argument("--treated-targets", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gaps", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--minimum-controls-per-date", type=int, default=3)
    args = parser.parse_args()
    result = build(
        control_targets_path=args.control_targets,
        treated_targets_path=args.treated_targets,
        source_paths=args.source,
        output_path=args.output,
        gap_path=args.gaps,
        summary_path=args.summary,
        minimum_controls_per_date=args.minimum_controls_per_date,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
