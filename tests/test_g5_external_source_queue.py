from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_external_source_queue as queue


def _candidates(tmp_path: Path) -> Path:
    p = tmp_path / "candidates.csv"
    p.write_text(
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc\n"
        "2015-02-17,C1,2015-02-17T19:19:00Z\n"
        "2015-02-17,C2,2015-02-17T19:19:00Z\n"
        "2015-02-18,C3,2015-02-18T19:00:00Z\n",
        encoding="utf-8",
    )
    return p


def test_external_queue_builds_four_lanes_per_candidate(tmp_path: Path):
    summary = queue.build(
        candidate_path=_candidates(tmp_path),
        output_dir=tmp_path / "out",
    )

    assert summary["candidate_symbol_date_count"] == 3
    assert summary["event_date_count"] == 2
    assert summary["lane_request_count"] == 12
    assert summary["external_field_requirement_count"] == 15
    assert summary["lane_counts"] == {
        "analyst": 3,
        "borrow": 3,
        "classification": 3,
        "ownership": 3,
    }
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["release_claimed"] is False


def test_request_ids_are_deterministic_and_unique(tmp_path: Path):
    out = tmp_path / "out"
    queue.build(candidate_path=_candidates(tmp_path), output_dir=out)
    rows = list(csv.DictReader((out / "g5_external_source_requests.csv").open(encoding="utf-8")))

    ids = [row["request_id"] for row in rows]
    assert len(ids) == len(set(ids)) == 12
    assert all(request_id.startswith("G5EXT-") for request_id in ids)

    first = rows[0]
    again = queue._request_id(
        first["lane"],
        first["event_date"],
        first["candidate_symbol"],
    )
    assert first["request_id"] == again


def test_lane_fields_and_source_routes_are_explicit(tmp_path: Path):
    out = tmp_path / "out"
    queue.build(candidate_path=_candidates(tmp_path), output_dir=out)
    rows = list(csv.DictReader((out / "g5_external_source_requests.csv").open(encoding="utf-8")))
    by_lane = {}
    for row in rows:
        by_lane.setdefault(row["lane"], row)

    assert by_lane["classification"]["required_fields"] == "sector;index_bucket"
    assert "SEC_SIC" in by_lane["classification"]["preferred_routes"]
    assert "INDEX_MEMBERSHIP" in by_lane["classification"]["preferred_routes"]

    assert by_lane["ownership"]["required_fields"] == "institutional_ownership"
    assert "13F" in by_lane["ownership"]["preferred_routes"]

    assert by_lane["analyst"]["required_fields"] == "analyst_coverage"
    assert "IBES" in by_lane["analyst"]["preferred_routes"]

    assert by_lane["borrow"]["required_fields"] == "borrow_cost"
    assert "MARKIT" in by_lane["borrow"]["preferred_routes"]

    assert all(row["eligible_g5_evidence"] == "0" for row in rows)
    assert all(row["research_use_only"] == "1" for row in rows)


def test_duplicate_candidate_is_rejected(tmp_path: Path):
    p = tmp_path / "dupe.csv"
    p.write_text(
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc\n"
        "2015-02-17,C1,2015-02-17T19:19:00Z\n"
        "2015-02-17,C1,2015-02-17T19:19:00Z\n",
        encoding="utf-8",
    )

    try:
        queue.build(candidate_path=p, output_dir=tmp_path / "out")
    except ValueError as exc:
        assert "duplicate candidate symbol-date" in str(exc)
    else:
        raise AssertionError("expected duplicate candidate rejection")
