from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_acquisition_planner as acquisition
import g5_control_history_requirements as history
import g5_control_identity_requirements as identity
import g5_control_identity_interval_requests as intervals


def _build_real(tmp_path: Path):
    control_dir = tmp_path / "controls"
    history_dir = tmp_path / "history"
    identity_dir = tmp_path / "identity"
    interval_dir = tmp_path / "intervals"

    acquisition.build(
        events_path=ROOT / "data/processed/historical_events.csv",
        requirements_path=(
            ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"
        ),
        planning_universe_path=(
            ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv"
        ),
        output_dir=control_dir,
    )
    history.build(
        candidate_path=control_dir / "g5_primary_candidate_symbol_dates.csv",
        output_dir=history_dir,
        frozen_requirements_path=(
            ROOT / "data/processed/coverage_plan_real/source_date_requirements.csv"
        ),
    )
    identity_summary = identity.build(
        control_history_path=(
            history_dir / "g5_control_history_symbol_date_requirements.csv"
        ),
        primary_candidates_path=(
            control_dir / "g5_primary_candidate_symbol_dates.csv"
        ),
        samplefirms_path=(
            ROOT / "data/raw/hacked_earnings_jfe/SampleFirms.csv"
        ),
        canonical_g2_identity_manifest_path=(
            ROOT
            / "data/processed/security_identity_real/security_identity_manifest.json"
        ),
        output_dir=identity_dir,
    )
    interval_summary = intervals.build(
        identity_queue_path=(
            identity_dir / "g5_control_identity_acquisition_queue.csv"
        ),
        output_dir=interval_dir,
    )
    return identity_summary, interval_summary, interval_dir


def test_real_interval_requests_compress_identity_work_without_losing_dates(
    tmp_path: Path,
):
    identity_summary, summary, _out = _build_real(tmp_path)

    assert summary["date_level_identity_requirement_count"] == (
        identity_summary["identity_acquisition_queue_count"]
    )
    assert summary["required_date_count_reconciled"] == (
        summary["date_level_identity_requirement_count"]
    )
    assert summary["symbol_level_interval_request_count"] > 0
    assert summary["symbol_level_interval_request_count"] < (
        summary["date_level_identity_requirement_count"]
    )
    assert 0 < summary["request_compression_ratio"] < 1

    assert summary["symbols_with_canonical_permno_hint"] > 0
    assert summary["symbols_with_samplefirms_permno_hint"] > 0
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False


def test_every_date_level_requirement_appears_once_in_symbol_requests(tmp_path: Path):
    identity_summary, summary, out = _build_real(tmp_path)

    rows = list(
        csv.DictReader(
            (out / "g5_control_identity_interval_requests.csv").open(
                encoding="utf-8"
            )
        )
    )
    flattened = []
    for row in rows:
        dates = [x for x in row["required_dates"].split(";") if x]
        assert len(dates) == int(row["required_date_count"])
        assert dates == sorted(set(dates))
        assert row["first_required_date"] == dates[0]
        assert row["last_required_date"] == dates[-1]
        assert row["primary_lane"] == "LICENSED_STABLE_ID_MASTER"
        assert row["secondary_lane"] == "AUTHORIZED_MARKET_SECURITY_MASTER"
        assert row["research_use_only"] == "1"
        flattened.extend(
            (row["historical_symbol"], trade_date)
            for trade_date in dates
        )

    assert len(flattened) == identity_summary["identity_acquisition_queue_count"]
    assert len(flattened) == len(set(flattened))
    with Path(summary["inputs"]["identity_queue_path"]).open(
        encoding="utf-8", newline=""
    ) as handle:
        expected_pairs = {
            (row["historical_symbol"], row["trade_date"])
            for row in csv.DictReader(handle)
        }
    assert set(flattened) == expected_pairs
    assert summary["policy"]["continuous_validity_not_assumed"] is True
    assert summary["policy"]["request_rows_are_g5_evidence"] is False
