from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as acquisition
import g5_control_history_requirements as history


def _single_candidate(tmp_path: Path) -> Path:
    p = tmp_path / "candidates.csv"
    p.write_text(
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc\n"
        "2015-02-17,C1,2015-02-17T19:19:00Z\n",
        encoding="utf-8",
    )
    return p


def _frozen_fixture(tmp_path: Path) -> Path:
    p = tmp_path / "frozen.csv"
    p.write_text(
        "record_kind,trade_date,historical_symbols\n"
        "equity_trade,2015-02-17,C1\n"
        "equity_quote,2015-02-17,C1\n"
        "option_trade,2015-02-17,C1\n"
        "option_quote,2015-02-17,C1\n",
        encoding="utf-8",
    )
    return p


def test_single_candidate_requires_event_plus_history(tmp_path: Path):
    summary = history.build(
        candidate_path=_single_candidate(tmp_path),
        output_dir=tmp_path / "out",
        frozen_requirements_path=_frozen_fixture(tmp_path),
    )

    assert summary["primary_candidate_symbol_date_count"] == 1
    assert summary["normalization_sessions"] == 21
    assert summary["daily_close_sessions"] == 22
    assert summary["unique_control_history_symbol_date_pairs"] == 23
    assert summary["role_symbol_date_counts"]["event_point"] == 1
    assert summary["role_symbol_date_counts"]["normalization_baseline"] == 21
    assert summary["role_symbol_date_counts"]["daily_close_history"] == 22

    assert summary["market_symbol_date_pair_counts"] == {
        "equity_trade": 23,
        "equity_quote": 22,
        "option_trade": 22,
        "option_quote": 22,
    }
    assert summary["frozen_g2_overlap_pair_counts"] == {
        "equity_trade": 1,
        "equity_quote": 1,
        "option_trade": 1,
        "option_quote": 1,
    }
    assert summary["additional_g5_market_pair_counts"] == {
        "equity_trade": 22,
        "equity_quote": 21,
        "option_trade": 21,
        "option_quote": 21,
    }
    assert summary["shares_symbol_date_pair_count"] == 22
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False


def test_detail_rows_encode_minute_roles_and_close_minute(tmp_path: Path):
    out = tmp_path / "out"
    history.build(
        candidate_path=_single_candidate(tmp_path),
        output_dir=out,
    )
    rows = list(
        csv.DictReader(
            (out / "g5_control_history_symbol_date_requirements.csv").open(
                encoding="utf-8"
            )
        )
    )
    by_date = {row["trade_date"]: row for row in rows}

    event = by_date["2015-02-17"]
    assert event["roles"] == "event_point"
    assert event["event_minutes_local"] == "14:18;14:19"
    assert event["normal_minutes_local"] == ""
    assert event["close_minute_local"] == "15:59"
    assert event["require_equity_trade"] == "1"
    assert event["require_equity_quote"] == "1"
    assert event["require_option_trade"] == "1"
    assert event["require_option_quote"] == "1"
    assert event["require_shares_outstanding"] == "1"

    daily_only = [
        row
        for row in rows
        if row["roles"] == "daily_close_history"
    ]
    assert len(daily_only) == 1
    assert daily_only[0]["require_equity_trade"] == "1"
    assert daily_only[0]["require_equity_quote"] == "0"
    assert daily_only[0]["require_option_trade"] == "0"
    assert daily_only[0]["require_option_quote"] == "0"
    assert daily_only[0]["require_shares_outstanding"] == "0"


def test_real_primary_queue_exposes_additional_history_gap(tmp_path: Path):
    acquisition_out = tmp_path / "acquisition"
    acquisition.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv",
        planning_universe_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
        output_dir=acquisition_out,
    )

    summary = history.build(
        candidate_path=acquisition_out / "g5_primary_candidate_symbol_dates.csv",
        output_dir=tmp_path / "history",
        frozen_requirements_path=ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv",
    )

    assert summary["primary_candidate_symbol_date_count"] == 216
    assert summary["role_symbol_date_counts"]["event_point"] == 216
    assert summary["role_symbol_date_counts"]["normalization_baseline"] > 216
    assert summary["role_symbol_date_counts"]["daily_close_history"] >= (
        summary["role_symbol_date_counts"]["normalization_baseline"]
    )
    assert summary["shares_symbol_date_pair_count"] > 216

    for kind in (
        "equity_trade",
        "equity_quote",
        "option_trade",
        "option_quote",
    ):
        assert summary["market_symbol_date_pair_counts"][kind] > 216
        assert summary["additional_g5_market_pair_counts"][kind] > 0
        assert (
            summary["market_symbol_date_pair_counts"][kind]
            == summary["frozen_g2_overlap_pair_counts"][kind]
            + summary["additional_g5_market_pair_counts"][kind]
        )

    assert summary["g5_dates_resolved_change"] == 0
    assert summary["policy"]["requirements_are_g5_evidence"] is False
    assert summary["policy"]["no_data_fetch_or_purchase_performed"] is True
