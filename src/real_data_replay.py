from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import baseline_engine as baseline
import coverage_planner as coverage_planner
import evaluation_release_controller as release_controller
import feature_engine as feature_engine
import g5_control_identity_gate as g5_control_identity
import g5_match_quality_gate as g5_match_quality
import g5_matching_metadata_materializer as g5_matching_metadata
import graph_challenger_harness as challenger_harness
import graph_feature_engine as graph_features
import historical_market_backfill as market_backfill
import matched_control_generator as matcher
import metadata_quality
import metadata_resolver

SCHEMA_VERSION = "1.0.0"
PROHIBITED_OUTPUTS = [
    "BUY", "SELL", "expected_return", "target_price", "position_size",
    "order", "execution_instruction",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return obj


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resolve_config_path(value: str | None, *, config_path: Path) -> Path | None:
    if not value:
        return None
    p = Path(value)
    if p.is_absolute():
        return p
    # Existing repository contracts use repository-relative paths. Resolve replay
    # config paths from the current working directory for the same semantics.
    return p.resolve()


def _require_file(path: Path | None, label: str) -> Path:
    if path is None or not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def materialize_resolved_shares(resolver_csv: Path, output_path: Path) -> dict[str, Any]:
    """Convert resolver symbol-date shares into the baseline engine's point-in-time schema.

    Only exact/resolved rows are emitted. Reviewed exclusions remain absent, so
    downstream turnover is fail-closed rather than silently imputed.
    """
    by_key: dict[tuple[str, str], str] = {}
    with resolver_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"historical_symbol", "trade_date", "shares_outstanding", "resolution_status"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"shares resolver missing columns: {sorted(missing)}")
        for row in reader:
            if (row.get("resolution_status") or "").strip() != "resolved":
                continue
            symbol = (row.get("historical_symbol") or "").strip().upper()
            trade_date = (row.get("trade_date") or "").strip()
            shares = (row.get("shares_outstanding") or "").strip()
            if not symbol or not trade_date or not shares:
                continue
            try:
                if float(shares) <= 0:
                    continue
            except Exception:
                continue
            by_key[(symbol, trade_date)] = shares

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "effective_date", "shares_outstanding"])
        writer.writeheader()
        for (symbol, effective_date), shares in sorted(by_key.items()):
            writer.writerow({
                "symbol": symbol,
                "effective_date": effective_date,
                "shares_outstanding": shares,
            })
    return {
        "path": str(output_path),
        "sha256": _sha256(output_path),
        "resolved_rows": len(by_key),
        "excluded_rows_not_materialized": True,
    }


def _market_source_state(contract_path: Path) -> dict[str, Any]:
    specs, _ = market_backfill.load_contract(contract_path)
    real = [s for s in specs if s.data_classification == market_backfill.NON_SYNTHETIC_CLASS]
    synthetic = [s for s in specs if s.data_classification == market_backfill.SYNTHETIC_CLASS]
    return {
        "source_count": len(specs),
        "real_source_count": len(real),
        "synthetic_source_count": len(synthetic),
        "source_ids": [s.source_id for s in specs],
        "has_real_sources": bool(real),
        "has_synthetic_sources": bool(synthetic),
    }


def _stage(status: str, **details: Any) -> dict[str, Any]:
    return {"status": status, **details}


def _market_release_readiness(market_manifest: dict[str, Any] | None) -> dict[str, Any]:
    if market_manifest is None:
        return {
            "ready": False,
            "backfill_unlock": False,
            "identity_attached": False,
            "identity_ready": False,
            "baseline_identity_unverified_count": None,
            "identity_sha_present": False,
        }
    backfill = market_manifest.get("non_synthetic_comparison_readiness") or {}
    identity = market_manifest.get("security_identity_gate") or {}
    backfill_unlock = bool(backfill.get("eligible_for_champion_challenger_unlock"))
    identity_attached = bool(identity.get("attached"))
    identity_ready = bool(identity.get("ready_for_non_synthetic_market_join"))
    raw_unverified = identity.get("baseline_identity_unverified_count")
    try:
        unverified = int(raw_unverified) if raw_unverified is not None else None
    except (TypeError, ValueError):
        unverified = None
    identity_sha_present = bool(str(identity.get("sha256", "")).strip())
    ready = (
        backfill_unlock
        and identity_attached
        and identity_ready
        and unverified == 0
        and identity_sha_present
    )
    return {
        "ready": ready,
        "backfill_unlock": backfill_unlock,
        "identity_attached": identity_attached,
        "identity_ready": identity_ready,
        "baseline_identity_unverified_count": unverified,
        "identity_sha_present": identity_sha_present,
    }


def run_replay(
    config_path: Path,
    *,
    require_ready: bool = False,
    output_dir_override: Path | None = None,
) -> dict[str, Any]:
    cfg = _read_json(config_path)
    if str(cfg.get("schema_version")) != "1":
        raise ValueError("real-data replay config schema_version must equal '1'")

    events = _require_file(_resolve_config_path(cfg.get("events"), config_path=config_path), "events")
    market_contract = _require_file(
        _resolve_config_path(cfg.get("market_contract"), config_path=config_path), "market contract"
    )
    metadata_contract = _require_file(
        _resolve_config_path(cfg.get("metadata_contract"), config_path=config_path), "metadata contract"
    )
    configured_output_dir = _resolve_config_path(cfg.get("output_dir"), config_path=config_path)
    if configured_output_dir is None:
        raise ValueError("output_dir is required")
    logical_output_dir = configured_output_dir
    output_dir = (
        Path(output_dir_override).resolve()
        if output_dir_override is not None
        else configured_output_dir
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    graph_db = _resolve_config_path(cfg.get("graph_db"), config_path=config_path)
    control_metadata = _resolve_config_path(cfg.get("control_metadata"), config_path=config_path)
    g5_matching_spec = cfg.get("g5_matching_metadata")
    if g5_matching_spec is not None and control_metadata is not None:
        raise ValueError(
            "control_metadata and g5_matching_metadata are mutually exclusive"
        )
    champion_bundle = _resolve_config_path(cfg.get("champion_bundle"), config_path=config_path)
    champion_training_manifest = _resolve_config_path(
        cfg.get("champion_training_manifest"), config_path=config_path
    )

    stages: dict[str, dict[str, Any]] = {}
    g5_matching_inputs: dict[str, Any] | None = None
    if g5_matching_spec is not None:
        if not isinstance(g5_matching_spec, dict):
            raise ValueError("g5_matching_metadata must be an object")
        control_targets = _require_file(
            _resolve_config_path(
                g5_matching_spec.get("control_targets"),
                config_path=config_path,
            ),
            "G5 control targets",
        )
        treated_targets = _require_file(
            _resolve_config_path(
                g5_matching_spec.get("treated_targets"),
                config_path=config_path,
            ),
            "G5 treated targets",
        )
        raw_sources = g5_matching_spec.get("normalized_sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ValueError(
                "g5_matching_metadata.normalized_sources must be a non-empty list"
            )
        normalized_sources = [
            _require_file(
                _resolve_config_path(value, config_path=config_path),
                f"G5 normalized metadata source {index}",
            )
            for index, value in enumerate(raw_sources, 1)
        ]
        minimum_controls = int(
            g5_matching_spec.get("minimum_controls_per_date", 3)
        )
        materialized_dir = output_dir / "g5_matching_metadata"
        materialized_summary = g5_matching_metadata.build(
            control_targets_path=control_targets,
            treated_targets_path=treated_targets,
            source_paths=normalized_sources,
            output_path=materialized_dir / "matcher_metadata.csv",
            gap_path=materialized_dir / "metadata_gaps.csv",
            summary_path=materialized_dir / "materialization_summary.json",
            minimum_controls_per_date=minimum_controls,
        )
        materialized_ready = bool(
            materialized_summary.get("matcher_input_ready")
        )
        stages["g5_matching_metadata"] = _stage(
            "READY" if materialized_ready else "BLOCKED",
            materialized_target_count=materialized_summary.get(
                "materialized_target_count"
            ),
            gap_target_count=materialized_summary.get("gap_target_count"),
            control_dates_with_minimum_complete_metadata=materialized_summary.get(
                "control_dates_with_minimum_complete_metadata"
            ),
            control_event_date_count=materialized_summary.get(
                "control_event_date_count"
            ),
            all_treated_metadata_complete=materialized_summary.get(
                "all_treated_metadata_complete"
            ),
        )
        g5_matching_inputs = {
            "control_targets": {
                "path": str(control_targets),
                "sha256": _sha256(control_targets),
            },
            "treated_targets": {
                "path": str(treated_targets),
                "sha256": _sha256(treated_targets),
            },
            "normalized_sources": [
                {"path": str(source), "sha256": _sha256(source)}
                for source in normalized_sources
            ],
            "minimum_controls_per_date": minimum_controls,
        }
        if materialized_ready:
            control_metadata = materialized_dir / "matcher_metadata.csv"

    g5_control_identity_spec = cfg.get("g5_control_identity")
    g5_control_identity_ready = False
    g5_control_identity_inputs: dict[str, Any] | None = None
    g5_identity_requirements: Path | None = None
    g5_canonical_g2_identity_manifest: Path | None = None
    g5_only_staged_identity: Path | None = None
    g5_identity_staging_receipt: Path | None = None

    if g5_control_identity_spec is not None:
        if not isinstance(g5_control_identity_spec, dict):
            raise ValueError("g5_control_identity must be an object")
        g5_identity_requirements = _require_file(
            _resolve_config_path(
                g5_control_identity_spec.get("identity_requirements"),
                config_path=config_path,
            ),
            "G5 identity requirements",
        )
        g5_canonical_g2_identity_manifest = _require_file(
            _resolve_config_path(
                g5_control_identity_spec.get("canonical_g2_identity_manifest"),
                config_path=config_path,
            ),
            "G5 canonical G2 identity manifest",
        )
        g5_only_staged_identity = _require_file(
            _resolve_config_path(
                g5_control_identity_spec.get("g5_only_staged_identity"),
                config_path=config_path,
            ),
            "G5-only staged identity",
        )
        g5_identity_staging_receipt = _require_file(
            _resolve_config_path(
                g5_control_identity_spec.get("g5_identity_staging_receipt"),
                config_path=config_path,
            ),
            "G5 identity staging receipt",
        )
        identity_gate_dir = output_dir / "g5_control_identity"
        identity_gate_result = g5_control_identity.build(
            identity_requirements_path=g5_identity_requirements,
            canonical_g2_identity_manifest_path=g5_canonical_g2_identity_manifest,
            g5_only_staged_verified_path=g5_only_staged_identity,
            g5_staging_receipt_path=g5_identity_staging_receipt,
            output_path=identity_gate_dir / "g5_control_identity_gate.json",
        )
        identity_state = identity_gate_result.get("state") or {}
        g5_control_identity_ready = bool(
            identity_gate_result.get("ready_for_g5_control_identity")
        )
        stages["g5_control_identity"] = _stage(
            "READY" if g5_control_identity_ready else "BLOCKED",
            required_symbol_date_count=identity_state.get(
                "required_symbol_date_count"
            ),
            verified_symbol_date_count=identity_state.get(
                "verified_symbol_date_count"
            ),
            unresolved_symbol_date_count=identity_state.get(
                "unresolved_symbol_date_count"
            ),
            canonical_g2_overlap_verified_count=identity_state.get(
                "canonical_g2_overlap_verified_count"
            ),
            g5_only_verified_count=identity_state.get(
                "g5_only_verified_count"
            ),
        )
        g5_control_identity_inputs = {
            "identity_requirements": {
                "path": str(g5_identity_requirements),
                "sha256": _sha256(g5_identity_requirements),
            },
            "canonical_g2_identity_manifest": {
                "path": str(g5_canonical_g2_identity_manifest),
                "sha256": _sha256(g5_canonical_g2_identity_manifest),
            },
            "g5_only_staged_identity": {
                "path": str(g5_only_staged_identity),
                "sha256": _sha256(g5_only_staged_identity),
            },
            "g5_identity_staging_receipt": {
                "path": str(g5_identity_staging_receipt),
                "sha256": _sha256(g5_identity_staging_receipt),
            },
        }
    else:
        stages["g5_control_identity"] = _stage(
            "DEPENDENCY_BLOCKED",
            reason="g5_control_identity_not_supplied",
        )

    # 1) Recompute exact required market coverage against whatever provider
    # contracts are supplied. No vendor-specific orchestration is embedded here.
    coverage_dir = output_dir / "coverage"
    coverage = coverage_planner.build(
        events,
        coverage_dir,
        contract_path=market_contract,
    )
    audit = coverage.get("contract_audit") or {}
    stages["coverage"] = _stage(
        "READY" if audit.get("ready_for_real_backfill") else "BLOCKED",
        required_source_date_rows=int(audit.get("required_source_date_rows", 0) or 0),
        covered_real_source_date_rows=int(audit.get("real_authorized_required_rows_covered", 0) or 0),
        missing_real_source_date_rows=int(audit.get("missing_real_authorized_required_rows", 0) or 0),
    )

    # 2) Resolve and quality-audit metadata every run, so newly dropped I/B/E/S,
    # control-universe, listing, or shares files automatically change the gates.
    metadata_dir = output_dir / "metadata"
    readiness = metadata_resolver.build(
        events,
        coverage_dir / "symbol_date_requirements.csv",
        metadata_contract,
        metadata_dir,
    )
    quality = metadata_quality.build(
        events_path=events,
        symbol_dates_path=coverage_dir / "symbol_date_requirements.csv",
        contract_path=metadata_contract,
        resolver_dir=metadata_dir,
        outdir=metadata_dir,
    )
    stages["metadata"] = _stage(
        "READY" if quality.get("quality_cleared_for_non_synthetic_model_evaluation") else "BLOCKED",
        announcement_exact_resolved=int(readiness.get("announcement_exact_resolved", 0) or 0),
        announcement_required=int(readiness.get("event_count", 0) or 0),
        control_dates_resolved=int(readiness.get("control_dates_resolved", 0) or 0),
        control_dates_required=int(readiness.get("event_date_count", 0) or 0),
        exact_timing_ready=bool(readiness.get("ready_g1_exact_timing_analysis")),
        model_controls_ready=bool(readiness.get("ready_g5_model_evaluation_controls")),
        quality_ready=bool(quality.get("quality_cleared_for_non_synthetic_model_evaluation")),
    )

    shares = materialize_resolved_shares(
        metadata_dir / "shares_outstanding_resolutions.csv",
        output_dir / "derived" / "shares_for_baselines.csv",
    )

    source_state = _market_source_state(market_contract)
    market_manifest: dict[str, Any] | None = None
    if source_state["has_synthetic_sources"]:
        # A real replay must never silently combine synthetic and production rows.
        stages["market_backfill"] = _stage(
            "BLOCKED_SYNTHETIC_SOURCE_PRESENT",
            **source_state,
        )
    elif not source_state["has_real_sources"]:
        stages["market_backfill"] = _stage(
            "SOURCE_BLOCKED",
            **source_state,
        )
    else:
        market_dir = output_dir / "market"
        market_manifest = market_backfill.build(
            market_contract,
            events,
            market_dir,
            shares_file=Path(shares["path"]),
        )
        stages["market_backfill"] = _stage(
            "READY" if (market_manifest.get("non_synthetic_comparison_readiness") or {}).get(
                "eligible_for_real_feature_backfill"
            ) else "PARTIAL",
            **source_state,
            outputs=market_manifest.get("outputs") or {},
        )

    feature_manifest: dict[str, Any] | None = None
    graph_manifest: dict[str, Any] | None = None
    match_manifest: dict[str, Any] | None = None
    match_quality_ready = False
    challenger_manifest: dict[str, Any] | None = None
    release_assessment: dict[str, Any] | None = None

    if market_manifest is not None:
        outputs = market_manifest.get("outputs") or {}
        market_dir = output_dir / "market"
        eq_path = market_dir / "equity_minutes.csv" if int(outputs.get("equity_minute_count", 0) or 0) > 0 else None
        op_path = market_dir / "option_minutes.csv" if int(outputs.get("option_minute_count", 0) or 0) > 0 else None
        if eq_path is not None or op_path is not None:
            baseline_dir = output_dir / "baselines"
            baseline_manifest = baseline.build(
                equity_minutes=eq_path,
                option_minutes=op_path,
                shares_file=Path(shares["path"]),
                output_dir=baseline_dir,
            )
            stages["baselines"] = _stage("READY", outputs=baseline_manifest.get("outputs") or {})

            feature_dir = output_dir / "features"
            feature_manifest = feature_engine.build(
                baseline_metrics=baseline_dir / "baseline_metrics.csv",
                equity_minutes=eq_path,
                option_minutes=op_path,
                output_dir=feature_dir,
            )
            stages["features"] = _stage("READY", outputs=feature_manifest.get("outputs") or {})

            if graph_db is not None and graph_db.exists():
                graph_dir = output_dir / "graph_features"
                graph_manifest = graph_features.build_graph_features(
                    feature_vectors=feature_dir / "feature_vectors.csv",
                    graph_db=graph_db,
                    output_dir=graph_dir,
                    mode="live_surveillance",
                )
                stages["graph_features"] = _stage("READY", outputs=graph_manifest.get("outputs") or {})
            else:
                stages["graph_features"] = _stage("DEPENDENCY_BLOCKED", reason="graph_db_not_supplied")
        else:
            stages["baselines"] = _stage("DEPENDENCY_BLOCKED", reason="no_market_minute_rows")
            stages["features"] = _stage("DEPENDENCY_BLOCKED", reason="no_market_minute_rows")
            stages["graph_features"] = _stage("DEPENDENCY_BLOCKED", reason="no_market_minute_rows")
    else:
        stages["baselines"] = _stage("DEPENDENCY_BLOCKED", reason="market_backfill_not_run")
        stages["features"] = _stage("DEPENDENCY_BLOCKED", reason="market_backfill_not_run")
        stages["graph_features"] = _stage("DEPENDENCY_BLOCKED", reason="market_backfill_not_run")

    # Control matching can be tested before release, but requires a candidate-level
    # point-in-time metadata file. The 72-date readiness summary is not a substitute.
    # A configured G5 materialization path must be complete before the matcher sees it.
    if feature_manifest is not None and control_metadata is not None and control_metadata.exists():
        match_dir = output_dir / "matches"
        match_manifest = matcher.build(
            events_path=events,
            feature_vectors=output_dir / "features" / "feature_vectors.csv",
            metadata_path=control_metadata,
            output_dir=match_dir,
        )
        stages["matched_controls"] = _stage("READY", outputs=match_manifest.get("outputs") or {})
        try:
            match_quality = g5_match_quality.build(
                historical_events_path=events,
                matched_controls_path=match_dir / "matched_controls.csv",
                match_events_path=match_dir / "match_events.csv",
                match_balance_path=match_dir / "match_balance.csv",
                match_manifest_path=match_dir / "match_manifest.json",
                output_path=match_dir / "g5_match_quality_gate.json",
            )
            match_quality_ready = bool(
                match_quality.get("ready_for_g5_model_evaluation")
            )
            stages["match_quality"] = _stage(
                "READY" if match_quality_ready else "BLOCKED",
                event_count=match_quality.get("event_count"),
                matched_control_row_count=match_quality.get(
                    "matched_control_row_count"
                ),
                hard_abs_smd_max=match_quality.get("hard_abs_smd_max"),
                preferred_smd_violation_covariates=match_quality.get(
                    "preferred_smd_violation_covariates"
                ),
            )
        except Exception as exc:
            stages["match_quality"] = _stage(
                "BLOCKED",
                reason="g5_match_quality_gate_failed",
                detail=str(exc),
            )
    else:
        if feature_manifest is None:
            match_block_reason = "features_not_ready"
        elif g5_matching_spec is not None:
            match_block_reason = "g5_matching_metadata_not_ready"
        else:
            match_block_reason = "control_metadata_not_supplied"
        stages["matched_controls"] = _stage(
            "DEPENDENCY_BLOCKED",
            reason=match_block_reason,
        )
        stages["match_quality"] = _stage(
            "DEPENDENCY_BLOCKED",
            reason="matched_controls_not_ready",
        )

    market_release = _market_release_readiness(market_manifest)
    real_eval_inputs_ready = (
        market_release["ready"]
        and bool(audit.get("ready_for_real_backfill"))
        and bool(readiness.get("ready_g1_exact_timing_analysis"))
        and bool(readiness.get("ready_g5_model_evaluation_controls"))
        and bool(quality.get("quality_cleared_for_non_synthetic_model_evaluation"))
        and g5_control_identity_ready
        and match_manifest is not None
        and match_quality_ready
        and graph_manifest is not None
        and champion_bundle is not None and champion_bundle.exists()
        and champion_training_manifest is not None and champion_training_manifest.exists()
    )

    if real_eval_inputs_ready:
        challenger_dir = output_dir / "challenger"
        challenger_manifest = challenger_harness.train_challenger(
            matched_controls=output_dir / "matches" / "matched_controls.csv",
            base_feature_vectors=output_dir / "features" / "feature_vectors.csv",
            graph_feature_vectors=output_dir / "graph_features" / "graph_feature_vectors.csv",
            champion_bundle=champion_bundle,
            output_dir=challenger_dir,
        )
        stages["challenger"] = _stage("READY", promotion=challenger_manifest.get("promotion") or {})

        release_dir = output_dir / "release"
        release_assessment = release_controller.assess_release(
            coverage_summary=coverage_dir / "coverage_summary.json",
            market_backfill_manifest=output_dir / "market" / "historical_market_backfill_manifest.json",
            market_contract=market_contract,
            historical_events=events,
            metadata_readiness=metadata_dir / "metadata_readiness_summary.json",
            metadata_quality=metadata_dir / "metadata_quality_summary.json",
            matched_controls=output_dir / "matches" / "matched_controls.csv",
            match_events=output_dir / "matches" / "match_events.csv",
            match_balance=output_dir / "matches" / "match_balance.csv",
            match_manifest=output_dir / "matches" / "match_manifest.json",
            g5_identity_requirements=g5_identity_requirements,
            g5_canonical_g2_identity_manifest=g5_canonical_g2_identity_manifest,
            g5_only_staged_identity=g5_only_staged_identity,
            g5_identity_staging_receipt=g5_identity_staging_receipt,
            base_features=output_dir / "features" / "feature_vectors.csv",
            graph_features=output_dir / "graph_features" / "graph_feature_vectors.csv",
            champion_bundle=champion_bundle,
            champion_training_manifest=champion_training_manifest,
            challenger_manifest=challenger_dir / "challenger_manifest.json",
            challenger_cv_audit=challenger_dir / "cv_split_audit.json",
            output_dir=release_dir,
            expected_champion_sha256=str(cfg.get("expected_champion_sha256") or ""),
            holdout_start_year=int(cfg.get("holdout_start_year", 2015)),
        )
        stages["release"] = _stage(
            "READY" if release_assessment.get("evaluation_release_permitted") else "BLOCKED",
            blocking_failures=release_assessment.get("blocking_failures") or [],
        )
    else:
        stages["challenger"] = _stage("DEPENDENCY_BLOCKED", reason="real_evaluation_inputs_not_ready")
        stages["release"] = _stage("DEPENDENCY_BLOCKED", reason="real_evaluation_inputs_not_ready")

    blockers = [
        name for name, value in stages.items()
        if value.get("status") not in {"READY", "PARTIAL"}
    ]
    ready = bool(release_assessment and release_assessment.get("evaluation_release_permitted"))
    status = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "One-command, provider-agnostic replay of authorized historical market-surveillance data. "
            "Missing evidence blocks downstream stages; synthetic fixtures never satisfy a real replay."
        ),
        "research_use_only": True,
        "config_path": str(config_path),
        "config_sha256": _sha256(config_path),
        "inputs": {
            "events": {"path": str(events), "sha256": _sha256(events)},
            "market_contract": {"path": str(market_contract), "sha256": _sha256(market_contract)},
            "metadata_contract": {"path": str(metadata_contract), "sha256": _sha256(metadata_contract)},
            "graph_db": (
                {"path": str(graph_db), "sha256": _sha256(graph_db)}
                if graph_db is not None and graph_db.exists() else None
            ),
            "control_metadata": (
                {"path": str(control_metadata), "sha256": _sha256(control_metadata)}
                if control_metadata is not None and control_metadata.exists() else None
            ),
            "g5_matching_metadata": g5_matching_inputs,
            "g5_control_identity": g5_control_identity_inputs,
        },
        "shares_materialization": {
            **shares,
            "path": str(logical_output_dir / "derived" / "shares_for_baselines.csv"),
        },
        "stages": stages,
        "blocking_stages": blockers,
        "ready_for_non_synthetic_offline_evaluation": ready,
        "evaluation_release_permitted": ready,
        "automatic_promotion_permitted": False,
        "active_champion_modification_permitted": False,
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    _write_json(output_dir / "real_data_replay_status.json", status)

    if require_ready and not ready:
        raise RuntimeError(
            "real-data replay remains blocked: " + ", ".join(blockers)
        )
    return status


def main() -> None:
    p = argparse.ArgumentParser(
        description="Run the provider-agnostic historical real-data replay pipeline."
    )
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--require-ready", action="store_true")
    args = p.parse_args()
    result = run_replay(args.config, require_ready=args.require_ready)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
