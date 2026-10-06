from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import real_data_replay as replay


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _g5_inputs(tmp_path: Path, *, missing_borrow: bool = False) -> dict:
    controls = _write_csv(
        tmp_path / "controls.csv",
        ["event_date", "candidate_symbol", "latest_acceptable_effective_ts_utc"],
        [
            {
                "event_date": "2015-02-17",
                "candidate_symbol": symbol,
                "latest_acceptable_effective_ts_utc": "2015-02-17T19:19:00Z",
            }
            for symbol in ("C1", "C2", "C3")
        ],
    )
    treated = _write_csv(
        tmp_path / "treated.csv",
        [
            "event_id",
            "event_date",
            "candidate_symbol",
            "latest_acceptable_effective_ts_utc",
        ],
        [
            {
                "event_id": "E1",
                "event_date": "2015-02-17",
                "candidate_symbol": "TRT",
                "latest_acceptable_effective_ts_utc": "2015-02-17T19:19:00Z",
            }
        ],
    )
    derived = _write_csv(
        tmp_path / "derived.csv",
        [
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
        ],
        [
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
            for i, symbol in enumerate(("TRT", "C1", "C2", "C3"), 1)
        ],
    )
    external_rows = [
        {
            "event_date": "2015-02-17",
            "symbol": symbol,
            "effective_ts_utc": "2015-02-17T18:00:00Z",
            "sector": "TECH",
            "index_bucket": "LARGE",
            "institutional_ownership": "0.6",
            "analyst_coverage": "10",
            "borrow_cost": "" if missing_borrow and symbol == "C1" else "0.01",
            "source_name": "external-reference",
            "authorization_reference": "AUTH-1",
            "research_use_only": "1",
        }
        for symbol in ("TRT", "C1", "C2", "C3")
    ]
    external = _write_csv(
        tmp_path / "external.csv",
        [
            "event_date",
            "symbol",
            "effective_ts_utc",
            "sector",
            "index_bucket",
            "institutional_ownership",
            "analyst_coverage",
            "borrow_cost",
            "source_name",
            "authorization_reference",
            "research_use_only",
        ],
        external_rows,
    )
    return {
        "control_targets": str(controls),
        "treated_targets": str(treated),
        "normalized_sources": [str(derived), str(external)],
        "minimum_controls_per_date": 3,
    }


def _config(tmp_path: Path, *, g5_spec: dict | None, control_metadata: str | None = None) -> Path:
    cfg = {
        "schema_version": "1",
        "events": str(ROOT / "data/processed/historical_events.csv"),
        "market_contract": str(ROOT / "config/historical_market_sources.example.json"),
        "metadata_contract": str(ROOT / "config/metadata_sources.public_progress.json"),
        "output_dir": str(tmp_path / "out"),
        "graph_db": str(
            ROOT
            / "data/processed/historical_graph_real/historical_cross_event_graph.sqlite"
        ),
    }
    if g5_spec is not None:
        cfg["g5_matching_metadata"] = g5_spec
    if control_metadata is not None:
        cfg["control_metadata"] = control_metadata
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def test_replay_materializes_ready_g5_matcher_metadata(tmp_path: Path):
    cfg = _config(tmp_path, g5_spec=_g5_inputs(tmp_path))
    result = replay.run_replay(cfg)

    stage = result["stages"]["g5_matching_metadata"]
    assert stage["status"] == "READY"
    assert stage["materialized_target_count"] == 4
    assert stage["gap_target_count"] == 0
    assert stage["control_dates_with_minimum_complete_metadata"] == 1
    assert stage["all_treated_metadata_complete"] is True

    metadata_input = result["inputs"]["control_metadata"]
    assert metadata_input is not None
    assert metadata_input["path"].endswith(
        "g5_matching_metadata/matcher_metadata.csv"
    )
    assert Path(metadata_input["path"]).exists()

    g5_inputs = result["inputs"]["g5_matching_metadata"]
    assert g5_inputs["minimum_controls_per_date"] == 3
    assert len(g5_inputs["normalized_sources"]) == 2
    assert result["ready_for_non_synthetic_offline_evaluation"] is False


def test_replay_keeps_incomplete_g5_materialization_blocked(tmp_path: Path):
    cfg = _config(
        tmp_path,
        g5_spec=_g5_inputs(tmp_path, missing_borrow=True),
    )
    result = replay.run_replay(cfg)

    stage = result["stages"]["g5_matching_metadata"]
    assert stage["status"] == "BLOCKED"
    assert stage["materialized_target_count"] == 3
    assert stage["gap_target_count"] == 1
    assert stage["control_dates_with_minimum_complete_metadata"] == 0
    assert result["inputs"]["control_metadata"] is None
    assert (
        tmp_path
        / "out"
        / "g5_matching_metadata"
        / "metadata_gaps.csv"
    ).exists()
    assert result["ready_for_non_synthetic_offline_evaluation"] is False


def test_replay_rejects_manual_and_generated_control_metadata_together(
    tmp_path: Path,
):
    manual = tmp_path / "manual.csv"
    manual.write_text("symbol,effective_ts_utc\n", encoding="utf-8")
    cfg = _config(
        tmp_path,
        g5_spec=_g5_inputs(tmp_path),
        control_metadata=str(manual),
    )

    with pytest.raises(
        ValueError,
        match="control_metadata and g5_matching_metadata are mutually exclusive",
    ):
        replay.run_replay(cfg)


def test_replay_rejects_empty_normalized_source_list(tmp_path: Path):
    spec = _g5_inputs(tmp_path)
    spec["normalized_sources"] = []
    cfg = _config(tmp_path, g5_spec=spec)

    with pytest.raises(
        ValueError,
        match="normalized_sources must be a non-empty list",
    ):
        replay.run_replay(cfg)
