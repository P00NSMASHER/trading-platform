from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from g5_control_gap_planner import (
    DEFAULT_MIN_CONTROLS,
    DEFAULT_REQUIRED_MARKET_KINDS,
    PROHIBITED_OUTPUTS,
    _intersection,
    _load_market_requirements,
    _load_positive_symbols,
)
from g5_control_expansion_planner import _load_planning_universe

SCHEMA_VERSION = "1"
DEFAULT_MAX_PRIOR_DAYS = 45
RETROSPECTIVE_LABEL_COLUMNS = {"hacked", "actual", "soft"}


@dataclass(frozen=True)
class PriorFallbackCandidate:
    event_date: str
    candidate_symbol: str
    prior_observation_date: str
    prior_observation_age_days: int
    residual_slot_rank: int
    planning_method: str = "PRIOR_ONLY_RETROSPECTIVE_SYMBOL_OBSERVATION"
    eligible_g5_evidence: int = 0
    requires_date_specific_identity: int = 1
    requires_real_four_kind_market_data: int = 1
    requires_pre_event_point_in_time_metadata: int = 1
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_prior_observations(path: Path) -> tuple[list[tuple[date, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        by_lower = {name.lower(): name for name in fields}
        symbol_col = next((by_lower[x] for x in ("symbol", "historical_symbol") if x in by_lower), None)
        date_col = next((by_lower[x] for x in ("date", "event_date", "trade_date") if x in by_lower), None)
        if symbol_col is None or date_col is None:
            raise ValueError("planning universe requires symbol and date columns")
        ignored = sorted(name for name in fields if name.lower() in RETROSPECTIVE_LABEL_COLUMNS)
        rows: list[tuple[date, str]] = []
        for row_no, row in enumerate(reader, 2):
            symbol = str(row.get(symbol_col) or "").strip().upper()
            raw_date = str(row.get(date_col) or "").strip()[:10]
            if not symbol or not raw_date:
                continue
            try:
                observed = date.fromisoformat(raw_date)
            except ValueError as exc:
                raise ValueError(f"planning row {row_no}: invalid date") from exc
            rows.append((observed, symbol))
    return rows, ignored


def build(
    *,
    events_path: Path,
    requirements_path: Path,
    planning_universe_path: Path,
    output_dir: Path,
    min_controls: int = DEFAULT_MIN_CONTROLS,
    max_prior_days: int = DEFAULT_MAX_PRIOR_DAYS,
    required_market_kinds: tuple[str, ...] = DEFAULT_REQUIRED_MARKET_KINDS,
) -> dict:
    if min_controls < 1:
        raise ValueError("min_controls must be positive")
    if max_prior_days < 1:
        raise ValueError("max_prior_days must be positive")

    positives_by_date = _load_positive_symbols(events_path)
    requirements = _load_market_requirements(requirements_path)
    exact_by_date, ignored_labels = _load_planning_universe(planning_universe_path)
    observations, _ = _load_prior_observations(planning_universe_path)

    selected: list[PriorFallbackCandidate] = []
    residual_before = 0
    residual_after = 0
    residual_dates_before = 0

    for event_date in sorted(positives_by_date):
        positives = positives_by_date[event_date]
        by_kind = requirements.get(event_date, {})
        existing = _intersection([by_kind.get(kind, set()) for kind in required_market_kinds])
        existing.difference_update(positives)
        deficit = max(0, min_controls - len(existing))
        if not deficit:
            continue

        exact = set(exact_by_date.get(event_date, set()))
        exact.difference_update(positives)
        exact.difference_update(existing)
        exact_chosen = sorted(exact)[:deficit]
        residual = deficit - len(exact_chosen)
        if not residual:
            continue

        residual_dates_before += 1
        residual_before += residual
        target = date.fromisoformat(event_date)

        latest_prior: dict[str, date] = {}
        for observed, symbol in observations:
            age = (target - observed).days
            if age <= 0 or age > max_prior_days:
                continue
            if symbol in positives or symbol in existing or symbol in exact_chosen:
                continue
            prior = latest_prior.get(symbol)
            if prior is None or observed > prior:
                latest_prior[symbol] = observed

        ranked = sorted(
            latest_prior.items(),
            key=lambda item: ((target - item[1]).days, item[0]),
        )
        chosen = ranked[:residual]
        residual_after += residual - len(chosen)

        for rank, (symbol, observed) in enumerate(chosen, 1):
            selected.append(
                PriorFallbackCandidate(
                    event_date=event_date,
                    candidate_symbol=symbol,
                    prior_observation_date=observed.isoformat(),
                    prior_observation_age_days=(target - observed).days,
                    residual_slot_rank=rank,
                )
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "g5_prior_only_fallback_candidates.csv"
    fields = list(PriorFallbackCandidate.__dataclass_fields__)
    with candidate_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            writer.writerow(asdict(row))

    market_path = output_dir / "g5_prior_only_market_requirements.csv"
    with market_path.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "event_date",
            "candidate_symbol",
            "record_kind",
            "status",
            "eligible_g5_evidence",
            "research_use_only",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            for kind in required_market_kinds:
                writer.writerow(
                    {
                        "event_date": row.event_date,
                        "candidate_symbol": row.candidate_symbol,
                        "record_kind": kind,
                        "status": "G5_CONTROL_MARKET_ACQUISITION_REQUIRED",
                        "eligible_g5_evidence": 0,
                        "research_use_only": 1,
                    }
                )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Fill only residual structural G5 planning slots using symbols observed strictly before "
            "the event date. This is acquisition planning, not control evidence."
        ),
        "research_use_only": True,
        "inputs": {
            "events": {"path": str(events_path), "sha256": _sha256(events_path)},
            "market_requirements": {"path": str(requirements_path), "sha256": _sha256(requirements_path)},
            "planning_universe": {
                "path": str(planning_universe_path),
                "sha256": _sha256(planning_universe_path),
                "ignored_retrospective_label_columns": ignored_labels,
            },
        },
        "max_prior_observation_age_days": max_prior_days,
        "residual_deficient_dates_before_prior_fallback": residual_dates_before,
        "residual_symbol_date_slots_before_prior_fallback": residual_before,
        "selected_prior_fallback_symbol_dates": len(selected),
        "generated_market_requirement_rows": len(selected) * len(required_market_kinds),
        "residual_symbol_date_slots_after_prior_fallback": residual_after,
        "all_structural_slots_planned": residual_after == 0,
        "candidate_selection_uses_future_observations": False,
        "candidate_selection_uses_retrospective_labels": False,
        "g5_model_evaluation_controls_ready": False,
        "release_claimed": False,
        "policy": {
            "prior_observation_is_planning_evidence_only": True,
            "date_specific_identity_required": True,
            "real_four_kind_market_data_required": True,
            "pre_event_point_in_time_metadata_required": True,
            "final_contamination_and_match_quality_screening_required": True,
        },
        "outputs": {
            "fallback_candidates": str(candidate_path),
            "market_requirements": str(market_path),
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    (output_dir / "g5_prior_only_fallback_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan prior-only fallback candidates for residual G5 structural gaps.")
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--planning-universe", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-controls", type=int, default=DEFAULT_MIN_CONTROLS)
    parser.add_argument("--max-prior-days", type=int, default=DEFAULT_MAX_PRIOR_DAYS)
    args = parser.parse_args()
    result = build(
        events_path=args.events,
        requirements_path=args.requirements,
        planning_universe_path=args.planning_universe,
        output_dir=args.output_dir,
        min_controls=args.min_controls,
        max_prior_days=args.max_prior_days,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
