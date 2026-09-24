from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import secret_scan


def test_detects_openai_style_key(tmp_path: Path):
    p = tmp_path / "config.py"
    fake = "api_key = 'sk-proj-abcdefghijklmnopqrstuvwxyz1234567890'"  # secret-scan: allow
    p.write_text(fake + "\n", encoding="utf-8")
    findings = secret_scan.scan_paths(tmp_path, [p])
    assert any(f.kind == "openai_api_key" for f in findings)


def test_detects_private_key_banner(tmp_path: Path):
    p = tmp_path / "material.txt"
    banner = "-----BEGIN PRIVATE KEY-----"  # secret-scan: allow
    p.write_text(banner + "\n", encoding="utf-8")
    findings = secret_scan.scan_paths(tmp_path, [p])
    assert any(f.kind == "private_key" for f in findings)


def test_allow_marker_suppresses_intentional_fixture(tmp_path: Path):
    p = tmp_path / "fixture.py"
    p.write_text(
        "api_key = 'sk-proj-abcdefghijklmnopqrstuvwxyz1234567890'  # secret-scan: allow\n",
        encoding="utf-8",
    )  # secret-scan: allow
    assert secret_scan.scan_paths(tmp_path, [p]) == []


def test_dangerous_secret_filename_is_flagged(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("SAFE_PLACEHOLDER=example\n", encoding="utf-8")
    findings = secret_scan.scan_paths(tmp_path, [p])
    assert any(f.kind == "dangerous_secret_filename" for f in findings)


def test_repository_currently_scans_clean():
    assert secret_scan.scan_paths(ROOT) == []
