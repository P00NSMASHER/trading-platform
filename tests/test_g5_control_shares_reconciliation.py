from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_shares_reconciliation as shares


HISTORY_HEADER = (
    "historical_symbol,trade_date,roles,candidate_event_dates,"
    "normal_minutes_local,event_minutes_local,close_minute_local,"
    "require_equity_trade,require_equity_quote,require_option_trade,"
    "require_option_quote,require_shares_outstanding,research_use_only\n"
)
G4_HEADER = (
    "historical_symbol,trade_date,shares_outstanding,resolution_status,"
    "source_tag,source_kind,source_reference,fact_date,available_at,"
    "staleness_days,research_use_only\n"
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_reuses_only_exact_pre_cutoff_g4_shares_and_queues_every_gap(tmp_path: Path):
    history = _write(
        tmp_path / "history.csv",
        HISTORY_HEADER
        + "AAA,2015-02-17,event_point,2015-02-17,,14:18;14:19,15:59,1,1,1,1,1,1\n"
        + "BBB,2015-02-17,normalization_baseline,2015-02-18,14:19,,15:59,1,1,1,1,1,1\n"
        + "CCC,2015-02-17,normalization_baseline,2015-02-18,14:19,,15:59,1,1,1,1,1,1\n"
        + "DDD,2015-02-17,daily_close_history,2015-02-18,,,15:59,1,0,0,0,0,1\n",
    )
    g4 = _write(
        tmp_path / "g4.csv",
        G4_HEADER
        + "AAA,2015-02-17,100,resolved,g4,sec,aaa,2015-02-10,2015-02-17T13:00:00-05:00,7,1\n"
        + "CCC,2015-02-17,200,resolved,g4,sec,ccc,2015-02-10,2015-02-17T15:00:00-05:00,7,1\n",
    )

    summary = shares.build(
        control_history_path=history,
        canonical_g4_shares_path=g4,
        output_dir=tmp_path / "out",
    )

    assert summary["required_shares_symbol_date_count"] == 3
    assert summary["canonical_g4_reuse_count"] == 1
    assert summary["incremental_g5_shares_acquisition_count"] == 2
    assert summary["gap_reason_counts"] == {
        "CANONICAL_G4_AVAILABLE_AFTER_G5_CUTOFF": 1,
        "NO_CANONICAL_G4_ROW": 1,
    }

    reused = list(
        csv.DictReader(
            (tmp_path / "out/g5_control_shares_g4_reuse.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert [row["historical_symbol"] for row in reused] == ["AAA"]
    # event_minutes contains 14:18 and 14:19; the bridge deliberately uses the
    # earlier minute as the conservative availability boundary.
    assert reused[0]["latest_acceptable_available_at_utc"] == "2015-02-17T19:18:00Z"

    gaps = list(
        csv.DictReader(
            (tmp_path / "out/g5_control_shares_acquisition_queue.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert {row["historical_symbol"] for row in gaps} == {"BBB", "CCC"}
    assert all(row["preferred_route"] == shares.ACQUISITION_ROUTE for row in gaps)
    assert summary["policy"]["canonical_g5_readiness_unchanged"] is True
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False


def test_nonresolved_g4_row_is_not_reused(tmp_path: Path):
    history = _write(
        tmp_path / "history.csv",
        HISTORY_HEADER
        + "AAA,2015-02-17,normalization_baseline,2015-02-18,14:19,,15:59,1,1,1,1,1,1\n",
    )
    g4 = _write(
        tmp_path / "g4.csv",
        G4_HEADER
        + "AAA,2015-02-17,,reviewed_exclusion,g4,sec,aaa,,,0,1\n",
    )
    summary = shares.build(
        control_history_path=history,
        canonical_g4_shares_path=g4,
        output_dir=tmp_path / "out",
    )
    assert summary["canonical_g4_reuse_count"] == 0
    assert summary["gap_reason_counts"] == {"CANONICAL_G4_NOT_RESOLVED": 1}


def test_duplicate_or_malformed_resolved_g4_rows_fail_closed(tmp_path: Path):
    history = _write(
        tmp_path / "history.csv",
        HISTORY_HEADER
        + "AAA,2015-02-17,normalization_baseline,2015-02-18,14:19,,15:59,1,1,1,1,1,1\n",
    )
    duplicate = _write(
        tmp_path / "dup.csv",
        G4_HEADER
        + "AAA,2015-02-17,100,resolved,g4,sec,a,2015-02-10,2015-02-10T12:00:00-05:00,7,1\n"
        + "AAA,2015-02-17,100,resolved,g4,sec,b,2015-02-10,2015-02-10T12:00:00-05:00,7,1\n",
    )
    with pytest.raises(
        shares.G5ControlSharesReconciliationError,
        match="duplicate canonical G4 shares resolution",
    ):
        shares.build(
            control_history_path=history,
            canonical_g4_shares_path=duplicate,
            output_dir=tmp_path / "out1",
        )

    malformed = _write(
        tmp_path / "bad.csv",
        G4_HEADER
        + "AAA,2015-02-17,-1,resolved,g4,sec,a,2015-02-10,2015-02-10T12:00:00-05:00,7,1\n",
    )
    with pytest.raises(
        shares.G5ControlSharesReconciliationError,
        match="resolved shares_outstanding must be positive integer",
    ):
        shares.build(
            control_history_path=history,
            canonical_g4_shares_path=malformed,
            output_dir=tmp_path / "out2",
        )


def test_missing_cutoff_minute_fails_closed(tmp_path: Path):
    history = _write(
        tmp_path / "history.csv",
        HISTORY_HEADER
        + "AAA,2015-02-17,event_point,2015-02-17,,,15:59,1,1,1,1,1,1\n",
    )
    g4 = _write(tmp_path / "g4.csv", G4_HEADER)
    with pytest.raises(
        shares.G5ControlSharesReconciliationError,
        match="shares-required row has no admissible cutoff minute",
    ):
        shares.build(
            control_history_path=history,
            canonical_g4_shares_path=g4,
            output_dir=tmp_path / "out",
        )


def test_real_reconciliation_accounts_for_every_planned_shares_pair(tmp_path: Path):
    import g5_control_acquisition_planner as acquisition
    import g5_control_history_requirements as history

    control_dir = tmp_path / "controls"
    history_dir = tmp_path / "history"
    frozen = ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"

    acquisition.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=frozen,
        planning_universe_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
        output_dir=control_dir,
    )
    history_summary = history.build(
        candidate_path=control_dir / "g5_primary_candidate_symbol_dates.csv",
        output_dir=history_dir,
        frozen_requirements_path=frozen,
    )
    summary = shares.build(
        control_history_path=(
            history_dir / "g5_control_history_symbol_date_requirements.csv"
        ),
        canonical_g4_shares_path=(
            ROOT
            / "data/processed/authorized_input_real/shares_outstanding_resolutions.csv"
        ),
        output_dir=tmp_path / "shares",
    )

    assert summary["required_shares_symbol_date_count"] == (
        history_summary["shares_symbol_date_pair_count"]
    )
    assert (
        summary["canonical_g4_reuse_count"]
        + summary["incremental_g5_shares_acquisition_count"]
        == summary["required_shares_symbol_date_count"]
    )
    assert summary["incremental_g5_shares_acquisition_count"] > 0
    assert summary["distinct_incremental_historical_symbol_count"] > 0
    assert summary["policy"]["exact_symbol_date_reuse_only"] is True
    assert summary["policy"]["canonical_g4_availability_rechecked_for_g5_cutoff"] is True
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
