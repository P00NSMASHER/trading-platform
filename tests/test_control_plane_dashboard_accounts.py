from __future__ import annotations

import csv
import http.client
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from case_evidence import ingest_case
from control_plane import account_surveillance, registry as control_registry
from private_dashboard import (
    DashboardConfig,
    DashboardRepository,
    PrivateDashboardServer,
    SESSION_COOKIE,
    render_account,
    render_accounts,
    render_control_plane,
)

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "data" / "processed" / "model_demo"
SCORES = MODEL_DIR / "holdout_scores.csv"
FEATURES = ROOT / "data" / "examples" / "model_training_feature_vectors.csv"
CONTROLS = ROOT / "data" / "examples" / "model_training_matched_controls.csv"
BUNDLE = MODEL_DIR / "model_bundle.joblib"
TRAINING_MANIFEST = MODEL_DIR / "training_manifest.json"
ACCESS_TOKEN = "A" * 32
SESSION_TOKEN = "S" * 32


def _case_db(tmp_path: Path) -> Path:
    db = tmp_path / "cases.sqlite"
    ingest_case(
        db_path=db,
        case_id="CASE-H001",
        sample_id="H001:TREATED",
        scores_csv=SCORES,
        feature_vectors=FEATURES,
        model_bundle=BUNDLE,
        matched_controls=CONTROLS,
        training_manifest=TRAINING_MANIFEST,
    )
    return db


def _mapping(tmp_path: Path, account_key: str = "RAW-ACCOUNT-123") -> Path:
    path = tmp_path / "account-links.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["account_key", "case_id", "research_use_only"])
        w.writeheader()
        w.writerow(
            {
                "account_key": account_key,
                "case_id": "CASE-H001",
                "research_use_only": "true",
            }
        )
    return path


def _account_db(tmp_path: Path, case_db: Path, account_key: str = "RAW-ACCOUNT-123") -> Path:
    db = tmp_path / "account-surveillance.sqlite"
    account_surveillance.ingest_links(
        mapping_csv=_mapping(tmp_path, account_key),
        case_db=case_db,
        account_db=db,
    )
    return db


def _control_dir(tmp_path: Path) -> Path:
    control = tmp_path / "control"
    control_registry.init_db(control / "control.sqlite")
    return control


def _dashboard_files(tmp_path: Path) -> tuple[Path, Path]:
    assessment = tmp_path / "g12-g15.json"
    assessment.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "research_use_only": True,
                "preauthority_release_ready": False,
                "checks": [
                    {
                        "gate_id": "G12_POINT_IN_TIME_GRAPH_FEATURES",
                        "passed": True,
                        "detail": "fixture-ready",
                    },
                    {
                        "gate_id": "G13_GRAPH_CHALLENGER_GUARDRAILS",
                        "passed": False,
                        "detail": "fixture-blocked",
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    token = tmp_path / "release-authority-token.json"
    token.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "scope": "single_offline_historical_champion_challenger_evaluation",
                "authority_claim_sha256": "a" * 64,
                "authority_signature_verified": True,
                "research_use_only": True,
                "automatic_promotion_permitted": False,
                "active_champion_modification_permitted": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return assessment, token


def _headers(server: PrivateDashboardServer, port: int) -> dict[str, str]:
    return {
        "Host": f"127.0.0.1:{port}",
        "Cookie": f"{SESSION_COOKIE}={server.session_token}",
    }


def test_account_ingest_pseudonymizes_identity_and_binds_case_evidence(tmp_path: Path):
    case_db = _case_db(tmp_path)
    raw_key = "CUSTOMER-ACCOUNT-SECRET-42"
    mapping = _mapping(tmp_path, raw_key)
    account_db = tmp_path / "account.sqlite"

    result = account_surveillance.ingest_links(
        mapping_csv=mapping,
        case_db=case_db,
        account_db=account_db,
    )
    assert result["inserted_link_count"] == 1
    assert result["raw_account_keys_persisted"] is False
    assert result["identity_redacted"] is True
    assert raw_key.encode("utf-8") not in account_db.read_bytes()

    rows = account_surveillance.list_accounts(account_db=account_db, case_db=case_db)
    assert len(rows) == 1
    assert rows[0]["subject_id"].startswith("acct_")
    assert raw_key not in json.dumps(rows)
    assert rows[0]["linked_case_count"] == 1
    assert rows[0]["integrity_ok"] is True

    detail = account_surveillance.account_detail(
        account_db=account_db,
        case_db=case_db,
        subject_id=rows[0]["subject_id"],
    )
    assert detail["identity_redacted"] is True
    assert detail["linked_cases"][0]["case_id"] == "CASE-H001"
    assert detail["linked_cases"][0]["link_integrity_ok"] is True


def test_account_ingest_is_idempotent_and_registry_is_immutable(tmp_path: Path):
    case_db = _case_db(tmp_path)
    mapping = _mapping(tmp_path)
    account_db = tmp_path / "account.sqlite"
    first = account_surveillance.ingest_links(
        mapping_csv=mapping, case_db=case_db, account_db=account_db
    )
    second = account_surveillance.ingest_links(
        mapping_csv=mapping, case_db=case_db, account_db=account_db
    )
    assert first["inserted_link_count"] == 1
    assert second["inserted_link_count"] == 0
    assert second["no_op_link_count"] == 1

    with sqlite3.connect(account_db) as con:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE account_subject SET research_use_only=0")
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("DELETE FROM account_case_link")


def test_account_ingest_rejects_identity_and_trading_columns(tmp_path: Path):
    case_db = _case_db(tmp_path)
    mapping = tmp_path / "bad.csv"
    with mapping.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["account_key", "case_id", "research_use_only", "email"],
        )
        w.writeheader()
        w.writerow(
            {
                "account_key": "A1",
                "case_id": "CASE-H001",
                "research_use_only": "true",
                "email": "person@example.com",
            }
        )
    with pytest.raises(ValueError, match="prohibited identity/trading columns"):
        account_surveillance.ingest_links(
            mapping_csv=mapping,
            case_db=case_db,
            account_db=tmp_path / "account.sqlite",
        )


def test_account_ingest_rejects_unknown_case_and_nonresearch_row(tmp_path: Path):
    case_db = _case_db(tmp_path)
    mapping = tmp_path / "unknown.csv"
    mapping.write_text(
        "account_key,case_id,research_use_only\nA1,CASE-NOT-THERE,true\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown case_id"):
        account_surveillance.ingest_links(
            mapping_csv=mapping,
            case_db=case_db,
            account_db=tmp_path / "account.sqlite",
        )

    mapping.write_text(
        "account_key,case_id,research_use_only\nA1,CASE-H001,false\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="research_use_only must be true"):
        account_surveillance.ingest_links(
            mapping_csv=mapping,
            case_db=case_db,
            account_db=tmp_path / "account2.sqlite",
        )


def test_account_surveillance_integrity_verifier_is_read_only(tmp_path: Path):
    case_db = _case_db(tmp_path)
    account_db = _account_db(tmp_path, case_db)
    before = account_db.stat().st_size
    report = account_surveillance.verify_account_surveillance(
        account_db=account_db,
        case_db=case_db,
    )
    after = account_db.stat().st_size
    assert report["ok"] is True
    assert report["raw_account_keys_persisted"] is False
    assert before == after


def test_dashboard_account_and_control_views_are_read_only_and_redacted(tmp_path: Path):
    case_db = _case_db(tmp_path)
    raw_key = "NEVER-RENDER-THIS-ACCOUNT"
    account_db = _account_db(tmp_path, case_db, raw_key)
    control = _control_dir(tmp_path)
    assessment, token = _dashboard_files(tmp_path)

    repo = DashboardRepository(
        case_db,
        account_db_path=account_db,
        control_dir=control,
        g12_g15_assessment_path=assessment,
        release_authority_token_path=token,
    )
    accounts = repo.list_accounts()
    subject_id = accounts[0]["subject_id"]

    pages = [
        render_accounts(repo).decode("utf-8"),
        render_account(repo, subject_id).decode("utf-8"),
        render_control_plane(repo).decode("utf-8"),
    ]
    for page in pages:
        assert raw_key not in page
        assert "expected_return" not in page
        assert "target_price" not in page
        assert "position_size" not in page
        assert "order_instruction" not in page

    account_page = pages[1]
    assert subject_id in account_page
    assert "not stored" in account_page
    assert "read-only aggregation" in account_page.lower()
    control_page = pages[2]
    assert "G12_POINT_IN_TIME_GRAPH_FEATURES" in control_page
    assert "G13_GRAPH_CHALLENGER_GUARDRAILS" in control_page
    assert "execution re-verifies" in control_page
    assert "<form" not in control_page.lower()


def test_dashboard_http_exposes_authenticated_readonly_account_and_control_routes(tmp_path: Path):
    case_db = _case_db(tmp_path)
    account_db = _account_db(tmp_path, case_db)
    control = _control_dir(tmp_path)
    assessment, token = _dashboard_files(tmp_path)
    cfg = DashboardConfig(
        case_db,
        port=0,
        account_db_path=account_db,
        control_dir=control,
        g12_g15_assessment_path=assessment,
        release_authority_token_path=token,
    )
    server = PrivateDashboardServer(
        cfg,
        csrf_token="known-token",
        access_token=ACCESS_TOKEN,
        session_token=SESSION_TOKEN,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        for path in ["/accounts", "/control-plane"]:
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", path, headers=_headers(server, port))
            resp = conn.getresponse()
            body = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "No trading or execution outputs" in body

        subject_id = DashboardRepository(
            case_db, account_db_path=account_db
        ).list_accounts()[0]["subject_id"]
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request(
            "GET",
            "/account/" + subject_id,
            headers=_headers(server, port),
        )
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        assert resp.status == 200
        assert subject_id in body

        # No account/control-plane mutation route exists, even with a valid CSRF token.
        form = "csrf_token=known-token"
        conn = http.client.HTTPConnection(host, port, timeout=5)
        headers = _headers(server, port) | {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        conn.request("POST", "/accounts", body=form, headers=headers)
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_dashboard_optional_sources_validate_fail_closed(tmp_path: Path):
    case_db = _case_db(tmp_path)
    with pytest.raises(ValueError, match="account surveillance database"):
        DashboardConfig(case_db, account_db_path=tmp_path / "missing.sqlite").validate()
    with pytest.raises(ValueError, match="control-plane database"):
        DashboardConfig(case_db, control_dir=tmp_path / "missing-control").validate()
    with pytest.raises(ValueError, match="G12-G15 assessment"):
        DashboardConfig(case_db, g12_g15_assessment_path=tmp_path / "missing.json").validate()
    with pytest.raises(ValueError, match="release-authority token"):
        DashboardConfig(case_db, release_authority_token_path=tmp_path / "missing-token.json").validate()
