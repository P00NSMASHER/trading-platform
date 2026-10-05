from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from g5_prior_fallback_planner import build


def test_real_residual_structural_gap_is_filled_without_future_observation(tmp_path: Path):
    summary = build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv",
        planning_universe_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
        output_dir=tmp_path,
    )
    assert summary["residual_deficient_dates_before_prior_fallback"] == 1
    assert summary["residual_symbol_date_slots_before_prior_fallback"] == 1
    assert summary["selected_prior_fallback_symbol_dates"] == 1
    assert summary["generated_market_requirement_rows"] == 4
    assert summary["residual_symbol_date_slots_after_prior_fallback"] == 0
    assert summary["all_structural_slots_planned"] is True
    assert summary["candidate_selection_uses_future_observations"] is False
    assert summary["candidate_selection_uses_retrospective_labels"] is False
    assert summary["g5_model_evaluation_controls_ready"] is False

    rows = list(csv.DictReader((tmp_path / "g5_prior_only_fallback_candidates.csv").open(encoding="utf-8")))
    assert rows == [
        {
            "event_date": "2014-12-15",
            "candidate_symbol": "NDSN",
            "prior_observation_date": "2014-12-11",
            "prior_observation_age_days": "4",
            "residual_slot_rank": "1",
            "planning_method": "PRIOR_ONLY_RETROSPECTIVE_SYMBOL_OBSERVATION",
            "eligible_g5_evidence": "0",
            "requires_date_specific_identity": "1",
            "requires_real_four_kind_market_data": "1",
            "requires_pre_event_point_in_time_metadata": "1",
            "research_use_only": "1",
        }
    ]


def test_future_only_symbol_is_never_selected(tmp_path: Path):
    events = tmp_path / "events.csv"
    req = tmp_path / "requirements.csv"
    universe = tmp_path / "universe.csv"

    events.write_text(
        "event_id,historical_symbol,first_documented_illicit_trade_ts\n"
        "E1,POS,2015-01-15 14:00:00\n",
        encoding="utf-8",
    )
    req.write_text(
        "record_kind,trade_date,historical_symbols\n"
        "equity_trade,2015-01-15,POS\n"
        "equity_quote,2015-01-15,POS\n"
        "option_trade,2015-01-15,POS\n"
        "option_quote,2015-01-15,POS\n",
        encoding="utf-8",
    )
    universe.write_text(
        "SYMBOL,date,Hacked,Actual,Soft\n"
        "AAA,2015-01-10,1,1,9.9\n"
        "BBB,2015-01-16,0,0,-9.9\n"
        "CCC,2015-01-17,1,0,4.2\n",
        encoding="utf-8",
    )

    summary = build(
        events_path=events,
        requirements_path=req,
        planning_universe_path=universe,
        output_dir=tmp_path / "out",
        min_controls=1,
    )
    rows = list(csv.DictReader((tmp_path / "out/g5_prior_only_fallback_candidates.csv").open(encoding="utf-8")))
    assert [row["candidate_symbol"] for row in rows] == ["AAA"]
    assert summary["candidate_selection_uses_future_observations"] is False
