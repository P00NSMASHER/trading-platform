from __future__ import annotations

import http.client
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from case_evidence import ingest_case, init_db, verify_review_chain
from private_dashboard import (
    DashboardConfig,
    DashboardRepository,
    PrivateDashboardServer,
    SESSION_COOKIE,
    render_case,
    render_index,
)

MODEL_DIR = ROOT / "data" / "processed" / "model_demo"
SCORES = MODEL_DIR / "holdout_scores.csv"
FEATURES = ROOT / "data" / "examples" / "model_training_feature_vectors.csv"
CONTROLS = ROOT / "data" / "examples" / "model_training_matched_controls.csv"
BUNDLE = MODEL_DIR / "model_bundle.joblib"
TRAINING_MANIFEST = MODEL_DIR / "training_manifest.json"
ACCESS_TOKEN = "A" * 32
SESSION_TOKEN = "S" * 32


def _auth_headers(server: PrivateDashboardServer, port: int) -> dict[str, str]:
    return {
        "Host": f"127.0.0.1:{port}",
        "Cookie": f"{SESSION_COOKIE}={server.session_token}",
    }


def _db(tmp_path: Path) -> Path:
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


def test_dashboard_rejects_non_loopback_bind(tmp_path: Path):
    db = _db(tmp_path)
    with pytest.raises(ValueError):
        DashboardConfig(db_path=db, host="0.0.0.0").validate()


def test_repository_lists_case_and_integrity(tmp_path: Path):
    db = _db(tmp_path)
    repo = DashboardRepository(db)
    rows = repo.list_cases()
    assert len(rows) == 1
    assert rows[0]["case_id"] == "CASE-H001"
    assert rows[0]["integrity_ok"] is True


def test_repository_filters_cases(tmp_path: Path):
    db = _db(tmp_path)
    repo = DashboardRepository(db)
    assert len(repo.list_cases(query="CASE-H001")) == 1
    assert len(repo.list_cases(query="NOPE")) == 0
    assert len(repo.list_cases(flagged="1")) in {0, 1}
    assert len(repo.list_cases(disposition="pending_human_review")) == 1


def test_case_detail_includes_evidence_views(tmp_path: Path):
    db = _db(tmp_path)
    d = DashboardRepository(db).case_detail("CASE-H001")
    assert d["features"]
    assert len(d["controls"]) == 3
    assert d["timeline"]
    assert d["sources"]
    assert d["reviews"]
    assert d["integrity"]["ok"] is True


def test_rendered_pages_include_research_notice_and_no_trade_directives(tmp_path: Path):
    db = _db(tmp_path)
    repo = DashboardRepository(db)
    pages = [render_index(repo, {}), render_case(repo, "CASE-H001", "csrf")]
    for page in pages:
        text = page.decode().lower()
        assert "not a finding" in text
        assert "expected_return" not in text
        assert "target_price" not in text
        assert "position_size" not in text
        assert "order_instruction" not in text


def test_http_server_loopback_security_headers_and_health(tmp_path: Path):
    db = _db(tmp_path)
    server = PrivateDashboardServer(DashboardConfig(db, port=0), csrf_token="known-token", access_token=ACCESS_TOKEN, session_token=SESSION_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/healthz", headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 200
        assert body == b"ok\n"
        assert resp.getheader("Cache-Control") == "no-store"
        assert resp.getheader("X-Frame-Options") == "DENY"
        assert "default-src 'none'" in resp.getheader("Content-Security-Policy")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_rejects_nonlocal_host_header(tmp_path: Path):
    db = _db(tmp_path)
    server = PrivateDashboardServer(DashboardConfig(db, port=0), csrf_token="known-token", access_token=ACCESS_TOKEN, session_token=SESSION_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/", headers={"Host": "evil.example"})
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 403
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_post_review_requires_csrf_and_appends_valid_chain(tmp_path: Path):
    db = _db(tmp_path)
    server = PrivateDashboardServer(DashboardConfig(db, port=0), csrf_token="known-token", access_token=ACCESS_TOKEN, session_token=SESSION_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        bad = urllib.parse.urlencode({
            "csrf_token": "wrong", "reviewer": "owner", "action": "note_added",
            "disposition": "under_review", "note": "x",
        })
        conn = http.client.HTTPConnection(host, port, timeout=5)
        bad_headers = _auth_headers(server, port) | {"Content-Type": "application/x-www-form-urlencoded"}
        conn.request("POST", "/case/CASE-H001/review", body=bad, headers=bad_headers)
        resp = conn.getresponse(); resp.read()
        assert resp.status == 403

        good = urllib.parse.urlencode({
            "csrf_token": "known-token", "reviewer": "owner", "action": "review_started",
            "disposition": "under_review", "note": "dashboard test",
        })
        conn = http.client.HTTPConnection(host, port, timeout=5)
        good_headers = _auth_headers(server, port) | {"Content-Type": "application/x-www-form-urlencoded"}
        conn.request("POST", "/case/CASE-H001/review", body=good, headers=good_headers)
        resp = conn.getresponse(); resp.read()
        assert resp.status == 303
        assert verify_review_chain(db, "CASE-H001") is True
        assert DashboardRepository(db).case_detail("CASE-H001")["current_disposition"] == "under_review"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_export_endpoint_generates_local_bundle(tmp_path: Path):
    db = _db(tmp_path)
    export_dir = tmp_path / "exports"
    server = PrivateDashboardServer(DashboardConfig(db, port=0, export_dir=export_dir), csrf_token="known-token", access_token=ACCESS_TOKEN, session_token=SESSION_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        form = urllib.parse.urlencode({"csrf_token": "known-token"})
        conn = http.client.HTTPConnection(host, port, timeout=5)
        headers = _auth_headers(server, port) | {"Content-Type": "application/x-www-form-urlencoded"}
        conn.request("POST", "/case/CASE-H001/export", body=form, headers=headers)
        resp = conn.getresponse(); body = resp.read().decode()
        assert resp.status == 200
        assert "Evidence bundle created locally" in body
        assert list(export_dir.glob("*.zip"))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)



def test_dashboard_requires_per_launch_authentication(tmp_path: Path):
    db = _db(tmp_path)
    server = PrivateDashboardServer(
        DashboardConfig(db, port=0), csrf_token="known-token", access_token=ACCESS_TOKEN, session_token=SESSION_TOKEN
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse(); resp.read()
        assert resp.status == 401

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request(
            "GET",
            "/?access_token=" + urllib.parse.quote(ACCESS_TOKEN),
            headers={"Host": f"127.0.0.1:{port}"},
        )
        resp = conn.getresponse(); resp.read()
        assert resp.status == 303
        cookie = resp.getheader("Set-Cookie")
        assert cookie is not None
        assert f"{SESSION_COOKIE}={SESSION_TOKEN}" in cookie
        assert ACCESS_TOKEN not in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=Strict" in cookie
        assert resp.getheader("Location") == "/"

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/", headers=_auth_headers(server, port))
        resp = conn.getresponse(); body = resp.read().decode()
        assert resp.status == 200
        assert "Private Market-Surveillance Review" in body

        # The bootstrap URL is single-use and cannot mint another session.
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request(
            "GET",
            "/?access_token=" + urllib.parse.quote(ACCESS_TOKEN),
            headers={"Host": f"127.0.0.1:{port}"},
        )
        resp = conn.getresponse(); resp.read()
        assert resp.status == 401
        assert resp.getheader("Set-Cookie") is None

        # The bootstrap token itself is never a valid session cookie.
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request(
            "GET",
            "/",
            headers={
                "Host": f"127.0.0.1:{port}",
                "Cookie": f"{SESSION_COOKIE}={ACCESS_TOKEN}",
            },
        )
        resp = conn.getresponse(); resp.read()
        assert resp.status == 401
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_dashboard_rejects_oversized_post_body(tmp_path: Path):
    db = _db(tmp_path)
    cfg = DashboardConfig(db, port=0, max_request_bytes=1024)
    server = PrivateDashboardServer(cfg, csrf_token="known-token", access_token=ACCESS_TOKEN, session_token=SESSION_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        body = "x=" + ("A" * 1500)
        headers = _auth_headers(server, port) | {"Content-Type": "application/x-www-form-urlencoded"}
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/case/CASE-H001/review", body=body, headers=headers)
        resp = conn.getresponse(); resp.read()
        assert resp.status == 413
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_dashboard_rate_limits_requests(tmp_path: Path):
    db = _db(tmp_path)
    cfg = DashboardConfig(db, port=0, requests_per_minute=2, writes_per_minute=1)
    server = PrivateDashboardServer(cfg, csrf_token="known-token", access_token=ACCESS_TOKEN, session_token=SESSION_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        statuses = []
        for _ in range(3):
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/healthz", headers={"Host": f"127.0.0.1:{port}"})
            resp = conn.getresponse(); resp.read()
            statuses.append(resp.status)
        assert statuses == [200, 200, 429]
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_dashboard_rejects_overlong_uri(tmp_path: Path):
    db = _db(tmp_path)
    cfg = DashboardConfig(db, port=0, max_uri_bytes=256)
    server = PrivateDashboardServer(cfg, csrf_token="known-token", access_token=ACCESS_TOKEN, session_token=SESSION_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/?" + ("q=A&" * 100), headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse(); resp.read()
        assert resp.status == 414
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_dashboard_rejects_excess_concurrent_connection_before_handler_thread(tmp_path: Path):
    db = _db(tmp_path)
    cfg = DashboardConfig(
        db,
        port=0,
        max_concurrent_connections=1,
        socket_timeout_seconds=1.0,
    )
    server = PrivateDashboardServer(
        cfg,
        csrf_token="known-token",
        access_token=ACCESS_TOKEN,
        session_token=SESSION_TOKEN,
    )
    # Occupy the only handler slot without creating a handler thread.
    assert server._connection_slots.acquire(blocking=False) is True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/healthz", headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse()
        body = resp.read()
        assert resp.status == 503
        assert body == b"service busy\n"
        assert resp.getheader("Retry-After") == "1"
    finally:
        server._connection_slots.release()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_dashboard_connection_resource_limits_validate(tmp_path: Path):
    db = _db(tmp_path)
    with pytest.raises(ValueError, match="max_concurrent_connections"):
        DashboardConfig(db, max_concurrent_connections=0).validate()
    with pytest.raises(ValueError, match="socket_timeout_seconds"):
        DashboardConfig(db, socket_timeout_seconds=0.1).validate()
