from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_treated_historical_cik_acquisition as cik


def test_real_queue_locks_current_treated_cik_gap(tmp_path: Path):
    summary = cik.build_queue(
        events_path=ROOT / "data/processed/historical_events.csv",
        historical_cik_map_path=ROOT / "data/public/metadata/g4_historical_cik_map.csv",
        output_dir=tmp_path,
    )
    assert summary["treated_event_count"] == 174
    assert summary["already_mapped_event_count"] == 119
    assert summary["missing_cik_event_count"] == 55
    assert summary["missing_cik_unique_symbol_count"] == 53
    assert summary["request_count"] == 53
    assert summary["canonical_g5_dates_resolved_change"] == 0

    rows = list(
        csv.DictReader(
            (tmp_path / "g5_treated_historical_cik_acquisition_queue.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert len(rows) == 53
    assert len({row["request_id"] for row in rows}) == 53
    assert all(row["status"] == "HISTORICAL_CIK_EVIDENCE_REQUIRED" for row in rows)


def test_queue_compresses_repeated_symbol_but_preserves_all_dates(tmp_path: Path):
    events = tmp_path / "events.csv"
    events.write_text(
        "historical_symbol,first_documented_illicit_trade_ts\n"
        "AAA,2013-01-01 10:00:00\n"
        "AAA,2015-02-02 11:00:00\n"
        "BBB,2014-03-03 12:00:00\n",
        encoding="utf-8",
    )
    mapping = tmp_path / "map.csv"
    mapping.write_text(
        "historical_symbol,cik\n"
        "BBB,0000000002\n",
        encoding="utf-8",
    )
    summary = cik.build_queue(
        events_path=events,
        historical_cik_map_path=mapping,
        output_dir=tmp_path / "out",
    )
    assert summary["missing_cik_event_count"] == 2
    assert summary["missing_cik_unique_symbol_count"] == 1
    rows = list(
        csv.DictReader(
            (tmp_path / "out/g5_treated_historical_cik_acquisition_queue.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert rows[0]["historical_symbol"] == "AAA"
    assert rows[0]["required_event_dates"] == "2013-01-01;2015-02-02"
    assert rows[0]["earliest_event_date"] == "2013-01-01"
    assert rows[0]["latest_event_date"] == "2015-02-02"


def test_reviewed_evidence_requires_interval_covering_every_event_date(tmp_path: Path):
    queue = tmp_path / "queue.csv"
    queue.write_text(
        "historical_symbol,required_event_dates\n"
        "AAA,2013-01-01;2015-02-02\n",
        encoding="utf-8",
    )
    reviewed = tmp_path / "reviewed.csv"
    reviewed.write_text(
        "historical_symbol,cik,valid_from,valid_through,source_reference,"
        "evidence_effective_at,review_status,research_use_only\n"
        "AAA,12345,2014-01-01,2016-01-01,SEC_ARCHIVE,2016-01-02T00:00:00Z,"
        "EXPLICIT_HISTORICAL_CIK_VERIFIED,1\n",
        encoding="utf-8",
    )
    try:
        cik.stage_reviewed(
            acquisition_queue_path=queue,
            reviewed_evidence_path=reviewed,
            output_path=tmp_path / "staged.csv",
        )
    except cik.G5HistoricalCikAcquisitionError as exc:
        assert "does not cover every required event date" in str(exc)
    else:
        raise AssertionError("expected interval coverage failure")


def test_current_ticker_style_unreviewed_mapping_cannot_stage(tmp_path: Path):
    queue = tmp_path / "queue.csv"
    queue.write_text(
        "historical_symbol,required_event_dates\n"
        "AAA,2015-02-02\n",
        encoding="utf-8",
    )
    reviewed = tmp_path / "reviewed.csv"
    reviewed.write_text(
        "historical_symbol,cik,valid_from,valid_through,source_reference,"
        "evidence_effective_at,review_status,research_use_only\n"
        "AAA,12345,2010-01-01,2020-01-01,CURRENT_TICKER_LOOKUP,"
        "2026-01-01T00:00:00Z,UNREVIEWED_CURRENT_MAPPING,1\n",
        encoding="utf-8",
    )
    try:
        cik.stage_reviewed(
            acquisition_queue_path=queue,
            reviewed_evidence_path=reviewed,
            output_path=tmp_path / "staged.csv",
        )
    except cik.G5HistoricalCikAcquisitionError as exc:
        assert "review_status is not closing-authorized" in str(exc)
    else:
        raise AssertionError("expected review-status failure")


def test_explicit_reviewed_historical_mapping_stages_cleanly(tmp_path: Path):
    queue = tmp_path / "queue.csv"
    queue.write_text(
        "historical_symbol,required_event_dates\n"
        "AAA,2013-01-01;2015-02-02\n",
        encoding="utf-8",
    )
    reviewed = tmp_path / "reviewed.csv"
    reviewed.write_text(
        "historical_symbol,cik,valid_from,valid_through,source_reference,"
        "evidence_effective_at,review_status,research_use_only\n"
        "AAA,12345,2010-01-01,2016-12-31,SEC_ARCHIVAL_FILINGS,"
        "2016-12-31T00:00:00Z,EXPLICIT_HISTORICAL_CIK_VERIFIED,1\n",
        encoding="utf-8",
    )
    out = tmp_path / "staged.csv"
    summary = cik.stage_reviewed(
        acquisition_queue_path=queue,
        reviewed_evidence_path=reviewed,
        output_path=out,
    )
    assert summary["staged_verified_symbol_count"] == 1
    assert summary["remaining_symbol_count"] == 0
    assert summary["canonical_g5_dates_resolved_change"] == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert rows[0]["historical_symbol"] == "AAA"
    assert rows[0]["cik"] == "0000012345"
