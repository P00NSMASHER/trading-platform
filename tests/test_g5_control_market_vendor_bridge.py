from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as acquisition
import g5_control_history_requirements as history
import g5_control_market_vendor_bridge as bridge


G5_HEADER = (
    "record_kind,trade_date,unique_symbol_count,historical_symbols,"
    "symbol_date_pair_count,frozen_g2_symbol_date_pair_count,"
    "additional_g5_symbol_date_pair_count,acquisition_scope,research_use_only\n"
)
FROZEN_HEADER = "record_kind,trade_date,historical_symbols\n"


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_incremental_pairs_route_into_existing_g2_vendor_lanes(tmp_path: Path):
    g5 = _write(
        tmp_path / "g5.csv",
        G5_HEADER
        + "equity_trade,2014-01-02,2,AAA;BBB,2,1,1,authorized_historical_market_data,1\n"
        + "equity_quote,2014-01-02,2,AAA;BBB,2,1,1,authorized_historical_market_data,1\n"
        + "option_trade,2011-06-01,2,AAA;BBB,2,1,1,authorized_historical_market_data,1\n"
        + "option_trade,2012-03-01,2,AAA;BBB,2,1,1,authorized_historical_market_data,1\n"
        + "option_trade,2014-01-02,2,AAA;BBB,2,1,1,authorized_historical_market_data,1\n"
        + "option_quote,2011-06-01,2,AAA;BBB,2,1,1,authorized_historical_market_data,1\n"
        + "option_quote,2012-07-02,2,AAA;BBB,2,1,1,authorized_historical_market_data,1\n",
    )
    frozen = _write(
        tmp_path / "frozen.csv",
        FROZEN_HEADER
        + "equity_trade,2014-01-02,AAA\n"
        + "equity_quote,2014-01-02,AAA\n"
        + "option_trade,2011-06-01,AAA\n"
        + "option_trade,2012-03-01,AAA\n"
        + "option_trade,2014-01-02,AAA\n"
        + "option_quote,2011-06-01,AAA\n"
        + "option_quote,2012-07-02,AAA\n",
    )

    summary = bridge.build(
        g5_source_requirements_path=g5,
        frozen_g2_requirements_path=frozen,
        output_dir=tmp_path / "out",
    )

    assert summary["expected_incremental_g5_pair_count"] == 7
    assert summary["incremental_g5_pair_count"] == 7
    assert summary["frozen_g2_overlap_pair_count"] == 7
    assert summary["incremental_pair_count_by_record_kind"] == {
        "equity_quote": 1,
        "equity_trade": 1,
        "option_quote": 2,
        "option_trade": 3,
    }
    assert summary["route_symbol_date_pair_counts"] == {
        "candidate_cboe_option_trades": 1,
        "candidate_databento_opra_trades": 1,
        "candidate_lseg_opra_tick_history": 1,
        "candidate_lseg_opra_tick_history_option_quotes": 1,
        "candidate_thetadata_options_pro_option_quotes": 1,
        "candidate_tickdata_equity_nbbo_quotes": 1,
        "candidate_tickdata_equity_trades": 1,
    }
    assert summary["policy"]["purchase_authorized"] is False
    assert summary["policy"]["data_fetch_performed"] is False
    assert summary["policy"]["candidate_route_is_not_market_coverage"] is True
    assert summary["policy"]["option_quotes_require_tick_nbbo_fidelity"] is True
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False


def test_incremental_overlap_count_mismatch_fails_closed(tmp_path: Path):
    g5 = _write(
        tmp_path / "g5.csv",
        G5_HEADER
        + "equity_trade,2014-01-02,2,AAA;BBB,2,0,2,authorized_historical_market_data,1\n",
    )
    frozen = _write(
        tmp_path / "frozen.csv",
        FROZEN_HEADER + "equity_trade,2014-01-02,AAA\n",
    )

    with pytest.raises(
        bridge.G5ControlMarketVendorBridgeError,
        match="frozen overlap mismatch",
    ):
        bridge.build(
            g5_source_requirements_path=g5,
            frozen_g2_requirements_path=frozen,
            output_dir=tmp_path / "out",
        )


def test_duplicate_symbols_and_duplicate_source_rows_fail_closed(tmp_path: Path):
    duplicated_symbol = _write(
        tmp_path / "dupe_symbol.csv",
        G5_HEADER
        + "equity_trade,2014-01-02,2,AAA;AAA,2,0,2,authorized_historical_market_data,1\n",
    )
    frozen = _write(tmp_path / "frozen.csv", FROZEN_HEADER)
    with pytest.raises(
        bridge.G5ControlMarketVendorBridgeError,
        match="contains duplicates",
    ):
        bridge.build(
            g5_source_requirements_path=duplicated_symbol,
            frozen_g2_requirements_path=frozen,
            output_dir=tmp_path / "out1",
        )

    duplicated_row = _write(
        tmp_path / "dupe_row.csv",
        G5_HEADER
        + "equity_trade,2014-01-02,1,BBB,1,0,1,authorized_historical_market_data,1\n"
        + "equity_trade,2014-01-02,1,CCC,1,0,1,authorized_historical_market_data,1\n",
    )
    with pytest.raises(
        bridge.G5ControlMarketVendorBridgeError,
        match="duplicate G5 source-date row",
    ):
        bridge.build(
            g5_source_requirements_path=duplicated_row,
            frozen_g2_requirements_path=frozen,
            output_dir=tmp_path / "out2",
        )


def test_real_incremental_market_bridge_exactly_matches_history_planner(tmp_path: Path):
    control_dir = tmp_path / "controls"
    history_dir = tmp_path / "history"
    bridge_dir = tmp_path / "bridge"
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
    summary = bridge.build(
        g5_source_requirements_path=(
            history_dir / "g5_control_history_source_date_requirements.csv"
        ),
        frozen_g2_requirements_path=frozen,
        output_dir=bridge_dir,
    )

    assert summary["incremental_pair_count_by_record_kind"] == (
        history_summary["additional_g5_market_pair_counts"]
    )
    assert summary["incremental_g5_pair_count"] == sum(
        history_summary["additional_g5_market_pair_counts"].values()
    )
    assert sum(summary["route_symbol_date_pair_counts"].values()) == (
        summary["incremental_g5_pair_count"]
    )
    assert summary["incremental_source_date_row_count"] > 0
    assert summary["distinct_incremental_historical_symbol_count"] > 0
    assert summary["policy"]["frozen_g2_pairs_are_removed_before_vendor_routing"] is True
    assert summary["policy"]["canonical_g2_coverage_unchanged"] is True
    assert summary["policy"]["canonical_g5_readiness_unchanged"] is True
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
