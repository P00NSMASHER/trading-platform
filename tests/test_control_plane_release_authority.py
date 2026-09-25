from __future__ import annotations

import json
from pathlib import Path

import pytest

import evaluation_release_controller as erc
from control_plane import registry, release_authority as ra, signature_trust, storage


def _write_json(path: Path, obj: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    return path


def _positive_fixture(tmp_path: Path) -> dict:
    root=tmp_path/"repo"; root.mkdir()
    control=root/"private_runtime"/"control"; registry.init_db(control/"control.sqlite")

    champion=root/"champion.bin"; champion.write_bytes(b"frozen-champion")
    champion_sha=storage.sha256_file(champion)

    graph_features=root/"graph_features.csv"
    graph_features.write_text("visibility_mode,research_use_only\nlive_surveillance,1\n",encoding="utf-8")

    graph_manifest=_write_json(root/"graph_manifest.json",{
        "schema_version":"0.12.0","research_use_only":True,"visibility_mode":"live_surveillance",
        "point_in_time_policy":{
            "edge_must_be_observed_by_scoring_time":True,
            "live_mode_requires_public_at_or_before_scoring_time":True,
            "later_enforcement_facts_excluded_from_live_features":True,
        },
        "prohibited_outputs":["BUY","SELL","expected_return","target_price","position_size","order_instruction"],
    })

    challenger_obj={
        "schema_version":"0.13.0","research_use_only":True,"synthetic_fixture_detected":False,
        "active_champion_modified":False,
        "inputs":{
            "champion_bundle_sha256_before":champion_sha,
            "champion_bundle_sha256_after":champion_sha,
        },
        "validation_policy":{
            "challenger_cv_group_overlap_count":0,
            "base_ablation_cv_group_overlap_count":0,
        },
        "promotion":{
            "eligible_for_human_promotion_review":True,
            "active_model_changed":False,
            "automatic_promotion_permitted":False,
            "checks":{
                "temporal_ap_gain":True,
                "graph_ablation_gain":True,
                "false_alert_guardrail":True,
                "brier_guardrail":True,
                "unseen_issuer_not_worse":True,
            },
        },
    }
    challenger=_write_json(root/"challenger.json",challenger_obj)
    cv=_write_json(root/"cv.json",{"all_group_overlap_counts_zero":True})

    event_hash="1"*64
    market_obj={
        "schema_version":"0.15.0","research_use_only":True,"historical_events_sha256":event_hash,
        "non_synthetic_comparison_readiness":{
            "eligible_for_real_feature_backfill":True,
            "eligible_for_champion_challenger_unlock":True,
        },
        "source_contract_policy":{
            "authorization_required":True,
            "credentials_stored_in_contract":False,
        },
        "microstructure_policy":{
            "future_5m_fields_forbidden_from_live_model":True,
            "price_impact_5m_posthoc_only":True,
            "realized_spread_5m_posthoc_only":True,
        },
        "source_contracts":[{
            "source_id":"licensed-market",
            "data_classification":"authorized_historical_market_data",
            "authorized":True,
            "license_reference":"ENTITLEMENT-TEST",
        }],
        "prohibited_outputs":["BUY","SELL","expected_return","target_price","position_size","order"],
    }
    market=_write_json(root/"market.json",market_obj)

    graph_self=_write_json(root/"historical_graph_self_check.json",{
        "schema_version":"0.14.0","research_use_only":True,
        "graph_manifest":{
            "research_use_only":True,
            "point_in_time_policy":{
                "future_enforcement_information_not_live_visible":True,
                "live_surveillance_uses_public_at":True,
            },
        },
        "source_policy":{
            "future_enforcement_facts_hidden_from_live_historical_queries":True,
            "live_stolen_or_private_inputs_allowed":False,
        },
        "context_audit":{
            "rows":174,
            "live_case_visible_rows":0,
            "forensic_case_visible_rows":174,
        },
        "comparison_readiness":{
            "eligible_for_non_synthetic_champion_challenger_comparison":True,
            "active_champion_changed":False,
        },
        "historical_event_corpus":{"input_sha256":event_hash},
    })

    legacy_obj={
        "schema_version":"0.20.0",
        "research_use_only":True,
        "evaluation_release_permitted":True,
        "release_status":"RELEASED_FOR_OFFLINE_HISTORICAL_EVALUATION",
        "blocking_failure_count":0,
        "blocking_failures":[],
        "champion_sha256":champion_sha,
        "input_hashes":{
            "graph_features":storage.sha256_file(graph_features),
            "challenger_manifest":storage.sha256_file(challenger),
            "challenger_cv_audit":storage.sha256_file(cv),
            "market_backfill_manifest":storage.sha256_file(market),
        },
        "generated_at_utc":"2026-09-25T18:00:00Z",
    }
    legacy=_write_json(root/"legacy_assessment.json",legacy_obj)

    assessment_kwargs={
        "legacy_assessment":legacy,
        "graph_feature_manifest":graph_manifest,
        "graph_features":graph_features,
        "challenger_manifest":challenger,
        "challenger_cv_audit":cv,
        "historical_graph_self_check":graph_self,
        "market_backfill_manifest":market,
        "control_dir":control,
        "expected_champion_sha256":champion_sha,
    }
    return {
        "root":root,"control":control,"champion":champion,"champion_sha":champion_sha,
        "assessment_kwargs":assessment_kwargs,"legacy":legacy,"graph_manifest":graph_manifest,
        "challenger":challenger,"cv":cv,"graph_self":graph_self,"market":market,
    }


def _trust(tmp_path: Path):
    trust=tmp_path/"external-trust"; trust.mkdir(exist_ok=True)
    allowed=trust/"allowed_signers"
    allowed.write_text("release-reviewer ssh-ed25519 AAAATEST\n",encoding="utf-8")
    return allowed


def _good_ssh(monkeypatch, calls=None):
    def run(args, **kwargs):
        if calls is not None:
            calls.append(args)
        class Result:
            returncode=0
            stdout=b"Good signature"
            stderr=b""
        return Result()
    monkeypatch.setattr(signature_trust.subprocess,"run",run)


def test_g12_g15_positive_fixture_is_preauthority_ready(tmp_path: Path):
    fx=_positive_fixture(tmp_path)
    result=ra.assess_g12_g15(**fx["assessment_kwargs"])
    assert result["legacy_g1_g11_ready"] is True
    assert result["control_plane_integrity_ok"] is True
    assert result["g12_g15_ready"] is True
    assert result["preauthority_release_ready"] is True
    assert [x["gate_id"] for x in result["checks"]]==[
        "G12_POINT_IN_TIME_GRAPH_FEATURES",
        "G13_GRAPH_CHALLENGER_GUARDRAILS",
        "G14_REAL_HISTORICAL_GRAPH",
        "G15_AUTHORIZED_MARKET_BACKFILL",
    ]
    assert all(x["passed"] for x in result["checks"])


def test_g12_forensic_graph_manifest_blocks(tmp_path: Path):
    fx=_positive_fixture(tmp_path)
    raw=json.loads(fx["graph_manifest"].read_text())
    raw["visibility_mode"]="historical_forensics"
    _write_json(fx["graph_manifest"],raw)
    result=ra.assess_g12_g15(**fx["assessment_kwargs"])
    assert result["checks"][0]["passed"] is False
    assert result["preauthority_release_ready"] is False


def test_g13_synthetic_or_failed_ablation_blocks(tmp_path: Path):
    fx=_positive_fixture(tmp_path)
    raw=json.loads(fx["challenger"].read_text())
    raw["synthetic_fixture_detected"]=True
    raw["promotion"]["checks"]["graph_ablation_gain"]=False
    _write_json(fx["challenger"],raw)
    legacy=json.loads(fx["legacy"].read_text())
    legacy["input_hashes"]["challenger_manifest"]=storage.sha256_file(fx["challenger"])
    _write_json(fx["legacy"],legacy)
    result=ra.assess_g12_g15(**fx["assessment_kwargs"])
    g13=next(x for x in result["checks"] if x["gate_id"].startswith("G13_"))
    assert g13["passed"] is False


def test_g14_live_visibility_of_later_enforcement_blocks(tmp_path: Path):
    fx=_positive_fixture(tmp_path)
    raw=json.loads(fx["graph_self"].read_text())
    raw["context_audit"]["live_case_visible_rows"]=1
    _write_json(fx["graph_self"],raw)
    result=ra.assess_g12_g15(**fx["assessment_kwargs"])
    g14=next(x for x in result["checks"] if x["gate_id"].startswith("G14_"))
    assert g14["passed"] is False


def test_g15_synthetic_market_source_blocks(tmp_path: Path):
    fx=_positive_fixture(tmp_path)
    raw=json.loads(fx["market"].read_text())
    raw["source_contracts"][0]["data_classification"]="synthetic_fixture"
    raw["source_contracts"][0]["license_reference"]=""
    _write_json(fx["market"],raw)
    legacy=json.loads(fx["legacy"].read_text())
    legacy["input_hashes"]["market_backfill_manifest"]=storage.sha256_file(fx["market"])
    _write_json(fx["legacy"],legacy)
    result=ra.assess_g12_g15(**fx["assessment_kwargs"])
    g15=next(x for x in result["checks"] if x["gate_id"].startswith("G15_"))
    assert g15["passed"] is False


def test_authority_signature_and_external_signer_trust_are_required(tmp_path: Path, monkeypatch):
    fx=_positive_fixture(tmp_path)
    assessment=ra.assess_g12_g15(**fx["assessment_kwargs"])
    claim=ra.build_authority_claim(assessment=assessment)
    claim_path=ra.write_claim(fx["root"]/"authority.json",claim)
    signature=fx["root"]/"authority.json.sig"; signature.write_bytes(b"fake-signature")
    allowed=_trust(tmp_path)

    called=False
    def no_run(*args, **kwargs):
        nonlocal called
        called=True
        raise AssertionError("ssh-keygen must not run before signer trust hash matches")
    monkeypatch.setattr(signature_trust.subprocess,"run",no_run)
    with pytest.raises(ValueError,match="allowed-signers hash mismatch"):
        ra.verify_signed_authority(
            root=fx["root"],claim=claim_path,signature=signature,allowed_signers=allowed,
            expected_allowed_signers_sha256="0"*64,identity="release-reviewer",
            assessment_kwargs=fx["assessment_kwargs"],champion_bundle=fx["champion"],
        )
    assert called is False


def test_verified_authority_issues_exact_token_and_rejects_stale_evidence(tmp_path: Path, monkeypatch):
    fx=_positive_fixture(tmp_path)
    assessment=ra.assess_g12_g15(**fx["assessment_kwargs"])
    claim_path=ra.write_claim(fx["root"]/"authority.json",ra.build_authority_claim(assessment=assessment))
    signature=fx["root"]/"authority.json.sig"; signature.write_bytes(b"fake-signature")
    allowed=_trust(tmp_path)
    _good_ssh(monkeypatch)

    verified=ra.verify_signed_authority(
        root=fx["root"],claim=claim_path,signature=signature,allowed_signers=allowed,
        expected_allowed_signers_sha256=storage.sha256_file(allowed),identity="release-reviewer",
        assessment_kwargs=fx["assessment_kwargs"],champion_bundle=fx["champion"],
    )
    token_path=ra.write_token(fx["root"]/"release_authority_token.json",verified["token"])
    token=ra.verify_execution_token(
        token=token_path,root=fx["root"],claim=claim_path,signature=signature,allowed_signers=allowed,
        expected_allowed_signers_sha256=storage.sha256_file(allowed),identity="release-reviewer",
        assessment_kwargs=fx["assessment_kwargs"],champion_bundle=fx["champion"],
    )
    assert token["authority_signature_verified"] is True
    assert token["automatic_promotion_permitted"] is False
    assert token["active_champion_modification_permitted"] is False

    raw=json.loads(fx["graph_self"].read_text())
    raw["context_audit"]["live_case_visible_rows"]=2
    _write_json(fx["graph_self"],raw)
    with pytest.raises(PermissionError,match="prerequisites no longer pass"):
        ra.verify_execution_token(
            token=token_path,root=fx["root"],claim=claim_path,signature=signature,allowed_signers=allowed,
            expected_allowed_signers_sha256=storage.sha256_file(allowed),identity="release-reviewer",
            assessment_kwargs=fx["assessment_kwargs"],champion_bundle=fx["champion"],
        )


def test_legacy_timestamp_change_does_not_invalidate_stable_authority_subject(tmp_path: Path):
    fx=_positive_fixture(tmp_path)
    first=ra.assess_g12_g15(**fx["assessment_kwargs"])
    raw=json.loads(fx["legacy"].read_text())
    raw["generated_at_utc"]="2026-09-25T19:00:00Z"
    _write_json(fx["legacy"],raw)
    second=ra.assess_g12_g15(**fx["assessment_kwargs"])
    assert first["legacy_assessment_sha256"]==second["legacy_assessment_sha256"]
    assert ra._json_sha256(first)==ra._json_sha256(second)


def test_run_if_released_refuses_legacy_g1_g11_token_without_signed_authority(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(erc,"assess_release",lambda **kwargs:{
        "evaluation_release_permitted":True,
        "champion_sha256":"a"*64,
    })
    called=False
    def no_train(**kwargs):
        nonlocal called
        called=True
        raise AssertionError("challenger must not run without signed G12-G15 authority")
    monkeypatch.setattr(erc.gch,"train_challenger",no_train)
    with pytest.raises(RuntimeError,match="signed release authority is required"):
        erc.run_if_released(
            release_kwargs={"champion_bundle":tmp_path/"champion","output_dir":tmp_path/"release"},
            evaluation_output_dir=tmp_path/"eval",
        )
    assert called is False
