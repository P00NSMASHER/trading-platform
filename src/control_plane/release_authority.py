from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import integrity, signature_trust, storage

SCHEMA_VERSION = "1"
AUTHORITY_NAMESPACE = "mnpi-release-authority"
AUTHORITY_SCOPE = "single_offline_historical_champion_challenger_evaluation"
PROHIBITED_CAPABILITIES = [
    "model_auto_promotion",
    "active_champion_modification",
    "broker_connectivity",
    "order_generation",
    "trade_recommendations",
    "position_sizing",
    "expected_return_outputs",
    "live_confidential_data_ingestion",
]


@dataclass(frozen=True)
class ExtendedGateCheck:
    gate_id: str
    category: str
    passed: bool
    code: str
    detail: str
    blocking: bool = True
    research_use_only: int = 1


def _read_json(path: Path) -> dict:
    obj=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj,dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return obj


def _canonical(obj: object) -> bytes:
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")


def _json_sha256(obj: object) -> str:
    return hashlib.sha256(_canonical(obj)).hexdigest()


def _norm(values: list[str]) -> list[str]:
    return [str(x).lower().replace("_","").replace("-","").replace("/","").replace(" ","") for x in values]


def _prohibited_output_policy_present(values: list[str]) -> bool:
    norm=_norm(values)
    required=("buy","sell","expectedreturn","targetprice","positionsize")
    return bool(norm) and all(any(req in item for item in norm) for req in required) and any("order" in item for item in norm)


def _stable_legacy_assessment(legacy: dict) -> dict:
    out=dict(legacy)
    out.pop("generated_at_utc",None)
    out.pop("release_token",None)
    return out


def _legacy_ready(legacy: dict) -> bool:
    return (
        legacy.get("evaluation_release_permitted") is True
        and str(legacy.get("release_status",""))=="RELEASED_FOR_OFFLINE_HISTORICAL_EVALUATION"
        and int(legacy.get("blocking_failure_count",1) or 0)==0
        and not legacy.get("blocking_failures")
        and legacy.get("research_use_only") is True
    )


def _graph_feature_gate(manifest: dict, graph_features: Path, legacy: dict) -> ExtendedGateCheck:
    policy=manifest.get("point_in_time_policy") or {}
    legacy_hash=str((legacy.get("input_hashes") or {}).get("graph_features",""))
    actual_hash=storage.sha256_file(graph_features) if Path(graph_features).is_file() else ""
    prohibited=[str(x) for x in manifest.get("prohibited_outputs",[])]
    ok=bool(
        str(manifest.get("schema_version","")).startswith("0.12.")
        and manifest.get("research_use_only") is True
        and manifest.get("visibility_mode")=="live_surveillance"
        and policy.get("edge_must_be_observed_by_scoring_time") is True
        and policy.get("live_mode_requires_public_at_or_before_scoring_time") is True
        and policy.get("later_enforcement_facts_excluded_from_live_features") is True
        and _prohibited_output_policy_present(prohibited)
        and legacy_hash
        and actual_hash==legacy_hash
    )
    detail=(
        f"schema={manifest.get('schema_version')}; visibility_mode={manifest.get('visibility_mode')}; "
        f"observed_at_gate={policy.get('edge_must_be_observed_by_scoring_time')}; "
        f"public_at_gate={policy.get('live_mode_requires_public_at_or_before_scoring_time')}; "
        f"later_enforcement_excluded={policy.get('later_enforcement_facts_excluded_from_live_features')}; "
        f"graph_features_hash_matches_legacy={bool(legacy_hash and actual_hash==legacy_hash)}"
    )
    return ExtendedGateCheck("G12_POINT_IN_TIME_GRAPH_FEATURES","graph_features",ok,"READY" if ok else "BLOCKED",detail)


def _challenger_gate(challenger: dict, cv_audit: dict, legacy: dict, expected_champion_sha256: str) -> ExtendedGateCheck:
    promotion=challenger.get("promotion") or {}
    checks=promotion.get("checks") or {}
    required_checks=("temporal_ap_gain","graph_ablation_gain","false_alert_guardrail","brier_guardrail","unseen_issuer_not_worse")
    validation=challenger.get("validation_policy") or {}
    inputs=challenger.get("inputs") or {}
    legacy_hash=str((legacy.get("input_hashes") or {}).get("challenger_manifest",""))
    cv_legacy_hash=str((legacy.get("input_hashes") or {}).get("challenger_cv_audit",""))
    all_required=all(checks.get(name) is True for name in required_checks)
    overlap_zero=(
        cv_audit.get("all_group_overlap_counts_zero") is True
        and int(validation.get("challenger_cv_group_overlap_count",1) or 0)==0
        and int(validation.get("base_ablation_cv_group_overlap_count",1) or 0)==0
    )
    champion_before=str(inputs.get("champion_bundle_sha256_before",""))
    champion_after=str(inputs.get("champion_bundle_sha256_after",""))
    actual_manifest_hash=_json_file_hash_from_loaded(challenger)
    actual_cv_hash=_json_file_hash_from_loaded(cv_audit)
    ok=bool(
        str(challenger.get("schema_version","")).startswith("0.13.")
        and challenger.get("research_use_only") is True
        and challenger.get("synthetic_fixture_detected") is False
        and challenger.get("active_champion_modified") is False
        and promotion.get("eligible_for_human_promotion_review") is True
        and promotion.get("active_model_changed") is False
        and promotion.get("automatic_promotion_permitted") is False
        and all_required
        and overlap_zero
        and expected_champion_sha256
        and champion_before==expected_champion_sha256==champion_after
        and legacy_hash==actual_manifest_hash
        and cv_legacy_hash==actual_cv_hash
    )
    detail=(
        f"synthetic={challenger.get('synthetic_fixture_detected')}; eligible_for_human_review={promotion.get('eligible_for_human_promotion_review')}; "
        f"required_guardrails={all_required}; cv_overlap_zero={overlap_zero}; champion_unchanged={champion_before==champion_after==expected_champion_sha256}; "
        f"manifest_hash_matches_legacy={legacy_hash==actual_manifest_hash}; cv_hash_matches_legacy={cv_legacy_hash==actual_cv_hash}"
    )
    return ExtendedGateCheck("G13_GRAPH_CHALLENGER_GUARDRAILS","challenger",ok,"READY" if ok else "BLOCKED",detail)


def _historical_graph_gate(self_check: dict, market_manifest: dict) -> ExtendedGateCheck:
    graph=self_check.get("graph_manifest") or {}
    point=graph.get("point_in_time_policy") or {}
    source_policy=self_check.get("source_policy") or {}
    audit=self_check.get("context_audit") or {}
    readiness=self_check.get("comparison_readiness") or {}
    corpus=self_check.get("historical_event_corpus") or {}
    rows=int(audit.get("rows",0) or 0)
    same_events=bool(corpus.get("input_sha256")) and corpus.get("input_sha256")==market_manifest.get("historical_events_sha256")
    ok=bool(
        str(self_check.get("schema_version","")).startswith("0.14.")
        and self_check.get("research_use_only") is True
        and graph.get("research_use_only") is True
        and point.get("future_enforcement_information_not_live_visible") is True
        and point.get("live_surveillance_uses_public_at") is True
        and source_policy.get("future_enforcement_facts_hidden_from_live_historical_queries") is True
        and source_policy.get("live_stolen_or_private_inputs_allowed") is False
        and rows>0
        and int(audit.get("live_case_visible_rows",-1))==0
        and int(audit.get("forensic_case_visible_rows",0))==rows
        and readiness.get("eligible_for_non_synthetic_champion_challenger_comparison") is True
        and readiness.get("active_champion_changed") is False
        and same_events
    )
    detail=(
        f"rows={rows}; live_case_visible_rows={audit.get('live_case_visible_rows')}; "
        f"forensic_case_visible_rows={audit.get('forensic_case_visible_rows')}; "
        f"comparison_ready={readiness.get('eligible_for_non_synthetic_champion_challenger_comparison')}; "
        f"same_historical_events={same_events}; active_champion_changed={readiness.get('active_champion_changed')}"
    )
    return ExtendedGateCheck("G14_REAL_HISTORICAL_GRAPH","historical_graph",ok,"READY" if ok else "BLOCKED",detail)


def _market_backfill_gate(market: dict, market_path: Path, legacy: dict) -> ExtendedGateCheck:
    readiness=market.get("non_synthetic_comparison_readiness") or {}
    policy=market.get("source_contract_policy") or {}
    micro=market.get("microstructure_policy") or {}
    sources=market.get("source_contracts") or []
    nonsynth=[s for s in sources if s.get("data_classification")=="authorized_historical_market_data"]
    synth=[s for s in sources if s.get("data_classification")=="synthetic_fixture"]
    all_authorized=bool(nonsynth) and all(s.get("authorized") is True for s in nonsynth)
    all_licensed=bool(nonsynth) and all(bool(str(s.get("license_reference","")).strip()) for s in nonsynth)
    legacy_hash=str((legacy.get("input_hashes") or {}).get("market_backfill_manifest",""))
    actual_hash=storage.sha256_file(market_path) if Path(market_path).is_file() else ""
    ok=bool(
        str(market.get("schema_version","")).startswith("0.15.")
        and market.get("research_use_only") is True
        and readiness.get("eligible_for_real_feature_backfill") is True
        and readiness.get("eligible_for_champion_challenger_unlock") is True
        and policy.get("authorization_required") is True
        and policy.get("credentials_stored_in_contract") is False
        and micro.get("future_5m_fields_forbidden_from_live_model") is True
        and micro.get("price_impact_5m_posthoc_only") is True
        and micro.get("realized_spread_5m_posthoc_only") is True
        and bool(nonsynth)
        and not synth
        and all_authorized
        and all_licensed
        and _prohibited_output_policy_present([str(x) for x in market.get("prohibited_outputs",[])])
        and legacy_hash
        and actual_hash==legacy_hash
    )
    detail=(
        f"feature_backfill_ready={readiness.get('eligible_for_real_feature_backfill')}; "
        f"challenger_unlock={readiness.get('eligible_for_champion_challenger_unlock')}; "
        f"authorized_non_synthetic_sources={len(nonsynth)}; synthetic_sources={len(synth)}; "
        f"all_authorized={all_authorized}; all_license_refs={all_licensed}; hash_matches_legacy={bool(legacy_hash and actual_hash==legacy_hash)}"
    )
    return ExtendedGateCheck("G15_AUTHORIZED_MARKET_BACKFILL","market_backfill",ok,"READY" if ok else "BLOCKED",detail)


def _json_file_hash_from_loaded(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj,indent=2,sort_keys=False).encode("utf-8")).hexdigest()


def assess_g12_g15(
    *,
    legacy_assessment: Path,
    graph_feature_manifest: Path,
    graph_features: Path,
    challenger_manifest: Path,
    challenger_cv_audit: Path,
    historical_graph_self_check: Path,
    market_backfill_manifest: Path,
    control_dir: Path,
    expected_champion_sha256: str,
) -> dict:
    legacy_path=Path(legacy_assessment)
    graph_feature_path=Path(graph_feature_manifest)
    graph_features=Path(graph_features)
    challenger_path=Path(challenger_manifest)
    cv_path=Path(challenger_cv_audit)
    graph_self_path=Path(historical_graph_self_check)
    market_path=Path(market_backfill_manifest)
    control_dir=Path(control_dir).resolve()

    legacy=_read_json(legacy_path)
    gf=_read_json(graph_feature_path)
    challenger=_read_json(challenger_path)
    cv=_read_json(cv_path)
    graph_self=_read_json(graph_self_path)
    market=_read_json(market_path)

    # Bind loaded JSON to the exact files rather than serializer assumptions.
    legacy_inputs=legacy.get("input_hashes") or {}
    challenger_hash_ok=storage.sha256_file(challenger_path)==str(legacy_inputs.get("challenger_manifest",""))
    cv_hash_ok=storage.sha256_file(cv_path)==str(legacy_inputs.get("challenger_cv_audit",""))
    if not challenger_hash_ok:
        challenger=dict(challenger); challenger["__legacy_hash_mismatch__"]=True
    if not cv_hash_ok:
        cv=dict(cv); cv["__legacy_hash_mismatch__"]=True

    checks=[
        _graph_feature_gate(gf,graph_features,legacy),
        _challenger_gate_bound(challenger,cv,legacy,expected_champion_sha256,challenger_hash_ok,cv_hash_ok),
        _historical_graph_gate(graph_self,market),
        _market_backfill_gate(market,market_path,legacy),
    ]
    control_report=integrity.verify_control_plane(control_dir/"control.sqlite",control_dir)
    failures=[asdict(c) for c in checks if c.blocking and not c.passed]
    legacy_ok=_legacy_ready(legacy)
    control_ok=bool(control_report.get("ok"))
    ready=bool(legacy_ok and control_ok and not failures)
    return {
        "schema_version":SCHEMA_VERSION,
        "purpose":"G12-G15 extension and control-plane prerequisite for one offline historical surveillance evaluation.",
        "research_use_only":True,
        "legacy_g1_g11_ready":legacy_ok,
        "legacy_assessment_sha256":_json_sha256(_stable_legacy_assessment(legacy)),
        "control_plane_integrity_ok":control_ok,
        "control_plane_integrity":control_report,
        "g12_g15_ready":not failures,
        "preauthority_release_ready":ready,
        "checks":[asdict(c) for c in checks],
        "blocking_failures":failures,
        "champion_sha256":str(legacy.get("champion_sha256","")),
        "expected_champion_sha256":str(expected_champion_sha256),
        "input_hashes":dict(legacy_inputs),
        "evidence_hashes":{
            "graph_feature_manifest":storage.sha256_file(graph_feature_path),
            "graph_features":storage.sha256_file(graph_features),
            "challenger_manifest":storage.sha256_file(challenger_path),
            "challenger_cv_audit":storage.sha256_file(cv_path),
            "historical_graph_self_check":storage.sha256_file(graph_self_path),
            "market_backfill_manifest":storage.sha256_file(market_path),
        },
        "automatic_promotion_permitted":False,
        "active_champion_modification_permitted":False,
        "prohibited_capabilities":PROHIBITED_CAPABILITIES,
    }


def _challenger_gate_bound(challenger: dict, cv: dict, legacy: dict, expected: str, manifest_hash_ok: bool, cv_hash_ok: bool) -> ExtendedGateCheck:
    promotion=challenger.get("promotion") or {}
    pchecks=promotion.get("checks") or {}
    validation=challenger.get("validation_policy") or {}
    inputs=challenger.get("inputs") or {}
    required=("temporal_ap_gain","graph_ablation_gain","false_alert_guardrail","brier_guardrail","unseen_issuer_not_worse")
    all_required=all(pchecks.get(k) is True for k in required)
    overlap_zero=(
        cv.get("all_group_overlap_counts_zero") is True
        and int(validation.get("challenger_cv_group_overlap_count",1) or 0)==0
        and int(validation.get("base_ablation_cv_group_overlap_count",1) or 0)==0
    )
    before=str(inputs.get("champion_bundle_sha256_before","")); after=str(inputs.get("champion_bundle_sha256_after",""))
    ok=bool(
        str(challenger.get("schema_version","")).startswith("0.13.")
        and challenger.get("research_use_only") is True
        and challenger.get("synthetic_fixture_detected") is False
        and challenger.get("active_champion_modified") is False
        and promotion.get("eligible_for_human_promotion_review") is True
        and promotion.get("active_model_changed") is False
        and promotion.get("automatic_promotion_permitted") is False
        and all_required and overlap_zero and expected and before==expected==after
        and manifest_hash_ok and cv_hash_ok
    )
    return ExtendedGateCheck(
        "G13_GRAPH_CHALLENGER_GUARDRAILS","challenger",ok,"READY" if ok else "BLOCKED",
        f"synthetic={challenger.get('synthetic_fixture_detected')}; eligible_for_human_review={promotion.get('eligible_for_human_promotion_review')}; "
        f"required_guardrails={all_required}; cv_overlap_zero={overlap_zero}; champion_unchanged={before==after==expected}; "
        f"manifest_hash_matches_legacy={manifest_hash_ok}; cv_hash_matches_legacy={cv_hash_ok}",
    )


def write_assessment(path: Path, assessment: dict) -> Path:
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(assessment,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    try: path.chmod(0o600)
    except OSError: pass
    return path


def build_authority_claim(*, assessment: dict) -> dict:
    if assessment.get("preauthority_release_ready") is not True:
        raise ValueError("G1-G15/control-plane prerequisites are not ready; refusing to build release authority claim")
    if assessment.get("champion_sha256")!=assessment.get("expected_champion_sha256"):
        raise ValueError("champion hash does not equal the expected frozen champion")
    return {
        "schema_version":SCHEMA_VERSION,
        "authority_type":"offline_historical_surveillance_evaluation",
        "signature_namespace":AUTHORITY_NAMESPACE,
        "scope":AUTHORITY_SCOPE,
        "g12_g15_assessment_sha256":_json_sha256(assessment),
        "legacy_assessment_sha256":assessment["legacy_assessment_sha256"],
        "champion_sha256":assessment["champion_sha256"],
        "input_hashes":assessment["input_hashes"],
        "evidence_hashes":assessment["evidence_hashes"],
        "control_plane_integrity_required":True,
        "research_use_only":True,
        "automatic_promotion_permitted":False,
        "active_champion_modification_permitted":False,
        "prohibited_capabilities":PROHIBITED_CAPABILITIES,
    }


def write_claim(path: Path, claim: dict) -> Path:
    if claim.get("signature_namespace")!=AUTHORITY_NAMESPACE:
        raise ValueError("invalid release-authority signature namespace")
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(claim,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    try: path.chmod(0o600)
    except OSError: pass
    return path


def sign_claim(*, root: Path, claim: Path, private_key: Path) -> Path:
    raw=_read_json(claim)
    if raw.get("signature_namespace")!=AUTHORITY_NAMESPACE:
        raise ValueError("invalid release-authority signature namespace")
    return signature_trust.sign_file(root=root,payload=claim,private_key=private_key,namespace=AUTHORITY_NAMESPACE)


def _archive_authority(control_dir: Path, claim_bytes: bytes, signature_bytes: bytes) -> tuple[str,Path]:
    digest=signature_trust.sha256_bytes(claim_bytes)
    root=Path(control_dir).resolve()/"release_authority"/digest
    root.mkdir(parents=True,exist_ok=True)
    claim_path=root/"authority.json"; sig_path=root/"authority.json.sig"
    if claim_path.exists() and claim_path.read_bytes()!=claim_bytes:
        raise ValueError("existing release authority claim differs for its content hash")
    if sig_path.exists() and sig_path.read_bytes()!=signature_bytes:
        raise ValueError("existing release authority signature differs for the same claim")
    claim_path.write_bytes(claim_bytes); sig_path.write_bytes(signature_bytes)
    try: claim_path.chmod(0o600); sig_path.chmod(0o600); root.chmod(0o700)
    except OSError: pass
    if storage.sha256_file(claim_path)!=digest:
        raise ValueError("archived release authority claim hash mismatch")
    return digest,claim_path


def verify_signed_authority(
    *,
    root: Path,
    claim: Path,
    signature: Path,
    allowed_signers: Path,
    expected_allowed_signers_sha256: str,
    identity: str,
    assessment_kwargs: dict,
    champion_bundle: Path,
) -> dict:
    claim_bytes=Path(claim).read_bytes(); signature_bytes=Path(signature).read_bytes()
    try: raw=json.loads(claim_bytes.decode("utf-8"))
    except Exception as exc: raise ValueError("release authority claim must be valid UTF-8 JSON") from exc
    if not isinstance(raw,dict): raise ValueError("release authority claim root must be an object")
    if raw.get("signature_namespace")!=AUTHORITY_NAMESPACE:
        raise ValueError("invalid release-authority signature namespace")
    control_dir=Path(assessment_kwargs["control_dir"]).resolve()
    allowed_hash=signature_trust.verify_bytes(
        root=root,control_dir=control_dir,payload=claim_bytes,signature=signature_bytes,
        allowed_signers=allowed_signers,expected_allowed_signers_sha256=expected_allowed_signers_sha256,
        identity=identity,namespace=AUTHORITY_NAMESPACE,
    )
    assessment=assess_g12_g15(**assessment_kwargs)
    if assessment.get("preauthority_release_ready") is not True:
        raise PermissionError("G1-G15/control-plane prerequisites no longer pass")
    if raw.get("schema_version")!=SCHEMA_VERSION or raw.get("authority_type")!="offline_historical_surveillance_evaluation":
        raise ValueError("unsupported release authority claim")
    if raw.get("scope")!=AUTHORITY_SCOPE or raw.get("research_use_only") is not True:
        raise ValueError("release authority claim has invalid scope/policy")
    if raw.get("automatic_promotion_permitted") is not False or raw.get("active_champion_modification_permitted") is not False:
        raise ValueError("release authority must forbid automatic promotion and champion modification")
    if set(PROHIBITED_CAPABILITIES)-set(raw.get("prohibited_capabilities",[])):
        raise ValueError("release authority claim is missing prohibited capabilities")
    if raw.get("g12_g15_assessment_sha256")!=_json_sha256(assessment):
        raise ValueError("release authority claim is stale for the current G12-G15 assessment")
    if raw.get("legacy_assessment_sha256")!=assessment.get("legacy_assessment_sha256"):
        raise ValueError("release authority claim is bound to a different G1-G11 assessment")
    if raw.get("champion_sha256")!=assessment.get("champion_sha256"):
        raise ValueError("release authority champion hash differs from assessment")
    if storage.sha256_file(champion_bundle)!=raw.get("champion_sha256"):
        raise ValueError("active champion bytes do not match release authority")
    if raw.get("input_hashes")!=assessment.get("input_hashes") or raw.get("evidence_hashes")!=assessment.get("evidence_hashes"):
        raise ValueError("release authority input/evidence hashes are stale")
    claim_sha,archived=_archive_authority(control_dir,claim_bytes,signature_bytes)
    token={
        "schema_version":SCHEMA_VERSION,
        "scope":AUTHORITY_SCOPE,
        "authority_claim_sha256":claim_sha,
        "authority_signature_verified":True,
        "signer_identity":str(identity).strip(),
        "allowed_signers_sha256":allowed_hash,
        "g12_g15_assessment_sha256":_json_sha256(assessment),
        "legacy_assessment_sha256":assessment["legacy_assessment_sha256"],
        "champion_sha256":assessment["champion_sha256"],
        "input_hashes":assessment["input_hashes"],
        "evidence_hashes":assessment["evidence_hashes"],
        "research_use_only":True,
        "automatic_promotion_permitted":False,
        "active_champion_modification_permitted":False,
        "prohibited_capabilities":PROHIBITED_CAPABILITIES,
        "archived_authority_path_fingerprint":storage.path_fingerprint(archived),
    }
    return {"assessment":assessment,"token":token}


def write_token(path: Path, token: dict) -> Path:
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(token,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    try: path.chmod(0o600)
    except OSError: pass
    return path


def verify_execution_token(
    *,
    token: Path,
    root: Path,
    claim: Path,
    signature: Path,
    allowed_signers: Path,
    expected_allowed_signers_sha256: str,
    identity: str,
    assessment_kwargs: dict,
    champion_bundle: Path,
) -> dict:
    stored=_read_json(token)
    verified=verify_signed_authority(
        root=root,claim=claim,signature=signature,allowed_signers=allowed_signers,
        expected_allowed_signers_sha256=expected_allowed_signers_sha256,identity=identity,
        assessment_kwargs=assessment_kwargs,champion_bundle=champion_bundle,
    )
    if stored!=verified["token"]:
        raise PermissionError("release authority token does not match freshly verified authority")
    return stored


def main() -> None:
    p=argparse.ArgumentParser(description="G12-G15 and signed release-authority control")
    p.add_argument("--version",action="store_true")
    args=p.parse_args()
    if args.version:
        print(SCHEMA_VERSION)


if __name__=="__main__":
    main()
