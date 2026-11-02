"""Fail-closed public-research event replay cutoff regression tests.

All inputs are synthetic. This module never imports a broker or places orders.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from event_tape_replay import build_event_tape


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "events.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "event_id", "event_time_utc", "available_at_utc", "source_name",
            "source_sequence", "event_type", "payload_sha256", "research_use_only",
        ])
        writer.writeheader()
        for i, hour in enumerate(("10:00:00", "12:00:00"), 1):
            writer.writerow({
                "event_id": f"E{i}",
                "event_time_utc": f"2020-01-01T{hour}Z",
                "available_at_utc": f"2020-01-01T{hour}Z",
                "source_name": "synthetic",
                "source_sequence": str(i),
                "event_type": "historical_observation",
                "payload_sha256": "a" * 64,
                "research_use_only": "1",
            })
    return path


@pytest.mark.parametrize("cutoff", ["", "  ", False, 0, [], {}])
def test_explicit_invalid_cutoff_never_silently_disables_point_in_time_filter(tmp_path, cutoff):
    source = _source(tmp_path)
    out = tmp_path / "replay"
    with pytest.raises(ValueError, match="as_of_utc"):
        build_event_tape(input_paths=[source], output_dir=out, as_of_utc=cutoff)
    assert not out.exists(), "invalid cutoff must fail before any tape is written"


def test_omitted_cutoff_is_explicitly_unfiltered_and_valid_cutoff_purges_future_rows(tmp_path):
    source = _source(tmp_path)
    no_filter = build_event_tape(input_paths=[source], output_dir=tmp_path / "all", as_of_utc=None)
    assert no_filter["counts"]["replayed_events"] == 2
    assert no_filter["point_in_time_policy"]["as_of_filter_applied"] is False
    filtered = build_event_tape(
        input_paths=[source], output_dir=tmp_path / "asof",
        as_of_utc="2020-01-01T11:00:00Z",
    )
    assert filtered["counts"]["replayed_events"] == 1
    assert filtered["counts"]["deferred_due_as_of"] == 1
    assert filtered["point_in_time_policy"]["as_of_filter_applied"] is True


def test_invalid_asof_is_rejected_before_even_reading_input_paths(tmp_path):
    missing = tmp_path / "nonexistent.csv"
    with pytest.raises(ValueError, match="as_of_utc"):
        build_event_tape(input_paths=[missing], output_dir=tmp_path / "out", as_of_utc="")
