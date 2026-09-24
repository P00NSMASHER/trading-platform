from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import graph_challenger_harness as gch
import model_training_harness as mt

SCHEMA_VERSION = "0.20.0"
PROHIBITED_OUTPUTS = [
    "BUY", "SELL", "LONG/SHORT recommendation", "expected_return", "target_price",
    "position_size", "order", "execution_instruction",
]
FORBIDDEN_LIVE_FIELDS = {
    "realized_spread_5m_pct", "price_impact_5m_pct", "future_price", "future_return",
    "earnings_surprise", "enforcement_outcome", "actual", "hacked", "ground_truth",
}


@dataclass(frozen=True)
class GateCheck:
    gate_id: str
    category: str
    passed: bool
    code: str
    detail: str
    blocking: bool = True
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return obj


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_checks(path: Path, rows: Iterable[GateCheck]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()) if rows else ["gate_id"])
        w.writeheader()
        for row in rows:
            w.writerow(asdict(row))


def _check_hash(checks: list[GateCheck], gate_id: str, category: str, path: Path, expected: str, label: str) -> bool:
    if not path.exists():
        checks.append(GateCheck(gate_id, category, False, "MISSING_FILE", f"{label} missing: {path}"))
        return False
    actual = _sha256(path)
    ok = bool(expected) and actual == expected
    checks.append(GateCheck(
        gate_id, category, ok, "HASH_MATCH" if ok else "HASH_MISMATCH",
        f"{label} sha256={actual}; expected={expected or '<missing>'}",
    ))
    return ok


def _metadata_checks(checks: list[GateCheck], readiness: dict, quality: dict) -> None:
    mapping = [
        ("G1_ANNOUNCEMENT_TIMES", "ready_g1_announcement_times", "exact public announcement timestamps"),
        ("G3_PRIMARY_LISTING_HISTORY", "ready_g3_primary_listing_history", "point-in-time primary listing history"),
        ("G4_SHARES_OUTSTANDING", "ready_g4_shares_outstanding", "point-in-time shares outstanding"),
        ("G5_MATCHED_CONTROL_UNIVERSE", "ready_g5_matched_control_universe", "point-in-time matched-control universe"),
    ]
    for gate_id, key, label in mapping:
        ok = bool(readiness.get(key))
        checks.append(GateCheck(gate_id, "metadata", ok, "READY" if ok else "BLOCKED", label))

    qclear = bool(quality.get("quality_gate_clear"))
    real_clear = bool(quality.get("quality_cleared_for_non_synthetic_model_evaluation"))
    only_synthetic = bool(quality.get("only_synthetic_sources"))
    blocking = int(quality.get("blocking_issue_count", 0) or 0)
    ok = qclear and real_clear and not only_synthetic and blocking == 0
    detail = (
        f"quality_gate_clear={qclear}; real_eval_clear={real_clear}; "
        f"only_synthetic_sources={only_synthetic}; blocking_issues={blocking}"
    )
    checks.append(GateCheck("G6_METADATA_QUALITY", "metadata_quality", ok, "READY" if ok else "BLOCKED", detail))


def _market_checks(checks: list[GateCheck], coverage: dict, market_manifest: dict) -> None:
    audit = coverage.get("contract_audit") or {}
    plan_ready = bool(audit.get("ready_for_real_backfill"))
    missing = int(audit.get("missing_real_authorized_required_rows", 0) or 0)
    required = int(audit.get("required_source_date_rows", 0) or 0)
    covered = int(audit.get("real_authorized_required_rows_covered", 0) or 0)
    backfill = market_manifest.get("non_synthetic_comparison_readiness") or {}
    backfill_ready = bool(backfill.get("eligible_for_champion_challenger_unlock"))
    source_contracts = market_manifest.get("source_contracts") or []
    non_synth = [x for x in source_contracts if x.get("data_classification") == "authorized_historical_market_data"]
    synth = [x for x in source_contracts if x.get("data_classification") == "synthetic_fixture"]
    all_authorized = bool(source_contracts) and all(bool(x.get("authorized")) for x in source_contracts)
    all_licensed = bool(non_synth) and all(bool(str(x.get("license_reference", "")).strip()) for x in non_synth)
    no_synth = len(synth) == 0
    ok = plan_ready and backfill_ready and missing == 0 and required > 0 and covered == required and bool(non_synth) and no_synth and all_authorized and all_licensed
    detail = (
        f"coverage_plan_ready={plan_ready}; required_source_dates={required}; covered_real_source_dates={covered}; "
        f"missing={missing}; backfill_unlock={backfill_ready}; non_synthetic_sources={len(non_synth)}; "
        f"synthetic_sources={len(synth)}; all_authorized={all_authorized}; license_refs_present={all_licensed}"
    )
    checks.append(GateCheck("G2_REAL_MARKET_DATA", "market_data", ok, "READY" if ok else "BLOCKED", detail))


def _temporal_feature_checks(checks: list[GateCheck], base_features: Path, graph_features: Path) -> None:
    base_rows = _read_csv(base_features)
    graph_rows = _read_csv(graph_features)
    base_fields = set(base_rows[0].keys()) if base_rows else set()
    graph_fields = set(graph_rows[0].keys()) if graph_rows else set()
    forbidden = sorted((base_fields | graph_fields) & FORBIDDEN_LIVE_FIELDS)
    live_only = bool(graph_rows) and all((r.get("visibility_mode") or "") == "live_surveillance" for r in graph_rows)
    research_only = bool(base_rows) and bool(graph_rows) and all((r.get("research_use_only") or "1") in {"1", "true", "True"} for r in base_rows + graph_rows)
    ok = bool(base_rows) and bool(graph_rows) and not forbidden and live_only and research_only
    checks.append(GateCheck(
        "G7_TEMPORAL_FEATURE_INTEGRITY", "temporal_integrity", ok, "READY" if ok else "BLOCKED",
        f"base_rows={len(base_rows)}; graph_rows={len(graph_rows)}; forbidden_fields={forbidden}; graph_live_only={live_only}; research_only={research_only}",
    ))


def _holdout_checks(checks: list[GateCheck], matched_controls: Path, base_features: Path, champion_manifest: dict,
                    challenger_manifest: dict, challenger_cv_audit: dict, holdout_start_year: int) -> None:
    try:
        champion_features = tuple(champion_manifest["feature_policy"]["selected_features"])
        base, _ = mt.load_feature_vectors(base_features, selected_features=champion_features)
        matches = mt.load_matched_controls(matched_controls)
        samples, X = mt.build_samples(matches, base)
        dev_idx, hold_idx = mt.split_temporal(samples, X, holdout_start_year=holdout_start_year)
        dev_ids = {samples[i].sample_id for i in dev_idx}
        hold_ids = {samples[i].sample_id for i in hold_idx}
        dev_events = {samples[i].event_id for i in dev_idx}
        hold_events = {samples[i].event_id for i in hold_idx}
        year_ok = all(samples[i].event_year < holdout_start_year for i in dev_idx) and all(samples[i].event_year >= holdout_start_year for i in hold_idx)
        sample_overlap = dev_ids & hold_ids
        event_overlap = dev_events & hold_events
    except Exception as exc:
        checks.append(GateCheck("G8_HOLDOUT_ISOLATION", "validation", False, "AUDIT_ERROR", str(exc)))
        return

    cpol = champion_manifest.get("validation_policy") or {}
    chpol = challenger_manifest.get("validation_policy") or {}
    threshold_dev_only = "development" in str((champion_manifest.get("model") or {}).get("threshold_selection", "")).lower()
    calibration_dev_only = "development" in str((champion_manifest.get("model") or {}).get("calibration", "")).lower()
    cv_zero = bool(challenger_cv_audit.get("all_group_overlap_counts_zero")) and int(cpol.get("cv_group_overlap_count", 1) or 0) == 0
    manifests_agree = int(cpol.get("holdout_start_year", -1)) == holdout_start_year and int(chpol.get("holdout_start_year", -1)) == holdout_start_year
    ok = year_ok and not sample_overlap and not event_overlap and threshold_dev_only and calibration_dev_only and cv_zero and manifests_agree
    checks.append(GateCheck(
        "G8_HOLDOUT_ISOLATION", "validation", ok, "READY" if ok else "BLOCKED",
        f"dev_rows={len(dev_idx)}; holdout_rows={len(hold_idx)}; sample_overlap={len(sample_overlap)}; event_overlap={len(event_overlap)}; "
        f"year_split_ok={year_ok}; threshold_dev_only={threshold_dev_only}; calibration_dev_only={calibration_dev_only}; cv_group_overlap_zero={cv_zero}; manifests_agree={manifests_agree}",
    ))


def assess_release(*, coverage_summary: Path, market_backfill_manifest: Path, market_contract: Path,
                   historical_events: Path, metadata_readiness: Path, metadata_quality: Path,
                   matched_controls: Path, base_features: Path, graph_features: Path,
                   champion_bundle: Path, champion_training_manifest: Path,
                   challenger_manifest: Path, challenger_cv_audit: Path, output_dir: Path,
                   expected_champion_sha256: str = "", holdout_start_year: int = 2015) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    checks: list[GateCheck] = []

    coverage = _read_json(coverage_summary)
    market = _read_json(market_backfill_manifest)
    readiness = _read_json(metadata_readiness)
    quality = _read_json(metadata_quality)
    champion_training = _read_json(champion_training_manifest)
    challenger = _read_json(challenger_manifest)
    cv_audit = _read_json(challenger_cv_audit)

    # G1-G6: independent data/readiness gates.
    _metadata_checks(checks, readiness, quality)
    _market_checks(checks, coverage, market)

    # G7: no future/forensic feature leakage.
    _temporal_feature_checks(checks, base_features, graph_features)

    # G8: development/holdout/CV isolation.
    _holdout_checks(checks, matched_controls, base_features, champion_training, challenger, cv_audit, holdout_start_year)

    # G9: provenance hashes connect the release inputs to their manifests.
    prov_ok = True
    prov_ok &= _check_hash(checks, "G9_PROVENANCE", "provenance", historical_events, str(market.get("historical_events_sha256", "")), "historical events / market manifest")
    prov_ok &= _check_hash(checks, "G9_PROVENANCE", "provenance", historical_events, str(coverage.get("events_sha256", "")), "historical events / coverage plan")
    prov_ok &= _check_hash(checks, "G9_PROVENANCE", "provenance", historical_events, str(readiness.get("events_sha256", "")), "historical events / metadata resolver")
    prov_ok &= _check_hash(checks, "G9_PROVENANCE", "provenance", market_contract, str(market.get("contract_sha256", "")), "market source contract / backfill manifest")
    prov_ok &= _check_hash(checks, "G9_PROVENANCE", "provenance", market_contract, str((coverage.get("contract_audit") or {}).get("contract_sha256", "")), "market source contract / coverage plan")
    prov_ok &= _check_hash(checks, "G9_PROVENANCE", "provenance", metadata_readiness, str(quality.get("resolver_summary_sha256", "")), "metadata resolver summary / quality gate")
    prov_ok &= _check_hash(checks, "G9_PROVENANCE", "provenance", matched_controls, str((challenger.get("inputs") or {}).get("matched_controls_sha256", "")), "matched controls / challenger manifest")
    prov_ok &= _check_hash(checks, "G9_PROVENANCE", "provenance", matched_controls, str((champion_training.get("inputs") or {}).get("matched_controls_sha256", "")), "matched controls / champion manifest")
    prov_ok &= _check_hash(checks, "G9_PROVENANCE", "provenance", base_features, str((challenger.get("inputs") or {}).get("base_feature_vectors_sha256", "")), "base feature vectors / challenger manifest")
    prov_ok &= _check_hash(checks, "G9_PROVENANCE", "provenance", base_features, str((champion_training.get("inputs") or {}).get("feature_vectors_sha256", "")), "base feature vectors / champion manifest")
    prov_ok &= _check_hash(checks, "G9_PROVENANCE", "provenance", graph_features, str((challenger.get("inputs") or {}).get("graph_feature_vectors_sha256", "")), "graph feature vectors / challenger manifest")
    checks.append(GateCheck("G9_PROVENANCE_SUMMARY", "provenance", bool(prov_ok), "READY" if prov_ok else "BLOCKED", "all release input hashes must match the producing manifests"))

    # G10: active champion must be immutable and match every recorded reference.
    champion_actual = _sha256(champion_bundle)
    recorded_before = str((challenger.get("inputs") or {}).get("champion_bundle_sha256_before", ""))
    recorded_after = str((challenger.get("inputs") or {}).get("champion_bundle_sha256_after", ""))
    expected = expected_champion_sha256 or recorded_before
    champ_ok = bool(expected) and champion_actual == expected == recorded_before == recorded_after and not bool(challenger.get("active_champion_modified"))
    checks.append(GateCheck(
        "G10_CHAMPION_IMMUTABILITY", "model_integrity", champ_ok, "READY" if champ_ok else "BLOCKED",
        f"actual={champion_actual}; expected={expected}; challenger_before={recorded_before}; challenger_after={recorded_after}; active_champion_modified={challenger.get('active_champion_modified')}",
    ))

    # G11: this controller can only release a research-only, non-synthetic evaluation.
    research_flags = [
        bool(coverage.get("research_use_only")), bool(market.get("research_use_only")),
        bool(readiness.get("research_use_only")), bool(quality.get("research_use_only")),
        bool(champion_training.get("research_use_only")), bool(challenger.get("research_use_only")),
    ]
    synthetic_detected = bool(challenger.get("synthetic_fixture_detected"))
    prohibited = [str(x) for x in challenger.get("prohibited_outputs", [])]
    norm = [x.lower().replace("_", "").replace("-", "").replace("/", "").replace(" ", "") for x in prohibited]
    required_concepts = ["buy", "sell", "expectedreturn", "targetprice", "positionsize"]
    no_trade_outputs = bool(prohibited) and all(any(req in item for item in norm) for req in required_concepts) and any("order" in item for item in norm)
    non_synth_ok = all(research_flags) and not synthetic_detected and bool(quality.get("quality_cleared_for_non_synthetic_model_evaluation")) and no_trade_outputs
    checks.append(GateCheck(
        "G11_NON_SYNTHETIC_RESEARCH_ONLY", "policy", non_synth_ok, "READY" if non_synth_ok else "BLOCKED",
        f"all_research_only={all(research_flags)}; synthetic_fixture_detected={synthetic_detected}; metadata_non_synthetic_clear={quality.get('quality_cleared_for_non_synthetic_model_evaluation')}; prohibited_outputs_policy_present={no_trade_outputs}",
    ))

    blocking_failures = [c for c in checks if c.blocking and not c.passed]
    released = len(blocking_failures) == 0
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    assessment = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Fail-closed release controller for a non-synthetic offline historical MNPI/informed-trading surveillance model comparison; no trading outputs.",
        "generated_at_utc": now,
        "research_use_only": True,
        "evaluation_release_permitted": released,
        "release_status": "RELEASED_FOR_OFFLINE_HISTORICAL_EVALUATION" if released else "BLOCKED",
        "blocking_failure_count": len(blocking_failures),
        "blocking_failures": [{"gate_id": c.gate_id, "code": c.code, "detail": c.detail} for c in blocking_failures],
        "check_count": len(checks),
        "passed_check_count": sum(c.passed for c in checks),
        "champion_sha256": champion_actual,
        "holdout_start_year": holdout_start_year,
        "input_hashes": {
            "coverage_summary": _sha256(coverage_summary),
            "market_backfill_manifest": _sha256(market_backfill_manifest),
            "metadata_readiness": _sha256(metadata_readiness),
            "metadata_quality": _sha256(metadata_quality),
            "champion_training_manifest": _sha256(champion_training_manifest),
            "challenger_manifest": _sha256(challenger_manifest),
            "challenger_cv_audit": _sha256(challenger_cv_audit),
            "matched_controls": _sha256(matched_controls),
            "base_features": _sha256(base_features),
            "graph_features": _sha256(graph_features),
        },
        "release_semantics": {
            "permits": "one offline historical champion/challenger surveillance evaluation using exactly the hashed inputs",
            "does_not_permit": ["model auto-promotion", "broker connection", "order generation", "trade recommendation", "live confidential-data ingestion"],
            "automatic_promotion_permitted": False,
            "active_champion_modification_permitted": False,
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    _write_checks(output_dir / "evaluation_release_checks.csv", checks)
    (output_dir / "evaluation_release_assessment.json").write_text(json.dumps(assessment, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    token_path = output_dir / "evaluation_release_token.json"
    if released:
        token_payload = {
            "schema_version": SCHEMA_VERSION,
            "issued_at_utc": now,
            "research_use_only": True,
            "scope": "single_offline_historical_champion_challenger_evaluation",
            "assessment_sha256": _sha256(output_dir / "evaluation_release_assessment.json"),
            "champion_sha256": champion_actual,
            "input_hashes": assessment["input_hashes"],
            "automatic_promotion_permitted": False,
            "active_champion_modification_permitted": False,
            "prohibited_outputs": PROHIBITED_OUTPUTS,
        }
        (token_path).write_text(json.dumps(token_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        assessment["release_token"] = token_path.name
    else:
        token_path.unlink(missing_ok=True)
        assessment["release_token"] = None
    return assessment


def run_if_released(*, release_kwargs: dict, evaluation_output_dir: Path, target_fpr: float = 0.05, cv_folds: int = 4) -> dict:
    assessment = assess_release(**release_kwargs)
    if not assessment["evaluation_release_permitted"]:
        raise RuntimeError("evaluation release is BLOCKED; see evaluation_release_assessment.json")
    champion_bundle = Path(release_kwargs["champion_bundle"])
    before = _sha256(champion_bundle)
    result = gch.train_challenger(
        matched_controls=Path(release_kwargs["matched_controls"]),
        base_feature_vectors=Path(release_kwargs["base_features"]),
        graph_feature_vectors=Path(release_kwargs["graph_features"]),
        champion_bundle=champion_bundle,
        output_dir=evaluation_output_dir,
        holdout_start_year=int(release_kwargs.get("holdout_start_year", 2015)),
        target_fpr=target_fpr,
        cv_folds=cv_folds,
    )
    after = _sha256(champion_bundle)
    if after != before:
        raise AssertionError("active champion changed during released evaluation")
    result["step20_release_assessment_sha256"] = _sha256(Path(release_kwargs["output_dir"]) / "evaluation_release_assessment.json")
    result["step20_champion_sha256_before"] = before
    result["step20_champion_sha256_after"] = after
    result["step20_controller_research_use_only"] = True
    result["step20_automatic_promotion_permitted"] = False
    (evaluation_output_dir / "step20_controlled_evaluation_manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Fail-closed controller for non-synthetic offline historical surveillance evaluation")
    p.add_argument("--coverage-summary", type=Path, required=True)
    p.add_argument("--market-backfill-manifest", type=Path, required=True)
    p.add_argument("--market-contract", type=Path, required=True)
    p.add_argument("--historical-events", type=Path, required=True)
    p.add_argument("--metadata-readiness", type=Path, required=True)
    p.add_argument("--metadata-quality", type=Path, required=True)
    p.add_argument("--matched-controls", type=Path, required=True)
    p.add_argument("--base-features", type=Path, required=True)
    p.add_argument("--graph-features", type=Path, required=True)
    p.add_argument("--champion-bundle", type=Path, required=True)
    p.add_argument("--champion-training-manifest", type=Path, required=True)
    p.add_argument("--challenger-manifest", type=Path, required=True)
    p.add_argument("--challenger-cv-audit", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--expected-champion-sha256", default="")
    p.add_argument("--holdout-start-year", type=int, default=2015)
    a = p.parse_args()
    result = assess_release(
        coverage_summary=a.coverage_summary, market_backfill_manifest=a.market_backfill_manifest,
        market_contract=a.market_contract, historical_events=a.historical_events,
        metadata_readiness=a.metadata_readiness, metadata_quality=a.metadata_quality,
        matched_controls=a.matched_controls, base_features=a.base_features, graph_features=a.graph_features,
        champion_bundle=a.champion_bundle, champion_training_manifest=a.champion_training_manifest,
        challenger_manifest=a.challenger_manifest, challenger_cv_audit=a.challenger_cv_audit,
        output_dir=a.output_dir, expected_champion_sha256=a.expected_champion_sha256,
        holdout_start_year=a.holdout_start_year,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
