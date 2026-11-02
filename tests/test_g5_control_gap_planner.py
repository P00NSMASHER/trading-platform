from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from g5_control_gap_planner import build


def test_real_g2_scope_has_reproducible_g5_structural_gap(tmp_path: Path):
    summary = build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv",
        output_dir=tmp_path,
    )
    assert summary["event_date_count"] == 72
    assert summary["dates_with_g2_structural_pool_3plus"] == 49
    assert summary["dates_with_g2_structural_pool_deficit"] == 23
    assert summary["minimum_additional_candidate_symbol_dates"] == 52
    assert summary["g5_model_evaluation_controls_ready"] is False
    assert summary["release_claimed"] is False


def test_gap_rows_exclude_same_day_positive_symbols(tmp_path: Path):
    build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv",
        output_dir=tmp_path,
    )
    rows = list(csv.DictReader((tmp_path / "g5_market_candidate_gap.csv").open(encoding="utf-8")))
    assert len(rows) == 72
    for row in rows:
        positives = {x for x in row["same_date_positive_symbols"].split(";") if x}
        candidates = {x for x in row["g2_structural_candidate_symbols"].split(";") if x}
        assert positives.isdisjoint(candidates)

    by_date = {row["event_date"]: row for row in rows}
    assert by_date["2011-04-27"]["g2_structural_candidate_count"] == "0"
    assert by_date["2011-04-27"]["minimum_additional_candidate_symbol_dates"] == "3"
    assert by_date["2013-07-23"]["same_date_positive_symbols"] == "JNPR;MTH;PNRA;VMW"
    assert by_date["2013-07-23"]["minimum_additional_candidate_symbol_dates"] == "3"
