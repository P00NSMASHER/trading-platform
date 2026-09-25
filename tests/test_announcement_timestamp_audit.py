import csv
import json
from pathlib import Path

from announcement_timestamp_audit import audit


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def fixture(tmp_path: Path):
    req = tmp_path / "requirements.csv"
    events = tmp_path / "events.csv"
    candidates = tmp_path / "candidates.csv"

    write_csv(req, [
        "event_id", "historical_symbol", "event_trade_date", "current_public_announcement_ts",
        "requirement", "acceptable_source", "status", "research_use_only",
    ], [{
        "event_id": "E1", "historical_symbol": "ABC", "event_trade_date": "2015-01-02",
        "current_public_announcement_ts": "", "requirement": "exact_point_in_time_public_release_timestamp",
        "acceptable_source": "x", "status": "missing", "research_use_only": "1",
    }])

    write_csv(events, [
        "event_id", "historical_symbol", "first_documented_illicit_trade_ts",
    ], [{
        "event_id": "E1", "historical_symbol": "ABC",
        "first_documented_illicit_trade_ts": "2015-01-02 15:30:00",
    }])

    return req, events, candidates


def test_ready_exact_timestamp(tmp_path):
    req, events, candidates = fixture(tmp_path)
    write_csv(candidates, [
        "event_id", "historical_symbol", "event_date", "public_announcement_ts",
        "timestamp_kind", "source_grade", "source_reference",
    ], [{
        "event_id": "E1", "historical_symbol": "ABC", "event_date": "2015-01-02",
        "public_announcement_ts": "2015-01-02T16:05:00-05:00",
        "timestamp_kind": "official_newswire_release", "source_grade": "A",
        "source_reference": "official-source",
    }])

    summary = audit(req, events, candidates, tmp_path / "out")
    assert summary["g1_candidate_ready"] is True
    assert summary["ready_events"] == 1


def test_proxy_or_naive_timestamp_is_not_ready(tmp_path):
    req, events, candidates = fixture(tmp_path)
    write_csv(candidates, [
        "event_id", "historical_symbol", "event_date", "public_announcement_ts",
        "timestamp_kind", "source_grade", "source_reference",
    ], [{
        "event_id": "E1", "historical_symbol": "ABC", "event_date": "2015-01-02",
        "public_announcement_ts": "2015-01-02T16:05:00",
        "timestamp_kind": "edgar_acceptance", "source_grade": "C",
        "source_reference": "proxy-only",
    }])

    summary = audit(req, events, candidates, tmp_path / "out")
    assert summary["g1_candidate_ready"] is False
    assert summary["missing_events"] == 1


def test_conflicting_exact_sources_block(tmp_path):
    req, events, candidates = fixture(tmp_path)
    rows = []
    for ts, ref in [
        ("2015-01-02T16:05:00-05:00", "source-a"),
        ("2015-01-02T16:07:00-05:00", "source-b"),
    ]:
        rows.append({
            "event_id": "E1", "historical_symbol": "ABC", "event_date": "2015-01-02",
            "public_announcement_ts": ts, "timestamp_kind": "official_newswire_release",
            "source_grade": "A", "source_reference": ref,
        })
    write_csv(candidates, [
        "event_id", "historical_symbol", "event_date", "public_announcement_ts",
        "timestamp_kind", "source_grade", "source_reference",
    ], rows)

    summary = audit(req, events, candidates, tmp_path / "out")
    assert summary["g1_candidate_ready"] is False
    assert summary["blocking_events"] == 1
