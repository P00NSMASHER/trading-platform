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
    assert got[-1]["replay_time_utc"] == "2020-01-01T10:05:00.000000Z"
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


@pytest.mark.parametrize("controlling_clock", ["event_time_utc", "available_at_utc"])
@pytest.mark.parametrize("fraction,expected_count", [("000499", 1), ("000500", 1), ("000501", 0)])
def test_microsecond_cutoff_boundary(tmp_path: Path, controlling_clock, fraction, expected_count):
    p = tmp_path / "events.csv"
    row = _row("E1", "2015-01-29T20:00:00Z", "2015-01-29T20:00:00Z", 1)
    row[controlling_clock] = f"2015-01-29T20:00:00.{fraction}Z"
    _write(p, [row])
    out = tmp_path / "out"
    manifest = build_event_tape(
        input_paths=[p], output_dir=out, as_of_utc="2015-01-29T20:00:00.000500Z",
    )
    assert manifest["counts"]["replayed_events"] == expected_count
    assert manifest["counts"]["deferred_due_as_of"] == 1 - expected_count
    with (out / "event_tape.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == expected_count
    if rows:
        assert rows[0][controlling_clock] == row[controlling_clock]
        assert rows[0]["replay_time_utc"] == row[controlling_clock]


def test_manifest_preserves_exact_microsecond_cutoff(tmp_path: Path):
    p = tmp_path / "events.csv"
    _write(p, [_row("E1", "2015-01-29T20:00:00Z", "2015-01-29T20:00:00Z", 1)])
    out = tmp_path / "out"
    cutoff = "2015-01-29T20:00:00.000500Z"
    manifest = build_event_tape(input_paths=[p], output_dir=out, as_of_utc=cutoff)
    assert manifest["point_in_time_policy"]["as_of_utc"] == cutoff
    saved = json.loads((out / "event_tape_manifest.json").read_text(encoding="utf-8"))
    assert saved["point_in_time_policy"]["as_of_utc"] == cutoff
    assert saved["schema_version"] == "2.0.0"
    assert saved["timestamp_encoding"]["fractional_second_digits"] == 6
    assert saved["timestamp_encoding"]["precision_does_not_imply_accuracy"] is True


@pytest.mark.parametrize("same_availability", [False, True])
def test_microsecond_ordering_survives_reordering_and_partitioning(tmp_path: Path, same_availability):
    early = "2015-01-29T20:00:00.000100Z"
    late = "2015-01-29T20:00:00.000900Z"
    rows = [
        # Source and sequence tie-breakers deliberately favor the later event.
        _row("E2", late, late, 1, source="A"),
        _row("E1", early, late if same_availability else early, 9, source="Z"),
    ]
    p = tmp_path / "events.csv"
    _write(p, rows)
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    m1 = build_event_tape(input_paths=[p], output_dir=out1, checkpoint_size=1)
    parts = [tmp_path / "first.csv", tmp_path / "second.csv"]
    for part, row in zip(parts, reversed(rows)):
        _write(part, [row])
    m2 = build_event_tape(input_paths=parts, output_dir=out2, checkpoint_size=1)
    with (out1 / "event_tape.csv").open(newline="", encoding="utf-8") as f:
        got = list(csv.DictReader(f))
    assert [row["event_id"] for row in got] == ["E1", "E2"]
    assert got[0]["event_time_utc"] == early
    assert got[1]["event_time_utc"] == late
    assert m1["outputs"] == m2["outputs"]
    for name in ("event_tape.csv", "event_tape_checkpoints.json"):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()
    checkpoints = json.loads((out1 / "event_tape_checkpoints.json").read_text(encoding="utf-8"))
    assert checkpoints[0]["replay_time_utc"] == (late if same_availability else early)


@pytest.mark.parametrize("local_time", [
    "2015-03-20T00:30:00.123456+05:30",
    "2015-03-19T15:00:00.123456-04:00",
])
def test_timezone_equivalent_inputs_have_identical_semantic_outputs(tmp_path: Path, local_time):
    utc_time = "2015-03-19T19:00:00.123456Z"
    manifests = []
    for i, timestamp in enumerate((utc_time, local_time)):
        p = tmp_path / f"events{i}.csv"
        _write(p, [_row("E1", timestamp, timestamp, 1)])
        out = tmp_path / f"out{i}"
        manifests.append(build_event_tape(input_paths=[p], output_dir=out, as_of_utc=local_time))
        with (out / "event_tape.csv").open(newline="", encoding="utf-8") as f:
            row = next(csv.DictReader(f))
        assert row["replay_time_utc"] == utc_time
        assert manifests[-1]["point_in_time_policy"]["as_of_utc"] == utc_time
    assert manifests[0]["outputs"] == manifests[1]["outputs"]


@pytest.mark.parametrize("field", ["event_time_utc", "available_at_utc", "as_of_utc"])
@pytest.mark.parametrize("fraction", [".0000001", ".123456789", ",1234567", ".0000000"])
def test_unsupported_precision_is_rejected_before_writing(tmp_path: Path, field, fraction):
    p = tmp_path / "events.csv"
    row = _row("E1", "2015-01-29T20:00:00Z", "2015-01-29T20:00:00Z", 1)
    value = f"2015-01-29T20:00:00{fraction}Z"
    options = {}
    if field == "as_of_utc":
        options[field] = value
    else:
        row[field] = value
    _write(p, [row])
    out = tmp_path / "out"
    with pytest.raises(ValueError, match=f"{field}.*microsecond precision"):
        build_event_tape(input_paths=[p], output_dir=out, **options)
    assert not out.exists()


@pytest.mark.parametrize("field", ["event_time_utc", "available_at_utc", "as_of_utc"])
def test_fractional_utc_offsets_fail_closed(tmp_path: Path, field):
    p = tmp_path / "events.csv"
    row = _row("E1", "2015-01-29T20:00:00Z", "2015-01-29T20:00:00Z", 1)
    # Some datetime parsers normalize a sub-second zero-hour offset to UTC.
    # Reject it rather than risk silently shifting an instant at the cutoff.
    value = "2015-01-29T20:00:00+00:00:00.000001"
    options = {}
    if field == "as_of_utc":
        options[field] = value
    else:
        row[field] = value
    _write(p, [row])
    out = tmp_path / "out"
    with pytest.raises(ValueError, match=f"{field}.*fractional UTC offsets"):
        build_event_tape(input_paths=[p], output_dir=out, **options)
    assert not out.exists()


@pytest.mark.parametrize("field", ["event_time_utc", "available_at_utc"])
def test_semantic_hash_detects_submillisecond_timestamp_change(tmp_path: Path, field):
    manifests = []
    for i, fraction in enumerate(("000100", "000900")):
        p = tmp_path / f"events{i}.csv"
        row = _row("E1", "2015-01-29T20:00:00Z", "2015-01-29T20:00:00Z", 1)
        row[field] = f"2015-01-29T20:00:00.{fraction}Z"
        _write(p, [row])
        manifests.append(build_event_tape(input_paths=[p], output_dir=tmp_path / f"out{i}"))
    assert (manifests[0]["outputs"]["semantic_event_stream_sha256"]
            != manifests[1]["outputs"]["semantic_event_stream_sha256"])


@pytest.mark.parametrize("fraction,canonical", [
    ("", "000000"), (".1", "100000"), (".123", "123000"), (".123456", "123456"),
])
def test_supported_precision_round_trips_without_time_shift(tmp_path: Path, fraction, canonical):
    p = tmp_path / "events.csv"
    value = f"2015-01-29T20:00:00{fraction}Z"
    _write(p, [_row("E1", value, value, 1)])
    out = tmp_path / "out"
    manifest = build_event_tape(input_paths=[p], output_dir=out)
    with (out / "event_tape.csv").open(newline="", encoding="utf-8") as f:
        row = next(csv.DictReader(f))
    expected = f"2015-01-29T20:00:00.{canonical}Z"
    for field in ("event_time_utc", "available_at_utc", "replay_time_utc"):
        assert row[field] == expected
    assert manifest["point_in_time_policy"]["as_of_filter_applied"] is False
