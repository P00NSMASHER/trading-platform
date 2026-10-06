from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as acquisition
import g5_control_history_requirements as history
import g5_control_shares_anchor_reuse as anchor_reuse
import g5_control_shares_reconciliation as reconciliation


GAP_HEADER = (
    "historical_symbol,trade_date,latest_acceptable_available_at_utc,"
    "gap_reason,existing_resolution_status,existing_available_at,"
    "preferred_route,required_fields,max_fact_staleness_days,research_use_only\n"
)
G4_HEADER = (
    "historical_symbol,trade_date,shares_outstanding,resolution_status,"
    "source_id,source_family,source_reference,fact_date,available_at,"
    "staleness_days,research_use_only\n"
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _gap_row(
    symbol: str,
    trade_date: str,
    cutoff: str,
    *,
    reason: str = "NO_CANONICAL_G4_ROW",
    max_staleness: int = 130,
) -> str:
    return (
        f"{symbol},{trade_date},{cutoff},{reason},,,"
        "PUBLIC_SEC_XBRL_OR_AUTHORIZED_EXCHANGE_REFERENCE,"
        "historical_symbol;trade_date;fact_date;available_at;"
        f"shares_outstanding;source_reference,{max_staleness},1\n"
    )


def _g4_row(
    symbol: str,
    trade_date: str,
    shares: int,
    fact_date: str,
    available_at: str,
    *,
    source: str = "https://example.test/sec",
) -> str:
    return (
        f"{symbol},{trade_date},{shares},resolved,g4-test,sec_xbrl_companyfacts,"
        f"{source},{fact_date},{available_at},0,1\n"
    )


def test_reuses_earlier_g4_anchor_when_point_in_time_contract_is_satisfied(
    tmp_path: Path,
):
    gaps = _write(
        tmp_path / "gaps.csv",
        GAP_HEADER
        + _gap_row("AAA", "2015-02-18", "2015-02-18T19:18:00Z"),
    )
    g4 = _write(
        tmp_path / "g4.csv",
        G4_HEADER
        + _g4_row(
            "AAA",
            "2015-02-17",
            100,
            "2015-02-10",
            "2015-02-17T13:00:00-05:00",
        ),
    )

    out = tmp_path / "out"
    summary = anchor_reuse.build(
        shares_gap_queue_path=gaps,
        canonical_g4_shares_path=g4,
        output_dir=out,
    )

    assert summary["input_gap_count"] == 1
    assert summary["cross_date_g4_anchor_reuse_count"] == 1
    assert summary["remaining_incremental_acquisition_count"] == 0
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False

    rows = list(
        csv.DictReader(
            (out / "g5_control_shares_cross_date_g4_reuse.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(rows) == 1
    assert rows[0]["canonical_anchor_trade_date"] == "2015-02-17"
    assert rows[0]["shares_outstanding"] == "100"
    assert rows[0]["fact_date"] == "2015-02-10"
    assert rows[0]["target_staleness_days"] == "8"
    assert (
        rows[0]["resolution_status"]
        == "REUSE_CANONICAL_G4_POINT_IN_TIME_ANCHOR"
    )


def test_stale_after_cutoff_and_future_anchor_rows_remain_unreused(tmp_path: Path):
    gaps = _write(
        tmp_path / "gaps.csv",
        GAP_HEADER
        + _gap_row("STALE", "2015-06-15", "2015-06-15T18:00:00Z")
        + _gap_row("LATE", "2015-02-18", "2015-02-18T19:18:00Z")
        + _gap_row("FUTURE", "2015-02-18", "2015-02-18T19:18:00Z"),
    )
    g4 = _write(
        tmp_path / "g4.csv",
        G4_HEADER
        + _g4_row(
            "STALE",
            "2015-06-12",
            100,
            "2015-01-01",
            "2015-01-02T12:00:00Z",
        )
        + _g4_row(
            "LATE",
            "2015-02-17",
            200,
            "2015-02-10",
            "2015-02-18T20:00:00Z",
        )
        + _g4_row(
            "FUTURE",
            "2015-02-19",
            300,
            "2015-02-10",
            "2015-02-17T12:00:00Z",
        ),
    )

    out = tmp_path / "out"
    summary = anchor_reuse.build(
        shares_gap_queue_path=gaps,
        canonical_g4_shares_path=g4,
        output_dir=out,
    )
    assert summary["cross_date_g4_anchor_reuse_count"] == 0
    assert summary["remaining_incremental_acquisition_count"] == 3


def test_latest_admissible_fact_date_is_selected(tmp_path: Path):
    gaps = _write(
        tmp_path / "gaps.csv",
        GAP_HEADER
        + _gap_row("AAA", "2015-02-18", "2015-02-18T19:18:00Z"),
    )
    g4 = _write(
        tmp_path / "g4.csv",
        G4_HEADER
        + _g4_row(
            "AAA",
            "2015-02-10",
            100,
            "2015-01-31",
            "2015-02-02T12:00:00Z",
            source="https://example.test/old",
        )
        + _g4_row(
            "AAA",
            "2015-02-17",
            120,
            "2015-02-15",
            "2015-02-16T12:00:00Z",
            source="https://example.test/new",
        ),
    )

    out = tmp_path / "out"
    summary = anchor_reuse.build(
        shares_gap_queue_path=gaps,
        canonical_g4_shares_path=g4,
        output_dir=out,
    )
    assert summary["cross_date_g4_anchor_reuse_count"] == 1
    reused = list(
        csv.DictReader(
            (out / "g5_control_shares_cross_date_g4_reuse.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert reused[0]["shares_outstanding"] == "120"
    assert reused[0]["fact_date"] == "2015-02-15"
    assert reused[0]["source_reference"] == "https://example.test/new"


def test_conflicting_latest_fact_values_fail_closed(tmp_path: Path):
    gaps = _write(
        tmp_path / "gaps.csv",
        GAP_HEADER
        + _gap_row("AAA", "2015-02-18", "2015-02-18T19:18:00Z"),
    )
    g4 = _write(
        tmp_path / "g4.csv",
        G4_HEADER
        + _g4_row(
            "AAA",
            "2015-02-16",
            100,
            "2015-02-10",
            "2015-02-11T12:00:00Z",
            source="https://example.test/a",
        )
        + _g4_row(
            "AAA",
            "2015-02-17",
            110,
            "2015-02-10",
            "2015-02-12T12:00:00Z",
            source="https://example.test/b",
        ),
    )

    with pytest.raises(
        anchor_reuse.G5ControlSharesAnchorReuseError,
        match="conflicting canonical G4 shares values",
    ):
        anchor_reuse.build(
            shares_gap_queue_path=gaps,
            canonical_g4_shares_path=g4,
            output_dir=tmp_path / "out",
        )


def test_real_g4_anchors_reduce_current_g5_incremental_shares_gap(tmp_path: Path):
    control_dir = tmp_path / "controls"
    history_dir = tmp_path / "history"
    reconciliation_dir = tmp_path / "reconciliation"
    reuse_dir = tmp_path / "anchor_reuse"
    frozen = ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"
    canonical_g4 = (
        ROOT
        / "data/processed/authorized_input_real/shares_outstanding_resolutions.csv"
    )

    acquisition.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=frozen,
        planning_universe_path=ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv",
        output_dir=control_dir,
    )
    history.build(
        candidate_path=control_dir / "g5_primary_candidate_symbol_dates.csv",
        output_dir=history_dir,
        frozen_requirements_path=frozen,
    )
    baseline = reconciliation.build(
        control_history_path=(
            history_dir / "g5_control_history_symbol_date_requirements.csv"
        ),
        canonical_g4_shares_path=canonical_g4,
        output_dir=reconciliation_dir,
    )
    summary = anchor_reuse.build(
        shares_gap_queue_path=(
            reconciliation_dir / "g5_control_shares_acquisition_queue.csv"
        ),
        canonical_g4_shares_path=canonical_g4,
        output_dir=reuse_dir,
    )

    assert summary["input_gap_count"] == (
        baseline["incremental_g5_shares_acquisition_count"]
    )
    assert summary["cross_date_g4_anchor_reuse_count"] > 0
    assert summary["remaining_incremental_acquisition_count"] < (
        baseline["incremental_g5_shares_acquisition_count"]
    )
    assert (
        summary["cross_date_g4_anchor_reuse_count"]
        + summary["remaining_incremental_acquisition_count"]
        == summary["input_gap_count"]
    )
    assert summary["policy"]["canonical_g4_coverage_unchanged"] is True
    assert summary["policy"]["canonical_g5_readiness_unchanged"] is True
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
