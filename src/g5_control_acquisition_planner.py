from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from g5_control_expansion_planner import _load_planning_universe
from g5_prior_fallback_planner import DEFAULT_MAX_PRIOR_DAYS, _load_prior_observations
from g5_control_gap_planner import (
    DEFAULT_MIN_CONTROLS,
    DEFAULT_REQUIRED_MARKET_KINDS,
    _intersection,
    _load_market_requirements,
    _load_positive_symbols,
)
from metadata_resolver import CONTROL_COVARIATES

SCHEMA_VERSION = "3"
EVENT_TIMEZONE = ZoneInfo("America/New_York")

FIELD_ROUTES = {
    "sector": "POINT_IN_TIME_SECURITY_CLASSIFICATION",
    "index_bucket": "POINT_IN_TIME_INDEX_MEMBERSHIP",
    "market_cap": "G2_PRICE_X_G4_SHARES",
    "price": "G2_EQUITY_TRADE_QUOTE",
    "trailing_21d_vol": "G2_PRE_EVENT_EQUITY_HISTORY",
    "normal_minute_volume": "G2_PRE_EVENT_EQUITY_HISTORY",
    "normal_minute_turnover": "G2_PRE_EVENT_EQUITY_HISTORY_X_G4_SHARES",
    "normal_relative_spread": "G2_PRE_EVENT_EQUITY_QUOTES",
    "option_liquidity": "G2_PRE_EVENT_OPTION_HISTORY",
    "institutional_ownership": "POINT_IN_TIME_13F_OR_AUTHORIZED_REFERENCE",
    "analyst_coverage": "AUTHORIZED_POINT_IN_TIME_ANALYST_SOURCE",
    "borrow_cost": "AUTHORIZED_POINT_IN_TIME_SECURITIES_LENDING_SOURCE",
    "pre_event_return": "G2_PRE_EVENT_EQUITY_HISTORY",
}

EXTERNAL_FIELDS = {
    "sector",
    "index_bucket",
    "institutional_ownership",
    "analyst_coverage",
    "borrow_cost",
}
DERIVED_FIELDS = set(CONTROL_COVARIATES) - EXTERNAL_FIELDS

PROHIBITED_OUTPUTS = [
    "BUY",
    "SELL",
    "expected_return",
    "target_price",
    "position_size",
    "order",
    "execution_instruction",
]


@dataclass(frozen=True)
class CandidateSymbolDate:
    event_date: str
    candidate_symbol: str
    latest_acceptable_effective_ts_utc: str
    structural_origin: str
    market_data_status: str
    required_field_count: int
    derived_field_count: int
    external_field_count: int
    eligible_g5_evidence: int = 0
    research_use_only: int = 1


@dataclass(frozen=True)
class FieldRequirement:
    event_date: str
    candidate_symbol: str
    field_name: str
    route: str
    status: str
    market_data_prerequisite: str
    latest_acceptable_effective_ts_utc: str
    anti_lookahead_required: int = 1
    eligible_g5_evidence: int = 0
    research_use_only: int = 1


@dataclass(frozen=True)
class MarketAcquisitionRequirement:
    event_date: str
    candidate_symbol: str
    record_kind: str
    status: str = "G5_CONTROL_MARKET_ACQUISITION_REQUIRED"
    eligible_g5_evidence: int = 0
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_event_ts(raw: str) -> datetime:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("blank event timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=EVENT_TIMEZONE)
    return dt.astimezone(timezone.utc)


def _event_cutoffs(events_path: Path) -> dict[str, str]:
    by_date: dict[str, list[datetime]] = defaultdict(list)
    with events_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"event_id", "first_documented_illicit_trade_ts"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"events file missing columns: {sorted(missing)}")
        for row_no, row in enumerate(reader, 2):
            raw = str(row.get("first_documented_illicit_trade_ts") or "").strip()
            try:
                dt = _parse_event_ts(raw)
            except Exception as exc:
                raise ValueError(f"event row {row_no}: invalid first documented trade timestamp") from exc
            by_date[raw[:10]].append(dt)

    out: dict[str, str] = {}
    for day, values in by_date.items():
        cutoff = min(values)
        out[day] = cutoff.isoformat(timespec="seconds").replace("+00:00", "Z")
    return out


def _write_csv(path: Path, rows: list[object], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _validate_contract() -> None:
    required = set(CONTROL_COVARIATES)
    routed = set(FIELD_ROUTES)
    if required != routed:
        missing = sorted(required - routed)
        extra = sorted(routed - required)
        raise ValueError(f"G5 field-route contract drift: missing={missing}, extra={extra}")
    if EXTERNAL_FIELDS | DERIVED_FIELDS != required:
        raise ValueError("G5 external/derived field partition does not cover the readiness contract")
    if EXTERNAL_FIELDS & DERIVED_FIELDS:
        raise ValueError("G5 field route partitions overlap")


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
    _validate_contract()
    if min_controls < 1:
        raise ValueError("min_controls must be positive")
    if max_prior_days < 1:
        raise ValueError("max_prior_days must be positive")
    if not required_market_kinds:
        raise ValueError("at least one required market kind is required")

    positives_by_date = _load_positive_symbols(events_path)
    market_requirements = _load_market_requirements(requirements_path)
    planning_by_date, ignored_label_columns = _load_planning_universe(planning_universe_path)
    prior_observations, _ = _load_prior_observations(planning_universe_path)
    cutoffs = _event_cutoffs(events_path)

    candidates: list[CandidateSymbolDate] = []
    fields: list[FieldRequirement] = []
    expansion_market_rows: list[MarketAcquisitionRequirement] = []

    initially_sufficient_dates = 0
    deficient_dates = 0
    initial_deficit_slots = 0
    expansion_candidate_count = 0
    exact_expansion_candidate_count = 0
    prior_fallback_candidate_count = 0
    fully_fillable_deficient_dates = 0
    residual_unfilled_slots = 0

    for event_date in sorted(positives_by_date):
        positives = positives_by_date[event_date]
        by_kind = market_requirements.get(event_date, {})
        existing_pool = _intersection([by_kind.get(kind, set()) for kind in required_market_kinds])
        existing_pool.difference_update(positives)

        deficit = max(0, min_controls - len(existing_pool))
        if deficit:
            deficient_dates += 1
            initial_deficit_slots += deficit
        else:
            initially_sufficient_dates += 1

        available = set(planning_by_date.get(event_date, set()))
        available.difference_update(positives)
        available.difference_update(existing_pool)
        exact_expansion = sorted(available)[:deficit]

        residual_after_exact = deficit - len(exact_expansion)
        prior_expansion: list[str] = []
        if residual_after_exact:
            target = date.fromisoformat(event_date)
            latest_prior: dict[str, date] = {}
            for observed, symbol in prior_observations:
                age = (target - observed).days
                if age <= 0 or age > max_prior_days:
                    continue
                if symbol in positives or symbol in existing_pool or symbol in exact_expansion:
                    continue
                previous = latest_prior.get(symbol)
                if previous is None or observed > previous:
                    latest_prior[symbol] = observed
            ranked_prior = sorted(
                latest_prior.items(),
                key=lambda item: ((target - item[1]).days, item[0]),
            )
            prior_expansion = [
                symbol for symbol, _observed in ranked_prior[:residual_after_exact]
            ]

        expansion = [*exact_expansion, *prior_expansion]
        residual = deficit - len(expansion)
        if deficit and residual == 0:
            fully_fillable_deficient_dates += 1
        residual_unfilled_slots += residual
        expansion_candidate_count += len(expansion)
        exact_expansion_candidate_count += len(exact_expansion)
        prior_fallback_candidate_count += len(prior_expansion)

        cutoff = cutoffs[event_date]
        planned_candidates = [
            (
                symbol,
                "FROZEN_G2_FOUR_KIND_INTERSECTION",
                "FROZEN_G2_REQUIREMENT_SCOPE_ONLY",
            )
            for symbol in sorted(existing_pool)
        ] + [
            (
                symbol,
                "RETROSPECTIVE_SYMBOL_DATE_PLANNING_ONLY",
                "EXPANSION_MARKET_ACQUISITION_REQUIRED",
            )
            for symbol in exact_expansion
        ] + [
            (
                symbol,
                "PRIOR_ONLY_RETROSPECTIVE_SYMBOL_OBSERVATION",
                "EXPANSION_MARKET_ACQUISITION_REQUIRED",
            )
            for symbol in prior_expansion
        ]

        for symbol, origin, market_status in planned_candidates:
            candidates.append(
                CandidateSymbolDate(
                    event_date=event_date,
                    candidate_symbol=symbol,
                    latest_acceptable_effective_ts_utc=cutoff,
                    structural_origin=origin,
                    market_data_status=market_status,
                    required_field_count=len(CONTROL_COVARIATES),
                    derived_field_count=len(DERIVED_FIELDS),
                    external_field_count=len(EXTERNAL_FIELDS),
                )
            )

            market_prerequisite = (
                "REAL_G2_FOUR_KIND_EXPANSION"
                if market_status == "EXPANSION_MARKET_ACQUISITION_REQUIRED"
                else "REAL_G2_FOUR_KIND_DELIVERY"
            )
            for field_name in CONTROL_COVARIATES:
                external = field_name in EXTERNAL_FIELDS
                fields.append(
                    FieldRequirement(
                        event_date=event_date,
                        candidate_symbol=symbol,
                        field_name=field_name,
                        route=FIELD_ROUTES[field_name],
                        status=(
                            "EXTERNAL_POINT_IN_TIME_SOURCE_REQUIRED"
                            if external
                            else "DERIVE_AFTER_REAL_G2_G4"
                        ),
                        market_data_prerequisite=market_prerequisite,
                        latest_acceptable_effective_ts_utc=cutoff,
                    )
                )

        for symbol in expansion:
            for kind in required_market_kinds:
                expansion_market_rows.append(
                    MarketAcquisitionRequirement(
                        event_date=event_date,
                        candidate_symbol=symbol,
                        record_kind=kind,
                    )
                )

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "g5_candidate_symbol_dates.csv"
    field_path = output_dir / "g5_candidate_field_requirements.csv"
    market_path = output_dir / "g5_expansion_market_requirements.csv"
    summary_path = output_dir / "g5_control_acquisition_summary.json"

    _write_csv(
        candidate_path,
        candidates,
        list(CandidateSymbolDate.__dataclass_fields__),
    )
    _write_csv(
        field_path,
        fields,
        list(FieldRequirement.__dataclass_fields__),
    )
    _write_csv(
        market_path,
        expansion_market_rows,
        list(MarketAcquisitionRequirement.__dataclass_fields__),
    )

    derived_requirements = sum(row.field_name in DERIVED_FIELDS for row in fields)
    external_requirements = len(fields) - derived_requirements
    existing_candidate_count = len(candidates) - expansion_candidate_count
    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Deterministic G5 acquisition plan for genuine point-in-time matched controls. "
            "It combines the frozen G2 structural candidate pool with the planning-only expansion "
            "queue, then emits field-level pre-event metadata requirements without treating plans, "
            "reviewed exclusions, synthetic rows, or retrospective labels as genuine control evidence."
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
        "required_market_kinds": list(required_market_kinds),
        "minimum_controls_per_event_date": min_controls,
        "event_date_count": len(positives_by_date),
        "dates_with_g2_structural_pool_3plus": initially_sufficient_dates,
        "dates_with_g2_structural_pool_deficit": deficient_dates,
        "initial_minimum_additional_candidate_symbol_dates": initial_deficit_slots,
        "existing_scope_candidate_symbol_date_count": existing_candidate_count,
        "planned_expansion_candidate_symbol_date_count": expansion_candidate_count,
        "exact_date_expansion_candidate_symbol_date_count": exact_expansion_candidate_count,
        "prior_only_expansion_candidate_symbol_date_count": prior_fallback_candidate_count,
        "max_prior_observation_age_days": max_prior_days,
        "generated_expansion_market_requirement_rows": len(expansion_market_rows),
        "fully_fillable_deficient_dates_from_planning_universe": fully_fillable_deficient_dates,
        "dates_structurally_reaching_3_after_plan": (
            initially_sufficient_dates + fully_fillable_deficient_dates
        ),
        "residual_unfilled_symbol_date_slots": residual_unfilled_slots,
        "candidate_symbol_date_count": len(candidates),
        "control_field_count": len(CONTROL_COVARIATES),
        "field_requirement_count": len(fields),
        "derived_field_requirement_count": derived_requirements,
        "external_field_requirement_count": external_requirements,
        "derived_fields": sorted(DERIVED_FIELDS),
        "external_fields": sorted(EXTERNAL_FIELDS),
        "dependencies": {
            "G2_REAL_MARKET_DATA": (
                "Required for every existing-scope candidate and for each expansion market row before "
                "price, volatility, pre-event return, normal volume/spread, turnover inputs, or option "
                "liquidity may be treated as real."
            ),
            "G4_POINT_IN_TIME_SHARES": (
                "Required with real prices for market capitalization and turnover normalization."
            ),
            "G2_STABLE_SECURITY_IDENTITY": (
                "Required for safe market joins and for any residual universe expansion."
            ),
            "EXTERNAL_POINT_IN_TIME_METADATA": (
                "Sector, historical index bucket, institutional ownership, analyst coverage, and "
                "borrow cost require admissible point-in-time sources available no later than cutoff."
            ),
        },
        "planning_policy": {
            "retrospective_sample_labels_used_for_selection": False,
            "retrospective_sample_labels_may_close_g5": False,
            "planning_rows_are_g5_evidence": False,
            "candidate_rows_are_g5_evidence": False,
            "field_requirement_rows_are_g5_evidence": False,
            "expansion_market_requirement_rows_are_g5_evidence": False,
            "final_contamination_match_quality_and_point_in_time_checks_required": True,
        },
        "g5_model_evaluation_controls_ready": False,
        "release_claimed": False,
        "outputs": {
            "candidate_symbol_dates": str(candidate_path),
            "field_requirements": str(field_path),
            "expansion_market_requirements": str(market_path),
            "summary": str(summary_path),
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a fail-closed field-level acquisition plan for genuine G5 controls."
    )
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
