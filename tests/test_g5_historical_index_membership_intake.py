from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_external_metadata_adapter as adapter
import g5_historical_index_membership_intake as membership


def _targets(tmp_path: Path) -> Path:
    path = tmp_path / "targets.csv"
    path.write_text(
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc,research_use_only\n"
        "2015-02-17,AAA,2015-02-17T18:00:00Z,1\n",
        encoding="utf-8",
    )
    return path


def test_membership_interval_materializes_canonical_index_bucket(tmp_path: Path):
    targets = _targets(tmp_path)
    source = tmp_path / "membership.csv"
    source.write_text(
        "historical_symbol,index_bucket,valid_from,valid_through,"
        "evidence_effective_at,source_reference,authorization_reference,"
        "research_use_only\n"
        "AAA,SP500,2014-01-01,2016-01-01,2014-01-02T00:00:00Z,"
        "PRIMARY_SOURCE,AUTHORIZED,1\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    summary = membership.build(
        targets_path=targets,
        membership_intervals_path=source,
        output_path=out,
    )
    assert summary["resolved_index_bucket_count"] == 1
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert rows[0]["index_bucket"] == "SP500"

    normalized, receipt = adapter.normalize(
        lane="classification",
        candidate_path=targets,
        source_path=out,
        expected_source_sha256=membership._sha256(out),
        authorization_reference="AUTHORIZED",
        source_name="POINT_IN_TIME_INDEX_MEMBERSHIP",
    )
    assert normalized[0]["index_bucket"] == "SP500"
    assert normalized[0]["sector"] == ""
    assert receipt["accepted_field_counts"] == {"index_bucket": 1}


def test_post_cutoff_evidence_cannot_resolve_membership(tmp_path: Path):
    targets = _targets(tmp_path)
    source = tmp_path / "membership.csv"
    source.write_text(
        "historical_symbol,index_bucket,valid_from,valid_through,"
        "evidence_effective_at,source_reference,authorization_reference,"
        "research_use_only\n"
        "AAA,SP500,2014-01-01,2016-01-01,2015-02-17T19:00:00Z,"
        "LATE_SOURCE,AUTHORIZED,1\n",
        encoding="utf-8",
    )
    summary = membership.build(
        targets_path=targets,
        membership_intervals_path=source,
        output_path=tmp_path / "out.csv",
    )
    assert summary["resolved_index_bucket_count"] == 0
    assert summary["gap_count"] == 1


def test_conflicting_overlapping_memberships_fail_closed(tmp_path: Path):
    targets = _targets(tmp_path)
    source = tmp_path / "membership.csv"
    source.write_text(
        "historical_symbol,index_bucket,valid_from,valid_through,"
        "evidence_effective_at,source_reference,authorization_reference,"
        "research_use_only\n"
        "AAA,SP500,2014-01-01,2016-01-01,2014-01-02T00:00:00Z,S1,A,1\n"
        "AAA,SP400,2014-01-01,2016-01-01,2014-01-03T00:00:00Z,S2,A,1\n",
        encoding="utf-8",
    )
    try:
        membership.build(
            targets_path=targets,
            membership_intervals_path=source,
            output_path=tmp_path / "out.csv",
        )
    except membership.G5IndexMembershipError as exc:
        assert "conflicting index buckets" in str(exc)
    else:
        raise AssertionError("expected membership conflict")


def test_unknown_bucket_is_rejected(tmp_path: Path):
    source = tmp_path / "membership.csv"
    source.write_text(
        "historical_symbol,index_bucket,valid_from,valid_through,"
        "evidence_effective_at,source_reference,authorization_reference,"
        "research_use_only\n"
        "AAA,RUSSELL2000,2014-01-01,2016-01-01,2014-01-02T00:00:00Z,S,A,1\n",
        encoding="utf-8",
    )
    try:
        membership.build(
            targets_path=_targets(tmp_path),
            membership_intervals_path=source,
            output_path=tmp_path / "out.csv",
        )
    except membership.G5IndexMembershipError as exc:
        assert "unsupported bucket" in str(exc)
    else:
        raise AssertionError("expected unsupported bucket failure")
