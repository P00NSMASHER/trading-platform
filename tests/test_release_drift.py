from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_release_drift as drift


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _blob(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _write_fixture(tmp_path: Path):
    old = b"historical\n"
    changed = b"patched\n"
    added = b"new\n"
    (tmp_path / "old.txt").write_bytes(old)
    (tmp_path / "changed.txt").write_bytes(changed)
    (tmp_path / "added.txt").write_bytes(added)

    manifest = {
        "files": [
            {"path": "old.txt", "sha256": _sha(old), "size_bytes": len(old)},
            {"path": "changed.txt", "sha256": _sha(b"original\n"), "size_bytes": len(b"original\n")},
        ]
    }
    (tmp_path / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "SHA256SUMS").write_text(
        f"{_sha(old)}  old.txt\n{_sha(b'original\n')}  changed.txt\n",
        encoding="utf-8",
    )
    exceptions = {
        "intentional_release_modifications": {
            "changed.txt": {"expected_git_blob_sha1": _blob(changed), "reason": "security patch"}
        },
        "repository_additions": {
            "added.txt": {"expected_git_blob_sha1": _blob(added), "reason": "hardening file"}
        },
    }
    ex = tmp_path / "exceptions.json"
    ex.write_text(json.dumps(exceptions), encoding="utf-8")
    return ex


def test_release_drift_accepts_declared_patch_and_addition(tmp_path: Path):
    ex = _write_fixture(tmp_path)
    result = drift.verify_release_drift(
        root=tmp_path,
        release_manifest=tmp_path / "RELEASE_MANIFEST.json",
        sha256sums=tmp_path / "SHA256SUMS",
        exceptions=ex,
        tracked_paths={"old.txt", "changed.txt", "added.txt"},
    )
    assert result["ok"] is True


def test_release_drift_detects_tampered_unchanged_file(tmp_path: Path):
    ex = _write_fixture(tmp_path)
    (tmp_path / "old.txt").write_text("tampered\n", encoding="utf-8")
    result = drift.verify_release_drift(
        root=tmp_path,
        release_manifest=tmp_path / "RELEASE_MANIFEST.json",
        sha256sums=tmp_path / "SHA256SUMS",
        exceptions=ex,
        tracked_paths={"old.txt", "changed.txt", "added.txt"},
    )
    assert result["ok"] is False
    assert result["failed_check_count"] == 1


def test_release_drift_detects_unexpected_tracked_file(tmp_path: Path):
    ex = _write_fixture(tmp_path)
    (tmp_path / "surprise.txt").write_text("x", encoding="utf-8")
    result = drift.verify_release_drift(
        root=tmp_path,
        release_manifest=tmp_path / "RELEASE_MANIFEST.json",
        sha256sums=tmp_path / "SHA256SUMS",
        exceptions=ex,
        tracked_paths={"old.txt", "changed.txt", "added.txt", "surprise.txt"},
    )
    assert result["ok"] is False
    assert result["unexpected_tracked_paths"] == ["surprise.txt"]
