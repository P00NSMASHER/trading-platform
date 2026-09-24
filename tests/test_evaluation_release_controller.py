from __future__ import annotations

import json
from pathlib import Path

import evaluation_release_controller as erc

ROOT = Path(__file__).resolve().parents[1]


def _copy_json(src: Path, dst: Path, mutate=None) -> Path:
    obj = json.loads(src.read_text())
    if mutate:
        mutate(obj)
    dst.write_text(json.dumps(obj, indent=2) + "\n")
    return dst


def _base_kwargs(tmp_path: Path) -> dict:
    out = tmp_path / "release"
    return dict(
        coverage_summary=ROOT / "data/processed/coverage_plan_real/coverage_summary.json",
        market_backfill_manifest=ROOT / "data/processed/historical_market_backfill_demo/historical_market_backfill_manifest.json",
        market_contract=ROOT / "config/historical_market_sources.example.json",
        historical_events=ROOT / "data/examples/backfill_events.csv",
        metadata_readiness=ROOT / "data/processed/metadata_resolver_demo/metadata_readiness_summary.json",
        metadata_quality=ROOT / "data/processed/metadata_quality_demo/metadata_quality_summary.json",
        matched_controls=ROOT / "data/examples/model_training_matched_controls.csv",
        base_features=ROOT / "data/examples/model_training_feature_vectors.csv",
        graph_features=ROOT / "data/examples/model_training_graph_features.csv",
        champion_bundle=ROOT / "data/processed/model_demo/model_bundle.joblib",
        champion_training_manifest=ROOT / "data/processed/model_demo/training_manifest.json",
        challenger_manifest=ROOT / "data/processed/graph_challenger_demo/challenger_manifest.json",
        challenger_cv_audit=ROOT / "data/processed/graph_challenger_demo/cv_split_audit.json",
        output_dir=out,
        expected_champion_sha256="0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616",
        holdout_start_year=2015,
    )


def test_real_current_state_is_fail_closed(tmp_path):
    kw = _base_kwargs(tmp_path)
    kw.update(
        historical_events=ROOT / "data/processed/historical_events.csv",
        metadata_readiness=ROOT / "data/processed/metadata_resolution_real/metadata_readiness_summary.json",
        metadata_quality=ROOT / "data/processed/metadata_quality_real/metadata_quality_summary.json",
    )
    result = erc.assess_release(**kw)
    assert result["evaluation_release_permitted"] is False
    assert result["release_token"] is None
    assert not (kw["output_dir"] / "evaluation_release_token.json").exists()
    gates = {x["gate_id"] for x in result["blocking_failures"]}
    assert "G1_ANNOUNCEMENT_TIMES" in gates
    assert "G2_REAL_MARKET_DATA" in gates
    assert "G6_METADATA_QUALITY" in gates


def test_synthetic_complete_metadata_still_cannot_release(tmp_path):
    kw = _base_kwargs(tmp_path)
    result = erc.assess_release(**kw)
    assert result["evaluation_release_permitted"] is False
    gates = {x["gate_id"] for x in result["blocking_failures"]}
    assert "G11_NON_SYNTHETIC_RESEARCH_ONLY" in gates


def test_champion_hash_mismatch_blocks(tmp_path):
    kw = _base_kwargs(tmp_path)
    kw["expected_champion_sha256"] = "0" * 64
    result = erc.assess_release(**kw)
    gates = {x["gate_id"] for x in result["blocking_failures"]}
    assert "G10_CHAMPION_IMMUTABILITY" in gates


def test_forensic_graph_vector_blocks_temporal_gate(tmp_path):
    kw = _base_kwargs(tmp_path)
    src = kw["graph_features"]
    bad = tmp_path / "graph.csv"
    text = src.read_text()
    bad.write_text(text.replace("live_surveillance", "historical_forensics", 1))
    kw["graph_features"] = bad
    # Update challenger manifest hash so this test targets temporal visibility rather than provenance only.
    ch = json.loads(Path(kw["challenger_manifest"]).read_text())
    ch["inputs"]["graph_feature_vectors_sha256"] = erc._sha256(bad)
    chp = tmp_path / "challenger.json"; chp.write_text(json.dumps(ch))
    kw["challenger_manifest"] = chp
    result = erc.assess_release(**kw)
    gates = {x["gate_id"] for x in result["blocking_failures"]}
    assert "G7_TEMPORAL_FEATURE_INTEGRITY" in gates


def test_hash_mismatch_blocks_provenance(tmp_path):
    kw = _base_kwargs(tmp_path)
    base = tmp_path / "base.csv"
    base.write_text(Path(kw["base_features"]).read_text() + "\n")
    kw["base_features"] = base
    result = erc.assess_release(**kw)
    assert any(x["gate_id"] == "G9_PROVENANCE" and x["code"] == "HASH_MISMATCH" for x in result["blocking_failures"])


def test_release_token_is_bound_to_exact_hashed_inputs(tmp_path):
    # Construct a positive-path controller fixture from the real schemas. It is not a performance claim.
    kw = _base_kwargs(tmp_path)

    coverage = json.loads(Path(kw["coverage_summary"]).read_text())
    a = coverage["contract_audit"]
    a["ready_for_real_backfill"] = True
    a["missing_real_authorized_required_rows"] = 0
    a["real_authorized_required_rows_covered"] = a["required_source_date_rows"]
    cp = tmp_path / "coverage.json"; cp.write_text(json.dumps(coverage))
    kw["coverage_summary"] = cp

    # Make a dedicated non-synthetic contract and matching manifest around the tiny market fixture.
    market_contract_obj = json.loads(Path(kw["market_contract"]).read_text())
    for s in market_contract_obj["sources"]:
        s["data_classification"] = "authorized_historical_market_data"
        s["license_reference"] = "test-authorized-reference"
    mcp = tmp_path / "market_contract.json"; mcp.write_text(json.dumps(market_contract_obj))
    kw["market_contract"] = mcp
    coverage["events_sha256"] = erc._sha256(Path(kw["historical_events"]))
    coverage["contract_audit"]["contract_sha256"] = erc._sha256(mcp)
    cp.write_text(json.dumps(coverage))
    market = json.loads(Path(kw["market_backfill_manifest"]).read_text())
    market["contract_sha256"] = erc._sha256(mcp)
    market["historical_events_sha256"] = erc._sha256(Path(kw["historical_events"]))
    for s in market["source_contracts"]:
        s["data_classification"] = "authorized_historical_market_data"
        s["authorized"] = True
        s["license_reference"] = "test-authorized-reference"
    market["non_synthetic_comparison_readiness"]["eligible_for_champion_challenger_unlock"] = True
    mp = tmp_path / "market.json"; mp.write_text(json.dumps(market))
    kw["market_backfill_manifest"] = mp

    ready = json.loads(Path(kw["metadata_readiness"]).read_text())
    for k in ["ready_g1_announcement_times", "ready_g3_primary_listing_history", "ready_g4_shares_outstanding", "ready_g5_matched_control_universe", "ready_for_non_synthetic_model_evaluation_metadata"]:
        ready[k] = True
    ready["events_sha256"] = erc._sha256(Path(kw["historical_events"]))
    rp = tmp_path / "ready.json"; rp.write_text(json.dumps(ready)); kw["metadata_readiness"] = rp

    quality = json.loads(Path(kw["metadata_quality"]).read_text())
    quality.update({"quality_gate_clear": True, "quality_cleared_for_non_synthetic_model_evaluation": True, "only_synthetic_sources": False, "blocking_issue_count": 0})
    quality["resolver_summary_sha256"] = erc._sha256(rp)
    qp = tmp_path / "quality.json"; qp.write_text(json.dumps(quality)); kw["metadata_quality"] = qp

    challenger = json.loads(Path(kw["challenger_manifest"]).read_text())
    challenger["synthetic_fixture_detected"] = False
    chp = tmp_path / "challenger.json"; chp.write_text(json.dumps(challenger)); kw["challenger_manifest"] = chp

    result = erc.assess_release(**kw)
    assert result["evaluation_release_permitted"] is True
    token = json.loads((kw["output_dir"] / "evaluation_release_token.json").read_text())
    assert token["input_hashes"]["base_features"] == erc._sha256(Path(kw["base_features"]))
    assert token["automatic_promotion_permitted"] is False
    assert token["active_champion_modification_permitted"] is False
