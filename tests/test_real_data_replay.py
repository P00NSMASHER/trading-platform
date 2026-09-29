from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import real_data_replay as replay


def test_materialize_resolved_shares_excludes_fail_closed_rows(tmp_path: Path):
    source = tmp_path / "shares.csv"
    source.write_text(
        "historical_symbol,trade_date,shares_outstanding,resolution_status\n"
        "AAA,2015-01-02,100,resolved\n"
        "AAA,2015-01-03,,excluded_fail_closed\n"
        "BBB,2015-01-02,200,resolved\n",
        encoding="utf-8",
    )
    out = tmp_path / "shares_for_baselines.csv"
    receipt = replay.materialize_resolved_shares(source, out)

    rows = list(csv.DictReader(out.open()))
    assert receipt["resolved_rows"] == 2
    assert receipt["excluded_rows_not_materialized"] is True
    assert rows == [
        {"symbol": "AAA", "effective_date": "2015-01-02", "shares_outstanding": "100"},
        {"symbol": "BBB", "effective_date": "2015-01-02", "shares_outstanding": "200"},
    ]


def test_replay_with_synthetic_market_contract_stays_fail_closed(tmp_path: Path):
    cfg = tmp_path / "replay.json"
    cfg.write_text(
        json.dumps({
            "schema_version": "1",
            "events": str(ROOT / "data/processed/historical_events.csv"),
            "market_contract": str(ROOT / "config/historical_market_sources.example.json"),
            "metadata_contract": str(ROOT / "config/metadata_sources.public_progress.json"),
            "output_dir": str(tmp_path / "out"),
            "graph_db": str(ROOT / "data/processed/historical_graph_real/historical_cross_event_graph.sqlite"),
        }),
        encoding="utf-8",
    )

    result = replay.run_replay(cfg)

    assert result["ready_for_non_synthetic_offline_evaluation"] is False
    assert result["evaluation_release_permitted"] is False
    assert result["stages"]["market_backfill"]["status"] == "BLOCKED_SYNTHETIC_SOURCE_PRESENT"
    assert result["stages"]["baselines"]["status"] == "DEPENDENCY_BLOCKED"
    assert result["stages"]["features"]["status"] == "DEPENDENCY_BLOCKED"
    assert result["stages"]["release"]["status"] == "DEPENDENCY_BLOCKED"
    assert result["stages"]["coverage"]["covered_real_source_date_rows"] == 0
    assert result["stages"]["coverage"]["required_source_date_rows"] == 1656
    assert (tmp_path / "out" / "real_data_replay_status.json").exists()


def test_replay_config_requires_existing_contracts(tmp_path: Path):
    cfg = tmp_path / "bad.json"
    cfg.write_text(json.dumps({
        "schema_version": "1",
        "events": str(ROOT / "data/processed/historical_events.csv"),
        "market_contract": str(tmp_path / "missing-market.json"),
        "metadata_contract": str(ROOT / "config/metadata_sources.public_progress.json"),
        "output_dir": str(tmp_path / "out"),
    }), encoding="utf-8")

    try:
        replay.run_replay(cfg)
    except FileNotFoundError as exc:
        assert "market contract" in str(exc)
    else:
        raise AssertionError("missing market contract must fail closed")


def test_output_dir_override_stages_without_changing_logical_receipt_paths(tmp_path: Path):
    cfg = tmp_path / "replay.json"
    published = tmp_path / "published"
    staged = tmp_path / "staged"
    cfg.write_text(
        json.dumps({
            "schema_version": "1",
            "events": str(ROOT / "data/processed/historical_events.csv"),
            "market_contract": str(ROOT / "config/historical_market_sources.example.json"),
            "metadata_contract": str(ROOT / "config/metadata_sources.public_progress.json"),
            "output_dir": str(published),
            "graph_db": str(ROOT / "data/processed/historical_graph_real/historical_cross_event_graph.sqlite"),
        }),
        encoding="utf-8",
    )

    result = replay.run_replay(cfg, output_dir_override=staged)

    assert (staged / "real_data_replay_status.json").exists()
    assert not published.exists()
    assert result["config_path"] == str(cfg)
    assert result["shares_materialization"]["path"] == str(
        published / "derived" / "shares_for_baselines.csv"
    )


def test_market_release_readiness_requires_stable_security_identity():
    manifest = {
        "non_synthetic_comparison_readiness": {
            "eligible_for_champion_challenger_unlock": True,
        },
        "security_identity_gate": {
            "attached": True,
            "ready_for_non_synthetic_market_join": False,
            "baseline_identity_unverified_count": 3654,
            "sha256": "a" * 64,
        },
    }
    blocked = replay._market_release_readiness(manifest)
    assert blocked["ready"] is False
    assert blocked["backfill_unlock"] is True
    assert blocked["identity_ready"] is False
    assert blocked["baseline_identity_unverified_count"] == 3654

    manifest["security_identity_gate"].update({
        "ready_for_non_synthetic_market_join": True,
        "baseline_identity_unverified_count": 0,
    })
    ready = replay._market_release_readiness(manifest)
    assert ready["ready"] is True

    manifest["non_synthetic_comparison_readiness"]["eligible_for_champion_challenger_unlock"] = False
    assert replay._market_release_readiness(manifest)["ready"] is False
