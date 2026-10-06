from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_matching_metadata_materializer as materializer
from matched_control_generator import DEFAULT_NUMERIC_COVARIATES, load_metadata
from metadata_resolver import CONTROL_COVARIATES


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _targets(tmp_path: Path) -> tuple[Path, Path]:
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
    return controls, treated


def _derived(tmp_path: Path) -> Path:
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
    rows = []
    for i, symbol in enumerate(("TRT", "C1", "C2", "C3"), 1):
        rows.append(
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
    return _write_csv(tmp_path / "derived.csv", fields, rows)


def _external(tmp_path: Path) -> Path:
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
        "authorization_reference",
        "research_use_only",
    ]
    rows = [
        {
            "event_date": "2015-02-17",
            "symbol": symbol,
            "effective_ts_utc": "2015-02-17T18:00:00Z",
            "sector": "TECH",
            "index_bucket": "LARGE",
            "institutional_ownership": "0.6",
            "analyst_coverage": "10",
            "borrow_cost": "0.01",
            "source_name": "external-reference",
            "authorization_reference": "AUTH-1",
            "research_use_only": "1",
        }
        for symbol in ("TRT", "C1", "C2", "C3")
    ]
    return _write_csv(tmp_path / "external.csv", fields, rows)


def _build(tmp_path: Path, sources: list[Path] | None = None):
    controls, treated = _targets(tmp_path)
    return materializer.build(
        control_targets_path=controls,
        treated_targets_path=treated,
        source_paths=sources or [_derived(tmp_path), _external(tmp_path)],
        output_path=tmp_path / "matcher_metadata.csv",
        gap_path=tmp_path / "metadata_gaps.csv",
        summary_path=tmp_path / "summary.json",
    )


def test_complete_sources_materialize_exact_matcher_input(tmp_path: Path):
    summary = _build(tmp_path)

    assert summary["control_target_count"] == 3
    assert summary["treated_target_count"] == 1
    assert summary["total_target_count"] == 4
    assert summary["materialized_target_count"] == 4
    assert summary["gap_target_count"] == 0
    assert summary["control_dates_with_minimum_complete_metadata"] == 1
    assert summary["all_treated_metadata_complete"] is True
    assert summary["matcher_input_ready"] is True
    assert summary["required_covariates"] == list(CONTROL_COVARIATES)
    assert summary["release_claimed"] is False

    rows = list(
        csv.DictReader((tmp_path / "matcher_metadata.csv").open(encoding="utf-8"))
    )
    assert len(rows) == 4
    assert {row["target_kind"] for row in rows} == {"control", "treated"}
    assert {row["effective_ts_utc"] for row in rows} == {"2015-02-17T19:18:00Z"}
    assert all(
        row["source_name"] == "derived-market;external-reference" for row in rows
    )
    assert all(row["research_use_only"] == "1" for row in rows)

    loaded = load_metadata(
        tmp_path / "matcher_metadata.csv",
        tuple(DEFAULT_NUMERIC_COVARIATES),
    )
    assert set(loaded) == {"TRT", "C1", "C2", "C3"}


def test_missing_field_omits_target_and_keeps_date_fail_closed(tmp_path: Path):
    derived = _derived(tmp_path)
    external = _external(tmp_path)
    rows = list(csv.DictReader(external.open(encoding="utf-8")))
    c1 = next(row for row in rows if row["symbol"] == "C1")
    c1["borrow_cost"] = ""
    _write_csv(external, list(rows[0]), rows)

    summary = _build(tmp_path, [derived, external])

    assert summary["materialized_control_count"] == 2
    assert summary["materialized_treated_count"] == 1
    assert summary["gap_target_count"] == 1
    assert summary["control_dates_with_minimum_complete_metadata"] == 0
    assert summary["missing_field_counts"]["borrow_cost"] == 1
    assert summary["matcher_input_ready"] is False

    gaps = list(
        csv.DictReader((tmp_path / "metadata_gaps.csv").open(encoding="utf-8"))
    )
    assert len(gaps) == 1
    assert gaps[0]["symbol"] == "C1"
    assert gaps[0]["missing_fields"] == "borrow_cost"


def test_equal_timestamp_conflict_omits_target(tmp_path: Path):
    derived = _derived(tmp_path)
    external = _external(tmp_path)
    conflict = _write_csv(
        tmp_path / "conflict.csv",
        [
            "event_date",
            "symbol",
            "effective_ts_utc",
            "borrow_cost",
            "source_name",
            "research_use_only",
        ],
        [
            {
                "event_date": "2015-02-17",
                "symbol": "C1",
                "effective_ts_utc": "2015-02-17T18:00:00Z",
                "borrow_cost": "0.99",
                "source_name": "conflict-source",
                "research_use_only": "1",
            }
        ],
    )

    summary = _build(tmp_path, [derived, external, conflict])

    assert summary["materialized_control_count"] == 2
    assert summary["conflict_field_counts"]["borrow_cost"] == 1
    assert summary["matcher_input_ready"] is False
    gap = next(
        row
        for row in csv.DictReader(
            (tmp_path / "metadata_gaps.csv").open(encoding="utf-8")
        )
        if row["symbol"] == "C1"
    )
    assert gap["conflicted_fields"] == "borrow_cost"


def test_later_admissible_value_resolves_earlier_value(tmp_path: Path):
    derived = _derived(tmp_path)
    external = _external(tmp_path)
    later = _write_csv(
        tmp_path / "later.csv",
        [
            "event_date",
            "symbol",
            "effective_ts_utc",
            "borrow_cost",
            "source_name",
            "research_use_only",
        ],
        [
            {
                "event_date": "2015-02-17",
                "symbol": "C1",
                "effective_ts_utc": "2015-02-17T18:30:00Z",
                "borrow_cost": "0.02",
                "source_name": "later-source",
                "research_use_only": "1",
            }
        ],
    )

    summary = _build(tmp_path, [derived, external, later])
    assert summary["matcher_input_ready"] is True
    c1 = next(
        row
        for row in csv.DictReader(
            (tmp_path / "matcher_metadata.csv").open(encoding="utf-8")
        )
        if row["symbol"] == "C1"
    )
    assert c1["borrow_cost"] == "0.02"
    assert c1["effective_ts_utc"] == "2015-02-17T19:18:00Z"


def test_unknown_target_and_after_cutoff_rows_are_rejected(tmp_path: Path):
    controls, treated = _targets(tmp_path)
    unknown = _write_csv(
        tmp_path / "unknown.csv",
        [
            "event_date",
            "symbol",
            "effective_ts_utc",
            "sector",
            "source_name",
            "research_use_only",
        ],
        [
            {
                "event_date": "2015-02-17",
                "symbol": "NOPE",
                "effective_ts_utc": "2015-02-17T18:00:00Z",
                "sector": "TECH",
                "source_name": "bad",
                "research_use_only": "1",
            }
        ],
    )
    with pytest.raises(
        materializer.G5MatchingMetadataMaterializationError,
        match="unknown target",
    ):
        materializer.build(
            control_targets_path=controls,
            treated_targets_path=treated,
            source_paths=[unknown],
            output_path=tmp_path / "m.csv",
            gap_path=tmp_path / "g.csv",
            summary_path=tmp_path / "s.json",
        )

    late = _write_csv(
        tmp_path / "late.csv",
        [
            "event_date",
            "symbol",
            "effective_ts_utc",
            "sector",
            "source_name",
            "research_use_only",
        ],
        [
            {
                "event_date": "2015-02-17",
                "symbol": "C1",
                "effective_ts_utc": "2015-02-17T20:00:00Z",
                "sector": "TECH",
                "source_name": "late",
                "research_use_only": "1",
            }
        ],
    )
    with pytest.raises(
        materializer.G5MatchingMetadataMaterializationError,
        match="timestamp exceeds target cutoff",
    ):
        materializer.build(
            control_targets_path=controls,
            treated_targets_path=treated,
            source_paths=[late],
            output_path=tmp_path / "m.csv",
            gap_path=tmp_path / "g.csv",
            summary_path=tmp_path / "s.json",
        )


def test_treated_control_symbol_date_collision_is_rejected(tmp_path: Path):
    controls, treated = _targets(tmp_path)
    rows = list(csv.DictReader(treated.open(encoding="utf-8")))
    rows[0]["candidate_symbol"] = "C1"
    _write_csv(treated, list(rows[0]), rows)

    with pytest.raises(
        materializer.G5MatchingMetadataMaterializationError,
        match="treated/control target collision",
    ):
        materializer.build(
            control_targets_path=controls,
            treated_targets_path=treated,
            source_paths=[_derived(tmp_path), _external(tmp_path)],
            output_path=tmp_path / "m.csv",
            gap_path=tmp_path / "g.csv",
            summary_path=tmp_path / "s.json",
        )
