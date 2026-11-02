from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from g5_control_expansion_planner import build


def test_real_planning_universe_fills_all_but_one_structural_slot(tmp_path: Path):
    summary = build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv",
        planning_universe_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
        output_dir=tmp_path,
    )

    assert summary["structurally_deficient_date_count"] == 23
    assert summary["structural_deficit_slots_before"] == 52
    assert summary["selected_candidate_symbol_dates"] == 51
    assert summary["generated_market_requirement_rows"] == 204
    assert summary["fully_structurally_coverable_deficient_dates"] == 22
    assert summary["remaining_deficient_dates_after_planning"] == 1
    assert summary["residual_unfilled_symbol_date_slots"] == 1
    assert summary["candidate_selection_uses_retrospective_labels"] is False
    assert summary["g5_model_evaluation_controls_ready"] is False
    assert summary["release_claimed"] is False

    by_date = {
        row["event_date"]: row
        for row in csv.DictReader(
            (tmp_path / "g5_control_expansion_by_date.csv").open(encoding="utf-8")
        )
    }
    assert by_date["2014-12-15"]["residual_unfilled_slots"] == "1"


def test_retrospective_labels_do_not_change_candidate_selection(tmp_path: Path):
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

    out_a, out_b = tmp_path / "a", tmp_path / "b"
    build(
        events_path=events,
        requirements_path=requirements,
        planning_universe_path=universe_a,
        output_dir=out_a,
    )
    build(
        events_path=events,
        requirements_path=requirements,
        planning_universe_path=universe_b,
        output_dir=out_b,
    )

    def selected(path: Path) -> list[str]:
        return [
            row["candidate_symbol"]
            for row in csv.DictReader(
                (path / "g5_control_expansion_candidates.csv").open(encoding="utf-8")
            )
        ]

    assert selected(out_a) == ["AAA", "BBB", "CCC"]
    assert selected(out_a) == selected(out_b)


def test_known_positive_and_existing_g2_candidates_are_never_reselected(tmp_path: Path):
    events = tmp_path / "events.csv"
    requirements = tmp_path / "requirements.csv"
    universe = tmp_path / "universe.csv"
    events.write_text(
        "event_id,historical_symbol,first_documented_illicit_trade_ts\n"
        "E1,POS,2015-01-02 14:00:00\n",
        encoding="utf-8",
    )
    requirements.write_text(
        "record_kind,trade_date,historical_symbols\n"
        "equity_trade,2015-01-02,POS;EXIST\n"
        "equity_quote,2015-01-02,POS;EXIST\n"
        "option_trade,2015-01-02,POS;EXIST\n"
        "option_quote,2015-01-02,POS;EXIST\n",
        encoding="utf-8",
    )
    universe.write_text(
        "SYMBOL,date,Hacked,Actual,Soft\n"
        "POS,2015-01-02,0,0,\n"
        "EXIST,2015-01-02,0,0,\n"
        "AAA,2015-01-02,0,0,\n"
        "BBB,2015-01-02,0,0,\n",
        encoding="utf-8",
    )

    build(
        events_path=events,
        requirements_path=requirements,
        planning_universe_path=universe,
        output_dir=tmp_path / "out",
    )
    selected = {
        row["candidate_symbol"]
        for row in csv.DictReader(
            (tmp_path / "out/g5_control_expansion_candidates.csv").open(encoding="utf-8")
        )
    }
    assert selected == {"AAA", "BBB"}
