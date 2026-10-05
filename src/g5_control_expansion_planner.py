from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from g5_control_gap_planner import (
    DEFAULT_MIN_CONTROLS,
    DEFAULT_REQUIRED_MARKET_KINDS,
    PROHIBITED_OUTPUTS,
    _intersection,
    _load_market_requirements,
    _load_positive_symbols,
)

SCHEMA_VERSION = "1"
PLANNING_ONLY_STATUS = "PLANNING_ONLY_NOT_G5_EVIDENCE"
RETROSPECTIVE_LABEL_COLUMNS = {"hacked", "actual", "soft"}


@dataclass(frozen=True)
class ExpansionCandidate:
    event_date: str
    candidate_symbol: str
    selection_rank: int
    structural_deficit_before: int
    existing_g2_candidate_count: int
    planning_source: str
    requires_point_in_time_metadata: int = 1
    eligibility_status: str = PLANNING_ONLY_STATUS
    research_use_only: int = 1


@dataclass(frozen=True)
class ExpansionRequirement:
    event_date: str
    candidate_symbol: str
    record_kind: str
    status: str = "G5_CONTROL_MARKET_ACQUISITION_REQUIRED"
    eligible_g5_evidence: int = 0
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_planning_universe(path: Path) -> tuple[dict[str, set[str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        by_lower = {name.lower(): name for name in fieldnames}
        symbol_col = next(
            (by_lower[name] for name in ("symbol", "historical_symbol") if name in by_lower),
            None,
        )
        date_col = next(
            (by_lower[name] for name in ("date", "event_date", "trade_date") if name in by_lower),
            None,
        )
        if symbol_col is None or date_col is None:
            raise ValueError("planning universe requires symbol and date columns")

        ignored_label_columns = sorted(
            name for name in fieldnames if name.lower() in RETROSPECTIVE_LABEL_COLUMNS
        )
        out: dict[str, set[str]] = {}
        for i, row in enumerate(reader, 2):
            symbol = (row.get(symbol_col) or "").strip().upper()
            event_date = (row.get(date_col) or "").strip()
            if not symbol or not event_date:
                continue
            if len(event_date) < 10 or event_date[4:5] != "-" or event_date[7:8] != "-":
                raise ValueError(f"planning-universe row {i}: invalid date {event_date!r}")
            event_date = event_date[:10]
            out.setdefault(event_date, set()).add(symbol)
    return out, ignored_label_columns


def _write_dataclasses(path: Path, rows: list, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def build(
    *,
    events_path: Path,
    requirements_path: Path,
    planning_universe_path: Path,
    output_dir: Path,
    min_controls: int = DEFAULT_MIN_CONTROLS,
    required_market_kinds: tuple[str, ...] = DEFAULT_REQUIRED_MARKET_KINDS,
) -> dict:
    if min_controls < 1:
        raise ValueError("min_controls must be positive")
    if not required_market_kinds:
        raise ValueError("required_market_kinds must not be empty")

    positives_by_date = _load_positive_symbols(events_path)
    requirements = _load_market_requirements(requirements_path)
    planning_by_date, ignored_label_columns = _load_planning_universe(planning_universe_path)

    candidates: list[ExpansionCandidate] = []
    market_requirements: list[ExpansionRequirement] = []
    deficient_dates = 0
    deficit_slots_before = 0
    residual_slots = 0
    fully_coverable_dates = 0
    date_rows: list[dict] = []

    for event_date in sorted(positives_by_date):
        positives = positives_by_date[event_date]
        by_kind = requirements.get(event_date, {})
        kind_sets = [by_kind.get(kind, set()) for kind in required_market_kinds]
        existing_pool = _intersection(kind_sets)
        existing_pool.difference_update(positives)
        deficit = max(0, min_controls - len(existing_pool))
        if deficit == 0:
            continue

        deficient_dates += 1
        deficit_slots_before += deficit

        available = set(planning_by_date.get(event_date, set()))
        available.difference_update(positives)
        available.difference_update(existing_pool)
        chosen = sorted(available)[:deficit]
        residual = deficit - len(chosen)
        residual_slots += residual
        if residual == 0:
            fully_coverable_dates += 1

        for rank, symbol in enumerate(chosen, 1):
            candidates.append(
                ExpansionCandidate(
                    event_date=event_date,
                    candidate_symbol=symbol,
                    selection_rank=rank,
                    structural_deficit_before=deficit,
                    existing_g2_candidate_count=len(existing_pool),
                    planning_source=planning_universe_path.as_posix(),
                )
            )
            for kind in required_market_kinds:
                market_requirements.append(
                    ExpansionRequirement(
                        event_date=event_date,
                        candidate_symbol=symbol,
                        record_kind=kind,
                    )
                )

        date_rows.append(
            {
                "event_date": event_date,
                "existing_g2_candidate_count": len(existing_pool),
                "structural_deficit_before": deficit,
                "planning_universe_available_count": len(available),
                "selected_candidate_count": len(chosen),
                "residual_unfilled_slots": residual,
                "status": "STRUCTURALLY_FILLABLE_FROM_PLANNING_UNIVERSE" if residual == 0
                else "REQUIRES_ADDITIONAL_UNIVERSE_SYMBOLS",
                "research_use_only": 1,
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "g5_control_expansion_candidates.csv"
    requirement_path = output_dir / "g5_control_market_expansion_requirements.csv"
    date_path = output_dir / "g5_control_expansion_by_date.csv"

    _write_dataclasses(
        candidate_path,
        candidates,
        list(ExpansionCandidate.__dataclass_fields__),
    )
    _write_dataclasses(
        requirement_path,
        market_requirements,
        list(ExpansionRequirement.__dataclass_fields__),
    )
    with date_path.open("w", encoding="utf-8", newline="") as f:
        fields = [
            "event_date",
            "existing_g2_candidate_count",
            "structural_deficit_before",
            "planning_universe_available_count",
            "selected_candidate_count",
            "residual_unfilled_slots",
            "status",
            "research_use_only",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(date_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Deterministic acquisition planning for G5 control-candidate structural gaps. "
            "The retrospective planning universe supplies symbol names only; retrospective "
            "Hacked/Actual/Soft labels are ignored and never used for selection or eligibility."
        ),
        "research_use_only": True,
        "inputs": {
            "events": {"path": str(events_path), "sha256": _sha256(events_path)},
            "market_requirements": {
                "path": str(requirements_path),
                "sha256": _sha256(requirements_path),
            },
            "planning_universe": {
                "path": str(planning_universe_path),
                "sha256": _sha256(planning_universe_path),
                "ignored_retrospective_label_columns": ignored_label_columns,
            },
        },
        "minimum_controls_per_event": min_controls,
        "required_market_kinds": list(required_market_kinds),
        "structurally_deficient_date_count": deficient_dates,
        "structural_deficit_slots_before": deficit_slots_before,
        "selected_candidate_symbol_dates": len(candidates),
        "generated_market_requirement_rows": len(market_requirements),
        "fully_structurally_coverable_deficient_dates": fully_coverable_dates,
        "remaining_deficient_dates_after_planning": deficient_dates - fully_coverable_dates,
        "residual_unfilled_symbol_date_slots": residual_slots,
        "candidate_selection_uses_retrospective_labels": False,
        "point_in_time_metadata_still_required": True,
        "market_data_still_required": True,
        "g5_model_evaluation_controls_ready": False,
        "release_claimed": False,
        "eligibility_policy": {
            "planning_rows_are_not_g5_evidence": True,
            "future_or_retrospective_label_fields_may_not_close_g5": True,
            "each_selected_symbol_still_requires_all_market_record_kinds": True,
            "each_selected_symbol_still_requires_pre_event_point_in_time_metadata": True,
            "final_candidate_contamination_and_match_quality_screening_required": True,
        },
        "outputs": {
            "candidate_queue": str(candidate_path),
            "market_expansion_requirements": str(requirement_path),
            "date_summary": str(date_path),
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    (output_dir / "g5_control_expansion_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    p = argparse.ArgumentParser(
        description="Plan G5 control-candidate expansion without promoting retrospective labels."
    )
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--requirements", type=Path, required=True)
    p.add_argument("--planning-universe", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--min-controls", type=int, default=DEFAULT_MIN_CONTROLS)
    args = p.parse_args()
    result = build(
        events_path=args.events,
        requirements_path=args.requirements,
        planning_universe_path=args.planning_universe,
        output_dir=args.output_dir,
        min_controls=args.min_controls,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
