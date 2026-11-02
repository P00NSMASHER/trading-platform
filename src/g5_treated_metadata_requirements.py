from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from g5_control_acquisition_planner import (
    DERIVED_FIELDS,
    EXTERNAL_FIELDS,
    FIELD_ROUTES,
)
from metadata_resolver import CONTROL_COVARIATES

SCHEMA_VERSION = "1"
NY = ZoneInfo("America/New_York")

EXTERNAL_LANES = {
    "classification": ("sector", "index_bucket"),
    "ownership": ("institutional_ownership",),
    "analyst": ("analyst_coverage",),
    "borrow": ("borrow_cost",),
}


@dataclass(frozen=True)
class TreatedFieldRequirement:
    event_id: str
    event_date: str
    treated_symbol: str
    latest_acceptable_effective_ts_utc: str
    field_name: str
    field_class: str
    route: str
    status: str
    eligible_g5_evidence: int = 0
    research_use_only: int = 1


@dataclass(frozen=True)
class TreatedTarget:
    event_id: str
    event_date: str
    candidate_symbol: str
    latest_acceptable_effective_ts_utc: str
    target_kind: str = "treated"
    eligible_g5_evidence: int = 0
    research_use_only: int = 1


@dataclass(frozen=True)
class TreatedExternalLaneRequest:
    request_id: str
    event_id: str
    lane: str
    event_date: str
    treated_symbol: str
    latest_acceptable_effective_ts_utc: str
    required_fields: str
    status: str = "SOURCE_REQUIRED"
    eligible_g5_evidence: int = 0
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_event_ts(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("blank first_documented_illicit_trade_ts")
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(timezone.utc)


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _request_id(event_id: str, lane: str) -> str:
    raw = f"{event_id}|{lane}".encode("utf-8")
    return "G5TRT-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def load_events(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        required = {
            "event_id",
            "historical_symbol",
            "first_documented_illicit_trade_ts",
        }
        missing = required.difference(fields)
        if missing:
            raise ValueError(f"events file missing columns: {sorted(missing)}")
        rows = [
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    if not rows:
        raise ValueError("events file is empty")
    seen = set()
    for row_no, row in enumerate(rows, 2):
        event_id = row["event_id"]
        symbol = row["historical_symbol"].upper()
        if not event_id or not symbol:
            raise ValueError(f"event row {row_no}: event_id/historical_symbol required")
        if event_id in seen:
            raise ValueError(f"duplicate event_id: {event_id}")
        seen.add(event_id)
        _parse_event_ts(row["first_documented_illicit_trade_ts"])
    return rows


def build(*, events_path: Path, output_dir: Path) -> dict:
    events = load_events(events_path)
    requirements: list[TreatedFieldRequirement] = []
    targets: list[TreatedTarget] = []
    lane_requests: list[TreatedExternalLaneRequest] = []

    for event in events:
        event_id = event["event_id"]
        symbol = event["historical_symbol"].upper()
        raw_ts = event["first_documented_illicit_trade_ts"]
        cutoff = _parse_event_ts(raw_ts)
        event_date = cutoff.astimezone(NY).date().isoformat()
        cutoff_key = _fmt_utc(cutoff)

        targets.append(
            TreatedTarget(
                event_id=event_id,
                event_date=event_date,
                candidate_symbol=symbol,
                latest_acceptable_effective_ts_utc=cutoff_key,
            )
        )

        for field_name in CONTROL_COVARIATES:
            external = field_name in EXTERNAL_FIELDS
            requirements.append(
                TreatedFieldRequirement(
                    event_id=event_id,
                    event_date=event_date,
                    treated_symbol=symbol,
                    latest_acceptable_effective_ts_utc=cutoff_key,
                    field_name=field_name,
                    field_class="external" if external else "derived",
                    route=FIELD_ROUTES[field_name],
                    status=(
                        "EXTERNAL_POINT_IN_TIME_SOURCE_REQUIRED"
                        if external
                        else "DERIVE_AFTER_REAL_G2_G4"
                    ),
                )
            )

        for lane, lane_fields in EXTERNAL_LANES.items():
            lane_requests.append(
                TreatedExternalLaneRequest(
                    request_id=_request_id(event_id, lane),
                    event_id=event_id,
                    lane=lane,
                    event_date=event_date,
                    treated_symbol=symbol,
                    latest_acceptable_effective_ts_utc=cutoff_key,
                    required_fields=";".join(lane_fields),
                )
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / "g5_treated_targets.csv"
    field_path = output_dir / "g5_treated_field_requirements.csv"
    lane_path = output_dir / "g5_treated_external_lane_requests.csv"

    with target_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(TreatedTarget.__dataclass_fields__),
        )
        writer.writeheader()
        for row in targets:
            writer.writerow(asdict(row))

    with field_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(TreatedFieldRequirement.__dataclass_fields__),
        )
        writer.writeheader()
        for row in requirements:
            writer.writerow(asdict(row))

    with lane_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(TreatedExternalLaneRequest.__dataclass_fields__),
        )
        writer.writeheader()
        for row in lane_requests:
            writer.writerow(asdict(row))

    event_dates = {row.event_date for row in requirements}
    external_rows = sum(row.field_class == "external" for row in requirements)
    derived_rows = len(requirements) - external_rows

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Explicitly plan the treated-event metadata required by the matched-control "
            "generator. Candidate controls alone cannot make G5 genuinely match-ready."
        ),
        "research_use_only": True,
        "event_count": len(events),
        "event_date_count": len(event_dates),
        "treated_target_count": len(targets),
        "treated_field_requirement_count": len(requirements),
        "treated_derived_field_requirement_count": derived_rows,
        "treated_external_field_requirement_count": external_rows,
        "treated_external_lane_request_count": len(lane_requests),
        "required_field_count_per_event": len(CONTROL_COVARIATES),
        "external_field_count_per_event": len(EXTERNAL_FIELDS),
        "derived_field_count_per_event": len(DERIVED_FIELDS),
        "external_lanes": {
            lane: list(fields)
            for lane, fields in EXTERNAL_LANES.items()
        },
        "inputs": {
            "events_path": str(events_path),
            "events_sha256": _sha256(events_path),
        },
        "outputs": {
            "treated_targets": str(target_path),
            "treated_field_requirements": str(field_path),
            "treated_external_lane_requests": str(lane_path),
        },
        "policy": {
            "treated_metadata_is_required_for_actual_matching": True,
            "treated_targets_use_candidate_symbol_alias_for_shared_intake_adapters": True,
            "requirement_rows_are_g5_evidence": False,
            "all_values_must_be_effective_no_later_than_event_cutoff": True,
            "future_or_post_event_values_may_not_close_g5": True,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_treated_metadata_requirement_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build treated-event metadata requirements for G5 matching."
    )
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        events_path=args.events,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
