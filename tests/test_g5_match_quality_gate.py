from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_match_quality_gate as gate


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _fixture(tmp_path: Path) -> dict[str, Path]:
    events = [
        {
            "event_id": "E1",
            "historical_symbol": "TRT",
            "first_documented_illicit_trade_ts": "2026-01-05 14:30:00",
            "research_use_only": "1",
        },
        {
            "event_id": "E2",
            "historical_symbol": "POS",
            "first_documented_illicit_trade_ts": "2026-01-05 15:00:00",
            "research_use_only": "1",
        },
    ]
    events_path = _write_csv(
        tmp_path / "events.csv",
        list(events[0]),
        events,
    )

    match_events = [
        {
            "event_id": "E1",
            "treated_symbol": "TRT",
            "treated_minute_ts_utc": "2026-01-05T19:30:00.000Z",
            "local_date": "2026-01-05",
            "local_minute": "14:30",
            "candidate_pool_size": "5",
            "matched_control_count": "3",
            "event_status": "matched",
            "mean_match_distance": "0.4",
            "max_match_distance": "0.7",
            "max_component_z": "1.2",
            "research_use_only": "1",
        },
        {
            "event_id": "E2",
            "treated_symbol": "POS",
            "treated_minute_ts_utc": "2026-01-05T20:00:00.000Z",
            "local_date": "2026-01-05",
            "local_minute": "15:00",
            "candidate_pool_size": "5",
            "matched_control_count": "3",
            "event_status": "matched",
            "mean_match_distance": "0.5",
            "max_match_distance": "0.8",
            "max_component_z": "1.3",
            "research_use_only": "1",
        },
    ]
    match_events_path = _write_csv(
        tmp_path / "match_events.csv",
        list(match_events[0]),
        match_events,
    )

    control_fields = [
        "match_id",
        "event_id",
        "treated_symbol",
        "treated_minute_ts_utc",
        "control_rank",
        "control_symbol",
        "control_minute_ts_utc",
        "local_date",
        "local_minute",
        "same_sector",
        "scheduled_event_match",
        "candidate_pool_size",
        "numeric_covariates_used",
        "match_distance",
        "max_component_z",
        "match_quality",
        "treated_feature_status",
        "control_feature_status",
        "metadata_source_names",
        "research_use_only",
    ]
    controls = []
    for event_id, treated, minute, symbols in [
        ("E1", "TRT", "14:30", ["A", "B", "C"]),
        ("E2", "POS", "15:00", ["D", "E", "F"]),
    ]:
        hour = "19" if minute == "14:30" else "20"
        mm = minute.split(":")[1]
        for rank, symbol in enumerate(symbols, 1):
            controls.append(
                {
                    "match_id": f"M-{event_id}-{rank}",
                    "event_id": event_id,
                    "treated_symbol": treated,
                    "treated_minute_ts_utc": f"2026-01-05T{hour}:{mm}:00.000Z",
                    "control_rank": str(rank),
                    "control_symbol": symbol,
                    "control_minute_ts_utc": f"2026-01-05T{hour}:{mm}:00.000Z",
                    "local_date": "2026-01-05",
                    "local_minute": minute,
                    "same_sector": "1",
                    "scheduled_event_match": "1",
                    "candidate_pool_size": "5",
                    "numeric_covariates_used": "2",
                    "match_distance": "0.5",
                    "max_component_z": "1.1",
                    "match_quality": "good",
                    "treated_feature_status": "full",
                    "control_feature_status": "full",
                    "metadata_source_names": "fixture",
                    "research_use_only": "1",
                }
            )
    matched_controls_path = _write_csv(
        tmp_path / "matched_controls.csv",
        control_fields,
        controls,
    )

    balance_fields = [
        "covariate",
        "treated_n",
        "candidate_n",
        "matched_n",
        "treated_mean_transformed",
        "candidate_mean_transformed",
        "matched_mean_transformed",
        "smd_before",
        "smd_after",
        "preferred_abs_smd_max",
        "maximum_abs_smd",
        "research_use_only",
    ]
    balance = [
        {
            "covariate": covariate,
            "treated_n": "2",
            "candidate_n": "10",
            "matched_n": "6",
            "treated_mean_transformed": "1",
            "candidate_mean_transformed": "1.1",
            "matched_mean_transformed": "1.02",
            "smd_before": "0.15",
            "smd_after": smd,
            "preferred_abs_smd_max": "0.1",
            "maximum_abs_smd": "0.2",
            "research_use_only": "1",
        }
        for covariate, smd in [("market_cap", "0.05"), ("price", "-0.08")]
    ]
    match_balance_path = _write_csv(
        tmp_path / "match_balance.csv",
        balance_fields,
        balance,
    )

    manifest = {
        "schema_version": "0.5.0",
        "matching_policy": {
            "controls_per_event": 3,
            "minimum_controls": 3,
            "known_positive_event_controls_excluded": True,
            "max_standardized_component_distance": 2.5,
            "numeric_covariates": ["market_cap", "price"],
        },
        "outputs": {
            "event_count": 2,
            "matched_control_rows": 6,
            "event_status_counts": {"matched": 2},
            "balance_rows": 2,
        },
        "balance_policy": {
            "preferred_abs_smd_max": 0.1,
            "maximum_abs_smd": 0.2,
        },
    }
    match_manifest_path = tmp_path / "match_manifest.json"
    match_manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "events": events_path,
        "controls": matched_controls_path,
        "match_events": match_events_path,
        "balance": match_balance_path,
        "manifest": match_manifest_path,
    }


def _run(tmp_path: Path, paths: dict[str, Path]):
    return gate.build(
        historical_events_path=paths["events"],
        matched_controls_path=paths["controls"],
        match_events_path=paths["match_events"],
        match_balance_path=paths["balance"],
        match_manifest_path=paths["manifest"],
        output_path=tmp_path / "gate.json",
    )


def _mutate_csv(path: Path, mutator) -> None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    mutator(rows)
    _write_csv(path, fields, rows)


def test_complete_balanced_match_set_passes(tmp_path: Path):
    paths = _fixture(tmp_path)
    result = _run(tmp_path, paths)

    assert result["ready_for_g5_model_evaluation"] is True
    assert result["event_count"] == 2
    assert result["matched_control_row_count"] == 6
    assert result["numeric_covariates"] == ["market_cap", "price"]
    assert result["hard_balance_violation_count"] == 0
    assert result["known_positive_control_violation_count"] == 0
    assert result["canonical_g5_readiness_modified"] is False
    assert result["release_claimed"] is False


def test_hard_smd_violation_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    _mutate_csv(
        paths["balance"],
        lambda rows: rows[0].update({"smd_after": "0.2001"}),
    )
    with pytest.raises(
        gate.G5MatchQualityGateError,
        match="post-match balance exceeds hard SMD limit",
    ):
        _run(tmp_path, paths)


def test_same_day_known_positive_control_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    _mutate_csv(
        paths["controls"],
        lambda rows: rows[0].update({"control_symbol": "POS"}),
    )
    with pytest.raises(
        gate.G5MatchQualityGateError,
        match="known positive POS used as control",
    ):
        _run(tmp_path, paths)


def test_incomplete_numeric_distance_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    _mutate_csv(
        paths["controls"],
        lambda rows: rows[0].update({"numeric_covariates_used": "1"}),
    )
    with pytest.raises(
        gate.G5MatchQualityGateError,
        match="incomplete numeric covariate distance",
    ):
        _run(tmp_path, paths)


def test_duplicate_rank_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)

    def mutate(rows):
        rows[1]["control_rank"] = "1"

    _mutate_csv(paths["controls"], mutate)
    with pytest.raises(
        gate.G5MatchQualityGateError,
        match="control ranks are not exactly",
    ):
        _run(tmp_path, paths)


def test_unmatched_event_fails_closed(tmp_path: Path):
    paths = _fixture(tmp_path)
    _mutate_csv(
        paths["match_events"],
        lambda rows: rows[0].update(
            {"event_status": "insufficient_controls", "matched_control_count": "0"}
        ),
    )
    with pytest.raises(
        gate.G5MatchQualityGateError,
        match="is not fully matched",
    ):
        _run(tmp_path, paths)
