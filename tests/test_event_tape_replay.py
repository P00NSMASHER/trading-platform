from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from event_tape_replay import build_event_tape


def _write(path: Path, rows: list[dict]):
    fields = [
        "event_id","event_time_utc","available_at_utc","source_name",
        "source_sequence","event_type","payload_sha256","research_use_only",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _row(event_id: str, event_time: str, available: str, seq: int, source="S"):
    return {
        "event_id": event_id,
        "event_time_utc": event_time,
        "available_at_utc": available,
        "source_name": source,
        "source_sequence": str(seq),
        "event_type": "historical_observation",
        "payload_sha256": (event_id.lower()[0] if event_id[0].lower() in "abcdef" else "a") * 64,
        "research_use_only": "1",
    }


def test_event_tape_is_point_in_time_and_deterministic(tmp_path: Path):
    p = tmp_path / "events.csv"
    rows = [
        _row("E2","2020-01-01T10:00:00Z","2020-01-01T10:05:00Z",2),
        _row("E1","2020-01-01T10:01:00Z","2020-01-01T10:01:00Z",1),
        _row("E3","2020-01-01T09:55:00Z","2020-01-01T10:03:00Z",3),
    ]
    _write(p, rows)
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    m1 = build_event_tape(input_paths=[p], output_dir=out1, checkpoint_size=2)
    m2 = build_event_tape(input_paths=[p], output_dir=out2, checkpoint_size=2)
    got = list(csv.DictReader((out1 / "event_tape.csv").open()))
    assert [r["event_id"] for r in got] == ["E1","E3","E2"]
    assert got[-1]["replay_time_utc"] == "2020-01-01T10:05:00.000Z"
    assert m1["outputs"]["semantic_event_stream_sha256"] == m2["outputs"]["semantic_event_stream_sha256"]
    assert m1["architecture_origin"]["third_party_source_copied_or_vendored"] is False
    text = json.dumps(m1).lower()
    for bad in ["expected_return","target_price","position_size","trade_direction"]:
        assert bad in text  # present only in explicit prohibited_outputs


def test_as_of_defers_not_yet_available_event(tmp_path: Path):
    p = tmp_path / "events.csv"
    _write(p, [
        _row("E1","2020-01-01T10:00:00Z","2020-01-01T10:00:00Z",1),
        _row("E2","2020-01-01T10:00:00Z","2020-01-01T11:00:00Z",2),
    ])
    m = build_event_tape(
        input_paths=[p], output_dir=tmp_path/"out",
        as_of_utc="2020-01-01T10:30:00Z",
    )
    assert m["counts"]["replayed_events"] == 1
    assert m["counts"]["deferred_due_as_of"] == 1


def test_duplicate_event_id_fails_closed(tmp_path: Path):
    p = tmp_path / "events.csv"
    _write(p, [
        _row("E1","2020-01-01T10:00:00Z","2020-01-01T10:00:00Z",1),
        _row("E1","2020-01-01T10:01:00Z","2020-01-01T10:01:00Z",2),
    ])
    with pytest.raises(ValueError):
        build_event_tape(input_paths=[p], output_dir=tmp_path/"out")


def test_invalid_payload_hash_fails_closed(tmp_path: Path):
    p = tmp_path / "events.csv"
    r = _row("E1","2020-01-01T10:00:00Z","2020-01-01T10:00:00Z",1)
    r["payload_sha256"] = "not-a-hash"
    _write(p, [r])
    with pytest.raises(ValueError):
        build_event_tape(input_paths=[p], output_dir=tmp_path/"out")
