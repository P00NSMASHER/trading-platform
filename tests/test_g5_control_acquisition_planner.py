from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from g5_control_acquisition_planner import (
    DERIVED_FIELDS,
    EXTERNAL_FIELDS,
    FIELD_ROUTES,
    build,
)
from metadata_resolver import CONTROL_COVARIATES


def _build_real(tmp_path: Path):
    return build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv",
        planning_universe_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
        output_dir=tmp_path,
    )


def test_real_g5_acquisition_plan_combines_existing_and_expansion_queues(tmp_path: Path):
    summary = _build_real(tmp_path)

    assert summary["event_date_count"] == 72
    assert summary["dates_with_g2_structural_pool_3plus"] == 49
    assert summary["dates_with_g2_structural_pool_deficit"] == 23
    assert summary["initial_minimum_additional_candidate_symbol_dates"] == 52
    assert summary["planned_expansion_candidate_symbol_date_count"] == 51
    assert summary["generated_expansion_market_requirement_rows"] == 204
    assert summary["fully_fillable_deficient_dates_from_planning_universe"] == 22
    assert summary["dates_structurally_reaching_3_after_plan"] == 71
    assert summary["residual_unfilled_symbol_date_slots"] == 1
    assert summary["candidate_symbol_date_count"] > 51
    assert summary["control_field_count"] == len(CONTROL_COVARIATES)
    assert summary["field_requirement_count"] == (
        summary["candidate_symbol_date_count"] * len(CONTROL_COVARIATES)
    )
    assert summary["derived_field_requirement_count"] == (
        summary["candidate_symbol_date_count"] * len(DERIVED_FIELDS)
    )
    assert summary["external_field_requirement_count"] == (
        summary["candidate_symbol_date_count"] * len(EXTERNAL_FIELDS)
    )
    assert summary["g5_model_evaluation_controls_ready"] is False
    assert summary["release_claimed"] is False
    assert summary["planning_policy"]["retrospective_sample_labels_used_for_selection"] is False
    assert summary["planning_policy"]["retrospective_sample_labels_may_close_g5"] is False
    assert summary["planning_policy"]["planning_rows_are_g5_evidence"] is False


def test_field_routes_cover_exact_g5_readiness_contract():
    assert set(FIELD_ROUTES) == set(CONTROL_COVARIATES)
    assert EXTERNAL_FIELDS | DERIVED_FIELDS == set(CONTROL_COVARIATES)
    assert EXTERNAL_FIELDS.isdisjoint(DERIVED_FIELDS)
    assert EXTERNAL_FIELDS == {
        "sector",
        "index_bucket",
        "institutional_ownership",
        "analyst_coverage",
        "borrow_cost",
    }


def test_candidate_rows_exclude_positives_and_remain_planning_only(tmp_path: Path):
    _build_real(tmp_path)
    candidates = list(csv.DictReader((tmp_path / "g5_candidate_symbol_dates.csv").open(encoding="utf-8")))
    fields = list(csv.DictReader((tmp_path / "g5_candidate_field_requirements.csv").open(encoding="utf-8")))
    market_rows = list(csv.DictReader((tmp_path / "g5_expansion_market_requirements.csv").open(encoding="utf-8")))

    positives_by_date = {}
    with (ROOT / "data/processed/historical_events.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            day = row["first_documented_illicit_trade_ts"][:10]
            positives_by_date.setdefault(day, set()).add(row["historical_symbol"])

    assert candidates
    expansion = []
    for row in candidates:
        assert row["candidate_symbol"] not in positives_by_date[row["event_date"]]
        assert row["latest_acceptable_effective_ts_utc"].endswith("Z")
        assert row["eligible_g5_evidence"] == "0"
        assert row["research_use_only"] == "1"
        if row["structural_origin"] == "RETROSPECTIVE_SYMBOL_DATE_PLANNING_ONLY":
            expansion.append(row)
            assert row["market_data_status"] == "EXPANSION_MARKET_ACQUISITION_REQUIRED"
        else:
            assert row["structural_origin"] == "FROZEN_G2_FOUR_KIND_INTERSECTION"
            assert row["market_data_status"] == "FROZEN_G2_REQUIREMENT_SCOPE_ONLY"

    assert len(expansion) == 51
    assert len(market_rows) == 204
    assert {row["record_kind"] for row in market_rows} == {
        "equity_trade",
        "equity_quote",
        "option_trade",
        "option_quote",
    }
    assert all(row["eligible_g5_evidence"] == "0" for row in market_rows)

    assert len(fields) == len(candidates) * len(CONTROL_COVARIATES)
    for row in fields:
        assert row["field_name"] in CONTROL_COVARIATES
        assert row["route"] == FIELD_ROUTES[row["field_name"]]
        assert row["latest_acceptable_effective_ts_utc"].endswith("Z")
        assert row["anti_lookahead_required"] == "1"
        assert row["eligible_g5_evidence"] == "0"
        if row["field_name"] in EXTERNAL_FIELDS:
            assert row["status"] == "EXTERNAL_POINT_IN_TIME_SOURCE_REQUIRED"
        else:
            assert row["status"] == "DERIVE_AFTER_REAL_G2_G4"


def test_retrospective_labels_do_not_change_expansion_choice(tmp_path: Path):
    events = tmp_path / "events.csv"
    requirements = tmp_path / "requirements.csv"
    universe_a = tmp_path / "universe_a.csv"
    universe_b = tmp_path / "universe_b.csv"

    events.write_text(
        "event_id,historical_symbol,first_documented_illicit_trade_ts\n"
        "E1,POS,2015-01-02 14:00:00\n",
        encoding="utf-8",
    )
    requirements.write_text(
        "record_kind,trade_date,historical_symbols\n"
        "equity_trade,2015-01-02,POS\n"
        "equity_quote,2015-01-02,POS\n"
        "option_trade,2015-01-02,POS\n"
        "option_quote,2015-01-02,POS\n",
        encoding="utf-8",
    )
    universe_a.write_text(
        "SYMBOL,date,Hacked,Actual,Soft\n"
        "AAA,2015-01-02,0,0,0.1\n"
        "BBB,2015-01-02,1,1,0.9\n"
        "CCC,2015-01-02,0,1,0.2\n",
        encoding="utf-8",
    )
    universe_b.write_text(
        "SYMBOL,date,Hacked,Actual,Soft\n"
        "AAA,2015-01-02,1,1,9.9\n"
        "BBB,2015-01-02,0,0,-9.9\n"
        "CCC,2015-01-02,1,0,4.2\n",
        encoding="utf-8",
    )

    def selected(universe: Path, out: Path) -> list[str]:
        build(
            events_path=events,
            requirements_path=requirements,
            planning_universe_path=universe,
            output_dir=out,
        )
        return [
            row["candidate_symbol"]
            for row in csv.DictReader((out / "g5_candidate_symbol_dates.csv").open(encoding="utf-8"))
            if row["structural_origin"] == "RETROSPECTIVE_SYMBOL_DATE_PLANNING_ONLY"
        ]

    assert selected(universe_a, tmp_path / "a") == ["AAA", "BBB", "CCC"]
    assert selected(universe_b, tmp_path / "b") == ["AAA", "BBB", "CCC"]
