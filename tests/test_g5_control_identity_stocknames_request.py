from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_identity_stocknames_request as request


HEADER = (
    "request_id,permno,historical_symbol,trade_date,hint_source,"
    "identity_status,research_use_only\n"
)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_groups_exact_dates_by_permno_and_symbol_without_promoting_identity(tmp_path: Path):
    queue = _write(
        tmp_path / "ready.csv",
        HEADER
        + "G5SID-A,11111,AAA,2015-01-02,CANONICAL_G2_PERMNO,"
        "OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,1\n"
        + "G5SID-B,11111,AAA,2015-01-05,SYMBOL_LEVEL_CANONICAL_PERMNO_ACQUISITION_LEAD,"
        "NEW_G5_IDENTITY_EVIDENCE_REQUIRED,1\n"
        + "G5SID-C,22222,BBB,2015-01-03,SYMBOL_LEVEL_SAMPLEFIRMS_PERMNO_ACQUISITION_LEAD,"
        "NEW_G5_IDENTITY_EVIDENCE_REQUIRED,1\n",
    )
    out = tmp_path / "out"
    summary = request.build(expanded_queue_path=queue, output_dir=out)

    assert summary["state"]["date_level_request_count"] == 3
    assert summary["state"]["grouped_permno_symbol_request_count"] == 2
    assert summary["state"]["unique_permno_count"] == 2
    assert summary["state"]["unique_historical_symbol_count"] == 2
    assert summary["state"]["first_required_date"] == "2015-01-02"
    assert summary["state"]["last_required_date"] == "2015-01-05"
    assert summary["data_fetch_performed"] is False
    assert summary["purchase_performed"] is False
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False
    assert summary["authorization_policy"]["permno_leads_are_identity_evidence"] is False

    rows = list(
        csv.DictReader(
            (out / "g5_control_identity_stocknames_request.csv").open(
                encoding="utf-8"
            )
        )
    )
    aaa = next(row for row in rows if row["historical_symbol"] == "AAA")
    assert aaa["request_count"] == "2"
    assert aaa["required_dates"] == "2015-01-02;2015-01-05"

    sql = (out / "g5_control_identity_stocknames_request.sql").read_text(
        encoding="utf-8"
    )
    assert "JOIN requested AS r" in sql
    assert "ON n.permno = r.permno" in sql
    assert "n.ticker =" not in sql
    assert "authentication" in sql.lower()
    assert "bypass" in sql.lower()


def test_same_symbol_with_multiple_permno_leads_fails_closed(tmp_path: Path):
    queue = _write(
        tmp_path / "collision.csv",
        HEADER
        + "G5SID-A,11111,AAA,2015-01-02,CANONICAL_G2_PERMNO,X,1\n"
        + "G5SID-B,22222,AAA,2015-01-03,SYMBOL_LEVEL_SAMPLEFIRMS_PERMNO_ACQUISITION_LEAD,X,1\n",
    )
    fields, rows = request._read_csv(queue)
    with pytest.raises(
        request.G5StocknamesRequestError,
        match="historical symbols map to multiple PERMNO acquisition leads",
    ):
        request.build_request_rows(fields, rows)


def test_duplicate_request_or_symbol_date_fails_closed(tmp_path: Path):
    duplicate_id = _write(
        tmp_path / "duplicate_id.csv",
        HEADER
        + "G5SID-A,11111,AAA,2015-01-02,CANONICAL_G2_PERMNO,X,1\n"
        + "G5SID-A,11111,AAA,2015-01-03,CANONICAL_G2_PERMNO,X,1\n",
    )
    fields, rows = request._read_csv(duplicate_id)
    with pytest.raises(request.G5StocknamesRequestError, match="request_id"):
        request.build_request_rows(fields, rows)

    duplicate_pair = _write(
        tmp_path / "duplicate_pair.csv",
        HEADER
        + "G5SID-A,11111,AAA,2015-01-02,CANONICAL_G2_PERMNO,X,1\n"
        + "G5SID-B,11111,AAA,2015-01-02,CANONICAL_G2_PERMNO,X,1\n",
    )
    fields, rows = request._read_csv(duplicate_pair)
    with pytest.raises(
        request.G5StocknamesRequestError,
        match="duplicate expanded Stocknames symbol-date",
    ):
        request.build_request_rows(fields, rows)


def test_invalid_permno_and_research_flag_fail_closed(tmp_path: Path):
    bad_permno = _write(
        tmp_path / "bad_permno.csv",
        HEADER
        + "G5SID-A,ABC,AAA,2015-01-02,CANONICAL_G2_PERMNO,X,1\n",
    )
    fields, rows = request._read_csv(bad_permno)
    with pytest.raises(request.G5StocknamesRequestError, match="PERMNO"):
        request.build_request_rows(fields, rows)

    bad_flag = _write(
        tmp_path / "bad_flag.csv",
        HEADER
        + "G5SID-A,11111,AAA,2015-01-02,CANONICAL_G2_PERMNO,X,0\n",
    )
    fields, rows = request._read_csv(bad_flag)
    with pytest.raises(request.G5StocknamesRequestError, match="research_use_only"):
        request.build_request_rows(fields, rows)


def _build_real(tmp_path: Path):
    import g5_control_acquisition_planner as acquisition
    import g5_control_history_requirements as history
    import g5_control_identity_interval_requests as intervals
    import g5_control_identity_requirements as identity
    import g5_control_identity_stocknames_lead_expansion as expansion

    control_dir = tmp_path / "controls"
    history_dir = tmp_path / "history"
    identity_dir = tmp_path / "identity"
    interval_dir = tmp_path / "interval"
    expanded_dir = tmp_path / "expanded"
    request_dir = tmp_path / "request"

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
    identity.build(
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
        identity_queue_path=identity_dir / "g5_control_identity_acquisition_queue.csv",
        output_dir=interval_dir,
    )
    expanded_summary = expansion.build(
        identity_queue_path=identity_dir / "g5_control_identity_acquisition_queue.csv",
        interval_requests_path=interval_dir / "g5_control_identity_interval_requests.csv",
        output_dir=expanded_dir,
    )
    request_summary = request.build(
        expanded_queue_path=(
            expanded_dir / "g5_control_identity_stocknames_expanded_ready_queue.csv"
        ),
        output_dir=request_dir,
    )
    return interval_summary, expanded_summary, request_summary, request_dir


def test_real_request_packet_reconciles_every_routable_g5_identity_date(tmp_path: Path):
    interval, expanded, summary, out = _build_real(tmp_path)

    assert summary["state"]["date_level_request_count"] == (
        expanded["expanded_stocknames_ready_request_count"]
    )
    assert summary["state"]["grouped_permno_symbol_request_count"] <= (
        interval["symbol_level_interval_request_count"]
    )
    assert summary["state"]["unique_historical_symbol_count"] <= (
        interval["symbol_level_interval_request_count"]
    )
    assert summary["state"]["unique_permno_count"] > 0
    assert summary["authorization_policy"][
        "exact_requested_date_and_historical_symbol_validation_required"
    ] is True
    assert summary["data_fetch_performed"] is False
    assert summary["purchase_performed"] is False
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False

    sql = (out / "g5_control_identity_stocknames_request.sql").read_text(
        encoding="utf-8"
    )
    assert "ON n.permno = r.permno" in sql
    assert "n.ticker =" not in sql
