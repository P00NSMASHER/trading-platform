from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_staged_readiness_preview as preview
from metadata_resolver import CONTROL_COVARIATES


def _candidates(tmp_path: Path) -> Path:
    p = tmp_path / "candidates.csv"
    p.write_text(
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc\n"
        "2015-02-17,C1,2015-02-17T19:19:00Z\n"
        "2015-02-17,C2,2015-02-17T19:19:00Z\n"
        "2015-02-17,C3,2015-02-17T19:19:00Z\n",
        encoding="utf-8",
    )
    return p


def _derived(tmp_path: Path) -> Path:
    p = tmp_path / "derived.csv"
    fields = [
        "event_date",
        "symbol",
        "effective_ts_utc",
        "market_cap",
        "price",
        "trailing_21d_vol",
        "normal_minute_volume",
        "normal_minute_turnover",
        "normal_relative_spread",
        "option_liquidity",
        "pre_event_return",
        "source_name",
        "research_use_only",
    ]
    with p.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for i, symbol in enumerate(("C1", "C2", "C3"), 1):
            writer.writerow(
                {
                    "event_date": "2015-02-17",
                    "symbol": symbol,
                    "effective_ts_utc": "2015-02-17T19:18:00Z",
                    "market_cap": str(1_000_000_000 + i),
                    "price": str(20 + i),
                    "trailing_21d_vol": "0.02",
                    "normal_minute_volume": "100000",
                    "normal_minute_turnover": "0.001",
                    "normal_relative_spread": "0.0008",
                    "option_liquidity": "500",
                    "pre_event_return": "0.002",
                    "source_name": "derived-market",
                    "research_use_only": "1",
                }
            )
    return p


def _external(tmp_path: Path) -> Path:
    p = tmp_path / "external.csv"
    fields = [
        "event_date",
        "symbol",
        "effective_ts_utc",
        "sector",
        "index_bucket",
        "institutional_ownership",
        "analyst_coverage",
        "borrow_cost",
        "source_name",
        "research_use_only",
    ]
    with p.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for symbol in ("C1", "C2", "C3"):
            writer.writerow(
                {
                    "event_date": "2015-02-17",
                    "symbol": symbol,
                    "effective_ts_utc": "2015-02-17T18:00:00Z",
                    "sector": "Tech",
                    "index_bucket": "SP500",
                    "institutional_ownership": "0.6",
                    "analyst_coverage": "10",
                    "borrow_cost": "0.01",
                    "source_name": "external-reference",
                    "research_use_only": "1",
                }
            )
    return p


def test_split_staged_sources_preview_three_complete_candidates(tmp_path: Path):
    output = tmp_path / "preview.csv"
    summary_path = tmp_path / "summary.json"
    summary = preview.build_preview(
        candidate_path=_candidates(tmp_path),
        source_paths=[_derived(tmp_path), _external(tmp_path)],
        output_path=output,
        summary_path=summary_path,
    )

    assert summary["candidate_symbol_date_count"] == 3
    assert summary["complete_candidate_symbol_date_count"] == 3
    assert summary["staged_ready_event_date_count"] == 1
    assert summary["staged_ready_event_dates"] == ["2015-02-17"]
    assert summary["missing_field_counts"] == {}
    assert summary["conflict_field_counts"] == {}
    assert summary["required_fields"] == list(CONTROL_COVARIATES)
    assert summary["preview_all_dates_complete"] is True
    assert summary["canonical_g5_readiness_changed"] is False
    assert summary["canonical_g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False

    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert len(rows) == 3
    assert all(row["candidate_complete"] == "1" for row in rows)
    assert all(row["complete_field_count"] == str(len(CONTROL_COVARIATES)) for row in rows)
    assert all(row["preview_only"] == "1" for row in rows)


def test_missing_external_field_keeps_date_not_ready(tmp_path: Path):
    external = _external(tmp_path)
    rows = list(csv.DictReader(external.open(encoding="utf-8")))
    rows[0]["borrow_cost"] = ""
    with external.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = preview.build_preview(
        candidate_path=_candidates(tmp_path),
        source_paths=[_derived(tmp_path), external],
        output_path=tmp_path / "preview.csv",
        summary_path=tmp_path / "summary.json",
    )

    assert summary["complete_candidate_symbol_date_count"] == 2
    assert summary["staged_ready_event_date_count"] == 0
    assert summary["missing_field_counts"]["borrow_cost"] == 1


def test_equal_timestamp_conflict_fails_candidate_closed(tmp_path: Path):
    conflict = tmp_path / "conflict.csv"
    conflict.write_text(
        "event_date,symbol,effective_ts_utc,borrow_cost,source_name\n"
        "2015-02-17,C1,2015-02-17T18:00:00Z,0.99,conflict-source\n",
        encoding="utf-8",
    )

    summary = preview.build_preview(
        candidate_path=_candidates(tmp_path),
        source_paths=[_derived(tmp_path), _external(tmp_path), conflict],
        output_path=tmp_path / "preview.csv",
        summary_path=tmp_path / "summary.json",
    )

    assert summary["complete_candidate_symbol_date_count"] == 2
    assert summary["staged_ready_event_date_count"] == 0
    assert summary["conflict_field_counts"]["borrow_cost"] == 1


def test_unknown_candidate_row_is_rejected(tmp_path: Path):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "event_date,symbol,effective_ts_utc,sector,source_name\n"
        "2015-02-17,NOTQUEUED,2015-02-17T18:00:00Z,Tech,bad\n",
        encoding="utf-8",
    )

    with pytest.raises(preview.G5StagedPreviewError, match="unknown candidate"):
        preview.build_preview(
            candidate_path=_candidates(tmp_path),
            source_paths=[bad],
            output_path=tmp_path / "preview.csv",
            summary_path=tmp_path / "summary.json",
        )


def test_after_cutoff_source_row_is_rejected(tmp_path: Path):
    late = tmp_path / "late.csv"
    late.write_text(
        "event_date,symbol,effective_ts_utc,sector,source_name\n"
        "2015-02-17,C1,2015-02-17T20:00:00Z,Tech,late\n",
        encoding="utf-8",
    )

    with pytest.raises(preview.G5StagedPreviewError, match="exceeds candidate cutoff"):
        preview.build_preview(
            candidate_path=_candidates(tmp_path),
            source_paths=[late],
            output_path=tmp_path / "preview.csv",
            summary_path=tmp_path / "summary.json",
        )
