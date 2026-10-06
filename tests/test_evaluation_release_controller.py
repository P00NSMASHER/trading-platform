from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import evaluation_release_controller as erc

ROOT = Path(__file__).resolve().parents[1]


def _copy_json(src: Path, dst: Path, mutate=None) -> Path:
    obj = json.loads(src.read_text())
    if mutate:
        mutate(obj)
    dst.write_text(json.dumps(obj, indent=2) + "\n")
    return dst


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _attach_positive_match_quality_fixture(tmp_path: Path, kw: dict) -> None:
    source = Path(kw["matched_controls"])
    with source.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        original_fields = list(reader.fieldnames or [])
        original_rows = list(reader)

    extra_fields = [
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
    fields = original_fields + [
        field for field in extra_fields if field not in original_fields
    ]

    ny = ZoneInfo("America/New_York")
    enriched: list[dict[str, str]] = []
    events: dict[str, dict[str, str]] = {}
    summaries: dict[str, dict[str, str]] = {}
    for raw in original_rows:
        row = {str(k): str(v or "") for k, v in raw.items()}
        ts = datetime.fromisoformat(
            row["treated_minute_ts_utc"].replace("Z", "+00:00")
        )
        local = ts.astimezone(ny)
        row.update(
            {
                "local_date": local.date().isoformat(),
                "local_minute": local.strftime("%H:%M"),
                "same_sector": "1",
                "scheduled_event_match": "1",
                "candidate_pool_size": "4",
                "numeric_covariates_used": "1",
                "match_distance": "0.5",
                "max_component_z": "1.0",
                "match_quality": "good",
                "treated_feature_status": "full",
                "control_feature_status": "full",
                "metadata_source_names": "positive-controller-fixture",
                "research_use_only": "1",
            }
        )
        enriched.append(row)
        event_id = row["event_id"]
        events.setdefault(
            event_id,
            {
                "event_id": event_id,
                "historical_symbol": row["treated_symbol"],
                "first_documented_illicit_trade_ts": row[
                    "treated_minute_ts_utc"
                ],
                "research_use_only": "1",
            },
        )
        summaries.setdefault(
            event_id,
            {
                "event_id": event_id,
                "treated_symbol": row["treated_symbol"],
                "treated_minute_ts_utc": row["treated_minute_ts_utc"],
                "local_date": row["local_date"],
                "local_minute": row["local_minute"],
                "candidate_pool_size": "4",
                "matched_control_count": "3",
                "event_status": "matched",
                "mean_match_distance": "0.5",
                "max_match_distance": "0.5",
                "max_component_z": "1.0",
                "research_use_only": "1",
            },
        )

    controls_path = _write_csv(
        tmp_path / "release_quality_matched_controls.csv",
        fields,
        enriched,
    )
    events_path = _write_csv(
        tmp_path / "release_quality_events.csv",
        list(next(iter(events.values())).keys()),
        list(events.values()),
    )
    event_rows = list(summaries.values())
    match_events_path = _write_csv(
        tmp_path / "release_quality_match_events.csv",
        list(event_rows[0].keys()),
        event_rows,
    )

    balance_rows = [
        {
            "covariate": "market_cap",
            "treated_n": str(len(events)),
            "candidate_n": str(max(len(enriched), len(events) * 4)),
            "matched_n": str(len(enriched)),
            "treated_mean_transformed": "1",
            "candidate_mean_transformed": "1.05",
            "matched_mean_transformed": "1.01",
            "smd_before": "0.1",
            "smd_after": "0.05",
            "preferred_abs_smd_max": "0.1",
            "maximum_abs_smd": "0.2",
            "research_use_only": "1",
        }
    ]
    match_balance_path = _write_csv(
        tmp_path / "release_quality_match_balance.csv",
        list(balance_rows[0].keys()),
        balance_rows,
    )
    match_manifest = {
        "schema_version": "test",
        "matching_policy": {
            "controls_per_event": 3,
            "minimum_controls": 3,
            "known_positive_event_controls_excluded": True,
            "max_standardized_component_distance": 2.5,
            "numeric_covariates": ["market_cap"],
        },
        "outputs": {
            "event_count": len(events),
            "matched_control_rows": len(enriched),
            "event_status_counts": {"matched": len(events)},
            "balance_rows": 1,
        },
        "balance_policy": {
            "preferred_abs_smd_max": 0.1,
            "maximum_abs_smd": 0.2,
        },
    }
    match_manifest_path = tmp_path / "release_quality_match_manifest.json"
    match_manifest_path.write_text(
        json.dumps(match_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    kw.update(
        historical_events=events_path,
        matched_controls=controls_path,
        match_events=match_events_path,
        match_balance=match_balance_path,
        match_manifest=match_manifest_path,
    )

    training = json.loads(Path(kw["champion_training_manifest"]).read_text())
    training["inputs"]["matched_controls"] = str(controls_path)
    training["inputs"]["matched_controls_sha256"] = erc._sha256(controls_path)
    training_path = tmp_path / "release_quality_training_manifest.json"
    training_path.write_text(json.dumps(training, indent=2) + "\n")
    kw["champion_training_manifest"] = training_path

    challenger = json.loads(Path(kw["challenger_manifest"]).read_text())
    challenger["inputs"]["matched_controls"] = str(controls_path)
    challenger["inputs"]["matched_controls_sha256"] = erc._sha256(controls_path)
    challenger_path = tmp_path / "release_quality_challenger_manifest.json"
    challenger_path.write_text(json.dumps(challenger, indent=2) + "\n")
    kw["challenger_manifest"] = challenger_path



def _attach_positive_g5_control_identity_fixture(tmp_path: Path, kw: dict) -> None:
    requirements = _write_csv(
        tmp_path / "release_g5_identity_requirements.csv",
        [
            "historical_symbol",
            "trade_date",
            "roles",
            "identity_status",
            "canonical_g2_overlap",
            "canonical_permno",
            "canonical_gvkey",
            "samplefirms_permno",
            "samplefirms_gvkey",
            "samplefirms_exact_mapping_status",
            "required_evidence",
            "research_use_only",
        ],
        [
            {
                "historical_symbol": "AAA",
                "trade_date": "2015-01-01",
                "roles": "event_point",
                "identity_status": "REUSE_CANONICAL_G2_VERIFIED_IDENTITY",
                "canonical_g2_overlap": "CANONICAL_G2_VERIFIED",
                "canonical_permno": "11111",
                "canonical_gvkey": "1",
                "samplefirms_permno": "",
                "samplefirms_gvkey": "",
                "samplefirms_exact_mapping_status": "NO_EXACT_DATE_MAPPING",
                "required_evidence": "",
                "research_use_only": "1",
            },
            {
                "historical_symbol": "AAA",
                "trade_date": "2015-01-02",
                "roles": "prior_close",
                "identity_status": "OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE",
                "canonical_g2_overlap": "CANONICAL_G2_UNVERIFIED",
                "canonical_permno": "11111",
                "canonical_gvkey": "1",
                "samplefirms_permno": "",
                "samplefirms_gvkey": "",
                "samplefirms_exact_mapping_status": "NO_EXACT_DATE_MAPPING",
                "required_evidence": "DATED_STABLE_ID_CROSSWALK",
                "research_use_only": "1",
            },
            {
                "historical_symbol": "BBB",
                "trade_date": "2015-01-03",
                "roles": "event_point",
                "identity_status": "PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION",
                "canonical_g2_overlap": "NONE",
                "canonical_permno": "",
                "canonical_gvkey": "",
                "samplefirms_permno": "22222",
                "samplefirms_gvkey": "2",
                "samplefirms_exact_mapping_status": "UNIQUE_EXACT_DATE_MAPPING_AVAILABLE",
                "required_evidence": "ADMISSIBLE_DATE_SPECIFIC_STABLE_ID_EVIDENCE",
                "research_use_only": "1",
            },
        ],
    )
    canonical = tmp_path / "release_g5_canonical_identity.json"
    canonical.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "historical_symbol": "AAA",
                        "permno": "11111",
                        "verified_required_dates": ["2015-01-01", "2015-01-02"],
                    }
                ]
            }
        )
    )
    staged = _write_csv(
        tmp_path / "release_g5_only_staged_identity.csv",
        [
            "historical_symbol",
            "trade_date",
            "permno",
            "market_identifier",
            "evidence_ids",
            "source_references",
            "authorization_references",
            "research_use_only",
        ],
        [
            {
                "historical_symbol": "BBB",
                "trade_date": "2015-01-03",
                "permno": "22222",
                "market_identifier": "BBB",
                "evidence_ids": "E-G5",
                "source_references": "stocknames:test",
                "authorization_references": "AUTHORIZED-TEST",
                "research_use_only": "1",
            }
        ],
    )
    staging_receipt = tmp_path / "release_g5_identity_staging_receipt.json"
    staging_receipt.write_text(
        json.dumps(
            {
                "research_use_only": True,
                "canonical_g2_write_performed": False,
                "canonical_g5_write_performed": False,
                "counts": {"g5_only_staged_verified_count": 1},
                "output_sha256": {
                    "g5_only_staged_verified": erc._sha256(staged)
                },
            }
        )
    )
    kw.update(
        g5_identity_requirements=requirements,
        g5_canonical_g2_identity_manifest=canonical,
        g5_only_staged_identity=staged,
        g5_identity_staging_receipt=staging_receipt,
    )


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
    _attach_positive_match_quality_fixture(tmp_path, kw)
    _attach_positive_g5_control_identity_fixture(tmp_path, kw)

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
    market.setdefault("source_contract_policy", {})["stable_security_identity_gate_required_for_non_synthetic_unlock"] = True
    market["security_identity_gate"] = {
        "attached": True,
        "ready_for_non_synthetic_market_join": True,
        "baseline_identity_unverified_count": 0,
        "path": "test-security-identity.json",
        "sha256": "1" * 64,
    }
    mp = tmp_path / "market.json"; mp.write_text(json.dumps(market))
    kw["market_backfill_manifest"] = mp

    ready = json.loads(Path(kw["metadata_readiness"]).read_text())
    for k in ["ready_g1_announcement_times", "ready_g1_exact_timing_analysis", "ready_g3_primary_listing_history", "ready_g4_shares_outstanding", "ready_g5_matched_control_universe", "ready_g5_model_evaluation_controls", "ready_for_non_synthetic_model_evaluation_metadata"]:
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
    assert token["input_hashes"]["match_events"] == erc._sha256(Path(kw["match_events"]))
    assert token["input_hashes"]["match_balance"] == erc._sha256(Path(kw["match_balance"]))
    assert token["input_hashes"]["match_manifest"] == erc._sha256(Path(kw["match_manifest"]))
    assert token["input_hashes"]["g5_identity_requirements"] == erc._sha256(Path(kw["g5_identity_requirements"]))
    assert token["input_hashes"]["g5_canonical_g2_identity_manifest"] == erc._sha256(Path(kw["g5_canonical_g2_identity_manifest"]))
    assert token["input_hashes"]["g5_only_staged_identity"] == erc._sha256(Path(kw["g5_only_staged_identity"]))
    assert token["input_hashes"]["g5_identity_staging_receipt"] == erc._sha256(Path(kw["g5_identity_staging_receipt"]))
    assert token["input_hashes"]["g5_control_identity_gate_receipt"]
    assert token["input_hashes"]["g5_match_quality_receipt"]
    assert token["automatic_promotion_permitted"] is False
    assert token["active_champion_modification_permitted"] is False


def test_g1_completion_with_exclusions_does_not_unlock_exact_timing_release(tmp_path):
    kw = _base_kwargs(tmp_path)
    ready = json.loads(Path(kw["metadata_readiness"]).read_text())
    ready["ready_g1_announcement_times"] = True
    ready["ready_g1_exact_timing_analysis"] = False
    rp = tmp_path / "g1-excluded-ready.json"
    rp.write_text(json.dumps(ready))
    kw["metadata_readiness"] = rp

    quality = json.loads(Path(kw["metadata_quality"]).read_text())
    quality["resolver_summary_sha256"] = erc._sha256(rp)
    qp = tmp_path / "g1-excluded-quality.json"
    qp.write_text(json.dumps(quality))
    kw["metadata_quality"] = qp

    result = erc.assess_release(**kw)
    gates = {x["gate_id"] for x in result["blocking_failures"]}
    assert "G1_ANNOUNCEMENT_TIMES" not in gates
    assert "G1_EXACT_TIMING_ANALYSIS" in gates
    assert result["evaluation_release_permitted"] is False


def test_g5_completion_with_exclusions_does_not_unlock_model_control_release(tmp_path):
    kw = _base_kwargs(tmp_path)
    ready = json.loads(Path(kw["metadata_readiness"]).read_text())
    ready["ready_g5_matched_control_universe"] = True
    ready["ready_g5_model_evaluation_controls"] = False
    rp = tmp_path / "g5-excluded-ready.json"
    rp.write_text(json.dumps(ready))
    kw["metadata_readiness"] = rp

    quality = json.loads(Path(kw["metadata_quality"]).read_text())
    quality["resolver_summary_sha256"] = erc._sha256(rp)
    qp = tmp_path / "g5-excluded-quality.json"
    qp.write_text(json.dumps(quality))
    kw["metadata_quality"] = qp

    result = erc.assess_release(**kw)
    gates = {x["gate_id"] for x in result["blocking_failures"]}
    assert "G5_MATCHED_CONTROL_UNIVERSE" not in gates
    assert "G5_MODEL_EVALUATION_CONTROLS" in gates
    assert result["evaluation_release_permitted"] is False


def test_stable_security_identity_independently_blocks_false_market_unlock():
    checks = []
    coverage = {
        "contract_audit": {
            "ready_for_real_backfill": True,
            "missing_real_authorized_required_rows": 0,
            "required_source_date_rows": 1656,
            "real_authorized_required_rows_covered": 1656,
        }
    }
    market = {
        "non_synthetic_comparison_readiness": {
            "eligible_for_champion_challenger_unlock": True,
        },
        "source_contracts": [{
            "data_classification": "authorized_historical_market_data",
            "authorized": True,
            "license_reference": "authorized-test-source",
        }],
        "source_contract_policy": {
            "stable_security_identity_gate_required_for_non_synthetic_unlock": True,
        },
        "security_identity_gate": {
            "attached": True,
            "ready_for_non_synthetic_market_join": False,
            "baseline_identity_unverified_count": 3654,
            "path": "security_identity_manifest.json",
            "sha256": "a" * 64,
        },
    }

    erc._market_checks(checks, coverage, market)
    by_gate = {row.gate_id: row for row in checks}
    assert by_gate["G2_REAL_MARKET_DATA"].passed is True
    assert by_gate["G2_STABLE_SECURITY_IDENTITY"].passed is False
    assert "baseline_unverified=3654" in by_gate["G2_STABLE_SECURITY_IDENTITY"].detail


def test_missing_g5_match_quality_evidence_independently_blocks_release(tmp_path):
    kw = _base_kwargs(tmp_path)
    result = erc.assess_release(**kw)
    by_gate = {row["gate_id"]: row for row in result["blocking_failures"]}
    assert "G5_MATCH_QUALITY" in by_gate
    assert by_gate["G5_MATCH_QUALITY"]["code"] == "MISSING_EVIDENCE"
    assert result["evaluation_release_permitted"] is False


def test_missing_g5_control_identity_evidence_independently_blocks_release(tmp_path):
    kw = _base_kwargs(tmp_path)
    result = erc.assess_release(**kw)
    by_gate = {row["gate_id"]: row for row in result["blocking_failures"]}
    assert "G5_CONTROL_STABLE_IDENTITY" in by_gate
    assert by_gate["G5_CONTROL_STABLE_IDENTITY"]["code"] == "MISSING_EVIDENCE"
    assert result["evaluation_release_permitted"] is False
