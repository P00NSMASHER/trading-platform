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


class G5StagedPreviewError(ValueError):
    pass


@dataclass(frozen=True)
class CandidatePreview:
    event_date: str
    candidate_symbol: str
    complete_field_count: int
    required_field_count: int
    candidate_complete: int
    missing_fields: str
    conflicted_fields: str
    source_names: str
    latest_effective_ts_utc: str
    preview_only: int = 1
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
        raise G5StagedPreviewError(f"{label} is blank")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G5StagedPreviewError(f"{label} is not valid ISO timestamp") from exc
    if dt.tzinfo is None:
        raise G5StagedPreviewError(f"{label} must include timezone")
    return dt.astimezone(timezone.utc)


def _fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_candidates(path: Path) -> dict[tuple[str, str], datetime]:
    fields, rows = _read_csv(path)
    required = {"event_date", "candidate_symbol", "latest_acceptable_effective_ts_utc"}
    missing = required.difference(fields)
    if missing:
        raise G5StagedPreviewError(
            f"candidate file missing columns: {sorted(missing)}"
        )
    out: dict[tuple[str, str], datetime] = {}
    for row_no, row in enumerate(rows, 2):
        event_date = row["event_date"][:10]
        symbol = row["candidate_symbol"].upper()
        cutoff = _parse_ts(
            row["latest_acceptable_effective_ts_utc"],
            label=f"candidate row {row_no} cutoff",
        )
        if not event_date or not symbol:
            raise G5StagedPreviewError(
                f"candidate row {row_no}: event_date/candidate_symbol required"
            )
        key = (event_date, symbol)
        if key in out:
            raise G5StagedPreviewError(
                f"duplicate candidate symbol-date: {event_date}|{symbol}"
            )
        out[key] = cutoff
    return out


def build_preview(
    *,
    candidate_path: Path,
    source_paths: list[Path],
    output_path: Path,
    summary_path: Path,
    minimum_controls_per_date: int = 3,
) -> dict:
    if minimum_controls_per_date < 1:
        raise G5StagedPreviewError("minimum_controls_per_date must be positive")
    if not source_paths:
        raise G5StagedPreviewError("at least one staged source is required")

    candidates = load_candidates(candidate_path)
    required_fields = tuple(CONTROL_COVARIATES)
    state: dict[tuple[str, str], dict] = {
        key: {
            "latest": {},
            "conflicts": set(),
            "sources": set(),
            "latest_ts": None,
        }
        for key in candidates
    }

    source_receipts = []
    for source_path in source_paths:
        fields, rows = _read_csv(source_path)
        required_identity = {"event_date", "symbol", "effective_ts_utc"}
        missing = required_identity.difference(fields)
        if missing:
            raise G5StagedPreviewError(
                f"staged source {source_path} missing columns: {sorted(missing)}"
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
            key = (event_date, symbol)
            cutoff = candidates.get(key)
            if cutoff is None:
                raise G5StagedPreviewError(
                    f"staged source {source_path} row {row_no}: unknown candidate {event_date}|{symbol}"
                )
            effective = _parse_ts(
                row["effective_ts_utc"],
                label=f"{source_path} row {row_no} effective_ts_utc",
            )
            if effective > cutoff:
                raise G5StagedPreviewError(
                    f"staged source {source_path} row {row_no}: timestamp exceeds candidate cutoff"
                )
            source_name = row.get("source_name", "").strip() or source_path.name
            bucket = state[key]
            bucket["sources"].add(source_name)
            latest_ts = bucket["latest_ts"]
            if latest_ts is None or effective > latest_ts:
                bucket["latest_ts"] = effective

            for field in required_fields:
                value = row.get(field, "").strip()
                if not value:
                    continue
                previous = bucket["latest"].get(field)
                if previous is None or effective > previous["ts"]:
                    bucket["latest"][field] = {
                        "ts": effective,
                        "value": value,
                        "source": source_name,
                    }
                    bucket["conflicts"].discard(field)
                elif effective == previous["ts"] and value != previous["value"]:
                    bucket["conflicts"].add(field)

    previews: list[CandidatePreview] = []
    ready_by_date: dict[str, int] = defaultdict(int)
    missing_field_counts: dict[str, int] = defaultdict(int)
    conflict_field_counts: dict[str, int] = defaultdict(int)

    for (event_date, symbol), bucket in sorted(state.items()):
        conflicts = sorted(bucket["conflicts"])
        present = {
            field
            for field in required_fields
            if field in bucket["latest"] and field not in bucket["conflicts"]
        }
        missing = sorted(set(required_fields) - present)
        for field in missing:
            missing_field_counts[field] += 1
        for field in conflicts:
            conflict_field_counts[field] += 1
        complete = int(not missing and not conflicts)
        if complete:
            ready_by_date[event_date] += 1

        previews.append(
            CandidatePreview(
                event_date=event_date,
                candidate_symbol=symbol,
                complete_field_count=len(present),
                required_field_count=len(required_fields),
                candidate_complete=complete,
                missing_fields=";".join(missing),
                conflicted_fields=";".join(conflicts),
                source_names=";".join(sorted(bucket["sources"])),
                latest_effective_ts_utc=_fmt_ts(bucket["latest_ts"]),
            )
        )

    dates = sorted({event_date for event_date, _symbol in candidates})
    staged_ready_dates = [
        event_date
        for event_date in dates
        if ready_by_date[event_date] >= minimum_controls_per_date
    ]
    complete_candidates = sum(row.candidate_complete for row in previews)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(CandidatePreview.__dataclass_fields__),
        )
        writer.writeheader()
        for row in previews:
            writer.writerow(asdict(row))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Preview staged G5 control metadata completeness before canonical admission. "
            "This report cannot modify canonical G5 readiness or release gates."
        ),
        "research_use_only": True,
        "minimum_controls_per_date": minimum_controls_per_date,
        "event_date_count": len(dates),
        "candidate_symbol_date_count": len(candidates),
        "complete_candidate_symbol_date_count": complete_candidates,
        "staged_ready_event_date_count": len(staged_ready_dates),
        "staged_ready_event_dates": staged_ready_dates,
        "missing_field_counts": dict(sorted(missing_field_counts.items())),
        "conflict_field_counts": dict(sorted(conflict_field_counts.items())),
        "required_fields": list(required_fields),
        "inputs": {
            "candidates": {
                "path": str(candidate_path),
                "sha256": _sha256(candidate_path),
            },
            "staged_sources": source_receipts,
        },
        "canonical_g5_readiness_changed": False,
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
        "preview_all_dates_complete": len(staged_ready_dates) == len(dates),
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview G5 staged control metadata completeness."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--minimum-controls-per-date", type=int, default=3)
    args = parser.parse_args()
    result = build_preview(
        candidate_path=args.candidates,
        source_paths=args.source,
        output_path=args.output,
        summary_path=args.summary,
        minimum_controls_per_date=args.minimum_controls_per_date,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
