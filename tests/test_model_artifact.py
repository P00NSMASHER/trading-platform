from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import joblib
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import model_artifact as ma


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeSkops:
    def __init__(self, unknown: list[str], loaded=None):
        self.unknown = list(unknown)
        self.loaded = loaded if loaded is not None else {"research_use_only": True}
        self.load_called = False

    def get_untrusted_types(self, *, file: str):
        return list(self.unknown)

    def load(self, file: str, trusted):
        self.load_called = True
        return self.loaded

    def dump(self, obj, file: str):
        Path(file).write_bytes(b"fake-skops-artifact")


def test_verified_joblib_refuses_hash_mismatch_before_load(tmp_path: Path, monkeypatch):
    p = tmp_path / "model.joblib"
    joblib.dump({"x": 1}, p)
    called = False

    def _no_load(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("joblib.load must not run on a hash mismatch")

    monkeypatch.setattr(ma.joblib, "load", _no_load)
    with pytest.raises(ValueError, match="hash mismatch"):
        ma.load_verified_joblib(p, "0" * 64)
    assert called is False


def test_skops_load_refuses_unapproved_types_before_load(tmp_path: Path, monkeypatch):
    p = tmp_path / "model.skops"
    p.write_bytes(b"artifact")
    trust = tmp_path / "trusted.json"
    trust.write_text(json.dumps({"trusted_types": []}), encoding="utf-8")
    fake = FakeSkops(["example.CustomEstimator"])
    monkeypatch.setattr(ma, "_skops_io", lambda: fake)

    with pytest.raises(PermissionError, match="unapproved types"):
        ma.load_verified_skops(
            p, _sha(p), trusted_types_file=trust,
            expected_trusted_types_sha256=_sha(trust),
        )
    assert fake.load_called is False


def test_skops_load_allows_only_explicitly_reviewed_types(tmp_path: Path, monkeypatch):
    p = tmp_path / "model.skops"
    p.write_bytes(b"artifact")
    trust = tmp_path / "trusted.json"
    trust.write_text(
        json.dumps({"trusted_types": ["example.CustomEstimator"]}),
        encoding="utf-8",
    )
    fake = FakeSkops(["example.CustomEstimator"], loaded={"ok": True})
    monkeypatch.setattr(ma, "_skops_io", lambda: fake)

    loaded = ma.load_verified_skops(
        p, _sha(p), trusted_types_file=trust,
        expected_trusted_types_sha256=_sha(trust),
    )
    assert loaded == {"ok": True}
    assert fake.load_called is True


def test_export_report_does_not_auto_approve_unknown_types(tmp_path: Path, monkeypatch):
    source = tmp_path / "model.joblib"
    joblib.dump({"research_use_only": True}, source)
    output = tmp_path / "model.skops"
    report = tmp_path / "inspection.json"
    fake = FakeSkops(["example.CustomEstimator"])
    monkeypatch.setattr(ma, "_skops_io", lambda: fake)

    result = ma.export_verified_joblib_to_skops(source, _sha(source), output, report)
    assert result["untrusted_types"] == ["example.CustomEstimator"]
    assert result["runtime_load_permitted"] is False
    assert result["explicit_type_review_required"] is True
    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["runtime_load_permitted"] is False



def test_skops_trusted_types_file_hash_is_enforced_before_load(tmp_path: Path, monkeypatch):
    p = tmp_path / "model.skops"
    p.write_bytes(b"artifact")
    trust = tmp_path / "trusted.json"
    trust.write_text(
        json.dumps({"trusted_types": ["example.CustomEstimator"]}),
        encoding="utf-8",
    )
    approved_hash = _sha(trust)
    trust.write_text(
        json.dumps({"trusted_types": ["example.CustomEstimator", "malicious.NewType"]}),
        encoding="utf-8",
    )
    fake = FakeSkops(["example.CustomEstimator"])
    monkeypatch.setattr(ma, "_skops_io", lambda: fake)

    with pytest.raises(ValueError, match="hash mismatch"):
        ma.load_verified_skops(
            p,
            _sha(p),
            trusted_types_file=trust,
            expected_trusted_types_sha256=approved_hash,
        )
    assert fake.load_called is False
