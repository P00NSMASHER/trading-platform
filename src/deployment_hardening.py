from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as importlib_metadata
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib

try:
    import tomllib
except ImportError as exc:  # pragma: no cover - Python >=3.11 required by validated runtime
    raise RuntimeError("Step-10 runtime configuration requires Python 3.11+ (tomllib)") from exc

try:
    from case_evidence import connect, verify_review_chain
except ImportError:  # package-style import
    from .case_evidence import connect, verify_review_chain

SCHEMA_VERSION = "1.0.0"
RESEARCH_NOTICE = (
    "Historical market-surveillance research only. A surveillance score is not a finding "
    "of insider trading, MNPI misuse, or any other violation."
)
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
REQUIRED_MODEL_KEYS = {
    "schema_version",
    "selected_features",
    "elastic_net",
    "boosted_model",
    "calibrator",
    "blend_weights",
    "surveillance_threshold",
    "research_use_only",
}
PROHIBITED_TRADE_KEYS = {
    "buy",
    "sell",
    "trade_direction",
    "expected_return",
    "target_price",
    "position_size",
    "order_instruction",
    "broker",
    "brokerage",
    "execution",
}
RUNTIME_PACKAGES = ("joblib", "numpy", "scipy", "scikit-learn", "threadpoolctl")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuntimeConfig:
    config_path: Path
    case_db: Path
    model_bundle: Path
    training_manifest: Path
    backup_dir: Path
    export_dir: Path
    audit_dir: Path
    dashboard_host: str
    dashboard_port: int
    research_use_only: bool
    allow_network_bind: bool
    allow_execution_integration: bool
    allow_trade_outputs: bool
    expected_model_sha256: str
    model_format: str
    skops_trusted_types_file: Path | None
    expected_skops_trusted_types_sha256: str

    def validate(self) -> None:
        if not self.research_use_only:
            raise ValueError("runtime policy must keep research_use_only=true")
        if self.allow_network_bind:
            raise ValueError("runtime policy must keep allow_network_bind=false")
        if self.allow_execution_integration:
            raise ValueError("runtime policy must keep allow_execution_integration=false")
        if self.allow_trade_outputs:
            raise ValueError("runtime policy must keep allow_trade_outputs=false")
        expected = self.expected_model_sha256.strip().lower()
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise ValueError("runtime integrity expected_model_sha256 must be a 64-character SHA-256 hex digest")
        if self.model_format not in {"joblib", "skops"}:
            raise ValueError("runtime integrity model_format must be 'joblib' or 'skops'")
        if self.model_format == "skops":
            if (
                self.skops_trusted_types_file is None
                or not self.skops_trusted_types_file.exists()
                or not self.skops_trusted_types_file.is_file()
            ):
                raise ValueError("skops runtime requires an existing reviewed skops_trusted_types_file")
            trust_hash = self.expected_skops_trusted_types_sha256.strip().lower()
            if len(trust_hash) != 64 or any(ch not in "0123456789abcdef" for ch in trust_hash):
                raise ValueError("skops runtime requires expected_skops_trusted_types_sha256")
        if self.dashboard_host.strip().lower() not in LOOPBACK_HOSTS:
            raise ValueError("runtime dashboard host must be loopback-only")
        if not (1 <= int(self.dashboard_port) <= 65535):
            raise ValueError("runtime dashboard port must be in [1,65535]")
        for name, path in (
            ("case_db", self.case_db),
            ("model_bundle", self.model_bundle),
            ("training_manifest", self.training_manifest),
        ):
            if not path.exists():
                raise ValueError(f"configured {name} does not exist: {path}")
        if self.case_db.resolve() == self.model_bundle.resolve():
            raise ValueError("case database and model bundle must be separate files")


def _resolve(base: Path, value: str) -> Path:
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = (base / p).resolve()
    return p


def load_runtime_config(path: Path) -> RuntimeConfig:
    path = Path(path).resolve()
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    paths = raw.get("paths", {})
    dashboard = raw.get("dashboard", {})
    policy = raw.get("policy", {})
    integrity = raw.get("integrity", {})
    required_paths = {
        "case_db",
        "model_bundle",
        "training_manifest",
        "backup_dir",
        "export_dir",
        "audit_dir",
    }
    missing = sorted(required_paths - set(paths))
    if missing:
        raise ValueError(f"runtime config missing path keys: {missing}")
    # Config paths are resolved from project root when config/ is used.
    base = path.parent.parent if path.parent.name == "config" else path.parent
    cfg = RuntimeConfig(
        config_path=path,
        case_db=_resolve(base, str(paths["case_db"])),
        model_bundle=_resolve(base, str(paths["model_bundle"])),
        training_manifest=_resolve(base, str(paths["training_manifest"])),
        backup_dir=_resolve(base, str(paths["backup_dir"])),
        export_dir=_resolve(base, str(paths["export_dir"])),
        audit_dir=_resolve(base, str(paths["audit_dir"])),
        dashboard_host=str(dashboard.get("host", "127.0.0.1")),
        dashboard_port=int(dashboard.get("port", 8765)),
        research_use_only=bool(policy.get("research_use_only", False)),
        allow_network_bind=bool(policy.get("allow_network_bind", False)),
        allow_execution_integration=bool(policy.get("allow_execution_integration", False)),
        allow_trade_outputs=bool(policy.get("allow_trade_outputs", False)),
        expected_model_sha256=str(integrity.get("expected_model_sha256", "")).strip().lower(),
        model_format=str(integrity.get("model_format", "joblib")).strip().lower(),
        skops_trusted_types_file=(
            _resolve(base, str(integrity["skops_trusted_types_file"]))
            if str(integrity.get("skops_trusted_types_file", "")).strip()
            else None
        ),
        expected_skops_trusted_types_sha256=str(
            integrity.get("expected_skops_trusted_types_sha256", "")
        ).strip().lower(),
    )
    cfg.validate()
    return cfg


def runtime_versions() -> dict[str, str]:
    out = {"python": sys.version.split()[0]}
    for pkg in RUNTIME_PACKAGES:
        try:
            out[pkg] = importlib_metadata.version(pkg)
        except importlib_metadata.PackageNotFoundError:
            out[pkg] = "missing"
    return out


def _recursive_keys(obj: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(str(k).lower())
            keys.update(_recursive_keys(v))
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            keys.update(_recursive_keys(v))
    return keys


def verify_model_bundle(
    path: Path,
    *,
    expected_sha256: str | None = None,
    model_format: str = "joblib",
    skops_trusted_types_file: Path | None = None,
    expected_skops_trusted_types_sha256: str | None = None,
) -> dict[str, Any]:
    path = Path(path)
    actual_sha256 = sha256_file(path) if path.exists() else None
    expected = (expected_sha256 or "").strip().lower()
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "sha256": actual_sha256,
        "expected_sha256": expected or None,
        "model_format": model_format,
        "skops_trusted_types_file": str(skops_trusted_types_file) if skops_trusted_types_file else None,
        "expected_skops_trusted_types_sha256": expected_skops_trusted_types_sha256 or None,
        "hash_matches_expected": False,
        "deserialization_attempted": False,
        "required_keys_present": False,
        "research_use_only": False,
        "prohibited_trade_keys_present": [],
        "threshold_valid": False,
        "ok": False,
    }
    if not path.exists():
        return report
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        report["load_error"] = "trusted expected_model_sha256 is required before model deserialization"
        return report
    report["hash_matches_expected"] = actual_sha256 == expected
    if not report["hash_matches_expected"]:
        report["load_error"] = "model bundle hash mismatch; refusing to deserialize untrusted bytes"
        return report
    if model_format not in {"joblib", "skops"}:
        report["load_error"] = f"unsupported model_format={model_format!r}"
        return report
    try:
        report["deserialization_attempted"] = True
        if model_format == "joblib":
            bundle = joblib.load(path)
        else:
            try:
                from model_artifact import load_verified_skops
            except ImportError:
                from .model_artifact import load_verified_skops
            bundle = load_verified_skops(
                path,
                expected,
                trusted_types_file=skops_trusted_types_file,
                expected_trusted_types_sha256=expected_skops_trusted_types_sha256,
            )
        if not isinstance(bundle, dict):
            report["load_error"] = "model bundle is not a dict"
            return report
        report["required_keys_present"] = REQUIRED_MODEL_KEYS.issubset(bundle)
        report["research_use_only"] = bundle.get("research_use_only") is True
        keys = _recursive_keys({k: v for k, v in bundle.items() if k not in {"elastic_net", "boosted_model", "calibrator"}})
        prohibited = sorted(k for k in keys if k in PROHIBITED_TRADE_KEYS)
        report["prohibited_trade_keys_present"] = prohibited
        try:
            threshold = float(bundle.get("surveillance_threshold"))
            report["threshold_valid"] = 0.0 <= threshold <= 1.0
        except Exception:
            report["threshold_valid"] = False
        report["selected_feature_count"] = len(tuple(bundle.get("selected_features", ())))
        report["schema_version"] = bundle.get("schema_version")
        report["ok"] = bool(
            report["hash_matches_expected"]
            and report["required_keys_present"]
            and report["research_use_only"]
            and not prohibited
            and report["threshold_valid"]
        )
    except Exception as exc:
        report["load_error"] = f"{type(exc).__name__}: {exc}"
    return report


def verify_training_manifest(path: Path, model_report: dict[str, Any]) -> dict[str, Any]:
    path = Path(path)
    report: dict[str, Any] = {"path": str(path), "exists": path.exists(), "ok": False}
    if not path.exists():
        return report
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        report["sha256"] = sha256_file(path)
        report["research_use_only"] = manifest.get("research_use_only") is True
        report["deployment_status"] = manifest.get("deployment_status")
        report["prohibited_outputs"] = manifest.get("prohibited_outputs", [])
        report["lookahead_fields_rejected"] = bool(manifest.get("feature_policy", {}).get("lookahead_fields_rejected"))
        report["model_schema_matches"] = (
            str(manifest.get("schema_version")) == str(model_report.get("schema_version"))
        )
        report["ok"] = bool(
            report["research_use_only"]
            and report["lookahead_fields_rejected"]
            and report["model_schema_matches"]
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


def database_integrity_report(db_path: Path, *, model_sha256: str | None = None) -> dict[str, Any]:
    db_path = Path(db_path)
    report: dict[str, Any] = {
        "path": str(db_path),
        "exists": db_path.exists(),
        "sha256": sha256_file(db_path) if db_path.exists() else None,
        "sqlite_integrity": False,
        "foreign_keys_clean": False,
        "review_chains_valid": False,
        "source_hashes_well_formed": False,
        "model_hash_consistent": False,
        "ok": False,
    }
    if not db_path.exists():
        return report
    try:
        with connect(db_path) as con:
            integrity = [str(r[0]) for r in con.execute("PRAGMA integrity_check").fetchall()]
            fk_rows = con.execute("PRAGMA foreign_key_check").fetchall()
            case_ids = [str(r[0]) for r in con.execute("SELECT case_id FROM case_record ORDER BY case_id").fetchall()]
            sources = [dict(r) for r in con.execute("SELECT artifact_role,sha256 FROM source_artifact ORDER BY source_id").fetchall()]
            counts: dict[str, int] = {}
            for table in (
                "case_record",
                "case_timeline",
                "feature_snapshot",
                "control_snapshot",
                "source_artifact",
                "review_history",
            ):
                counts[table] = int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        review_results = {cid: verify_review_chain(db_path, cid) for cid in case_ids}
        source_hashes_well_formed = all(
            isinstance(s.get("sha256"), str)
            and len(s["sha256"]) == 64
            and all(ch in "0123456789abcdef" for ch in s["sha256"].lower())
            for s in sources
        )
        model_sources = [s for s in sources if s.get("artifact_role") == "model_bundle"]
        if model_sha256 is None:
            model_hash_consistent = bool(model_sources) and len({s["sha256"] for s in model_sources}) == 1
        else:
            model_hash_consistent = bool(model_sources) and all(s["sha256"] == model_sha256 for s in model_sources)
        report.update(
            {
                "sqlite_integrity_rows": integrity,
                "sqlite_integrity": integrity == ["ok"],
                "foreign_key_violation_count": len(fk_rows),
                "foreign_keys_clean": len(fk_rows) == 0,
                "case_count": len(case_ids),
                "row_counts": counts,
                "review_chain_results": review_results,
                "review_chains_valid": all(review_results.values()) if review_results else True,
                "source_hashes_well_formed": source_hashes_well_formed,
                "model_source_count": len(model_sources),
                "model_hash_consistent": model_hash_consistent,
            }
        )
        report["logical_fingerprint"] = sha256_json(
            {"row_counts": counts, "review_chain_results": review_results, "model_sources": model_sources}
        )
        report["ok"] = bool(
            report["sqlite_integrity"]
            and report["foreign_keys_clean"]
            and report["review_chains_valid"]
            and report["source_hashes_well_formed"]
            and report["model_hash_consistent"]
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


def ensure_private_runtime_dirs(cfg: RuntimeConfig) -> None:
    for path in (cfg.backup_dir, cfg.export_dir, cfg.audit_dir):
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except OSError:
            pass




def _mode_octal(path: Path) -> str:
    return oct(path.stat().st_mode & 0o777)


def apply_private_permissions(cfg: RuntimeConfig) -> dict[str, Any]:
    """Best-effort POSIX privacy hardening for local runtime artifacts.

    Sensitive files are owner read/write only; runtime directories are owner only.
    On platforms where chmod semantics differ, the resulting modes are still recorded
    by self_check rather than assumed.
    """
    cfg.validate()
    ensure_private_runtime_dirs(cfg)
    results: dict[str, Any] = {"files": {}, "directories": {}}
    protected_files = [cfg.config_path, cfg.case_db, cfg.model_bundle, cfg.training_manifest]
    if cfg.skops_trusted_types_file is not None:
        protected_files.append(cfg.skops_trusted_types_file)
    for path in protected_files:
        try:
            path.chmod(0o600)
            results["files"][str(path)] = {"mode": _mode_octal(path), "ok": (path.stat().st_mode & 0o077) == 0}
        except OSError as exc:
            results["files"][str(path)] = {"error": f"{type(exc).__name__}: {exc}", "ok": False}
    for path in (cfg.backup_dir, cfg.export_dir, cfg.audit_dir):
        try:
            path.chmod(0o700)
            results["directories"][str(path)] = {"mode": _mode_octal(path), "ok": (path.stat().st_mode & 0o077) == 0}
        except OSError as exc:
            results["directories"][str(path)] = {"error": f"{type(exc).__name__}: {exc}", "ok": False}
    results["ok"] = all(x.get("ok") for group in (results["files"], results["directories"]) for x in group.values())
    return results


def filesystem_permission_report(cfg: RuntimeConfig) -> dict[str, Any]:
    files: dict[str, Any] = {}
    directories: dict[str, Any] = {}
    protected_files = [cfg.config_path, cfg.case_db, cfg.model_bundle, cfg.training_manifest]
    if cfg.skops_trusted_types_file is not None:
        protected_files.append(cfg.skops_trusted_types_file)
    for path in protected_files:
        try:
            files[str(path)] = {"mode": _mode_octal(path), "ok": (path.stat().st_mode & 0o077) == 0}
        except OSError as exc:
            files[str(path)] = {"error": f"{type(exc).__name__}: {exc}", "ok": False}
    for path in (cfg.backup_dir, cfg.export_dir, cfg.audit_dir):
        try:
            directories[str(path)] = {"mode": _mode_octal(path), "ok": (path.stat().st_mode & 0o077) == 0}
        except OSError as exc:
            directories[str(path)] = {"error": f"{type(exc).__name__}: {exc}", "ok": False}
    return {"files": files, "directories": directories, "ok": all(x.get("ok") for group in (files, directories) for x in group.values())}

def verify_configured_model(cfg: RuntimeConfig) -> dict[str, Any]:
    """Verify/load only the model artifact explicitly trusted by runtime config."""
    cfg.validate()
    return verify_model_bundle(
        cfg.model_bundle,
        expected_sha256=cfg.expected_model_sha256,
        model_format=cfg.model_format,
        skops_trusted_types_file=cfg.skops_trusted_types_file,
        expected_skops_trusted_types_sha256=cfg.expected_skops_trusted_types_sha256,
    )


def self_check(cfg: RuntimeConfig) -> dict[str, Any]:
    cfg.validate()
    ensure_private_runtime_dirs(cfg)
    model = verify_configured_model(cfg)
    training = verify_training_manifest(cfg.training_manifest, model)
    database = database_integrity_report(cfg.case_db, model_sha256=model.get("sha256"))
    permissions = filesystem_permission_report(cfg)
    policy = {
        "research_use_only": cfg.research_use_only,
        "loopback_only": cfg.dashboard_host.lower() in LOOPBACK_HOSTS,
        "network_bind_disabled": not cfg.allow_network_bind,
        "execution_integration_disabled": not cfg.allow_execution_integration,
        "trade_outputs_disabled": not cfg.allow_trade_outputs,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "research_notice": RESEARCH_NOTICE,
        "config_path": str(cfg.config_path),
        "runtime_versions": runtime_versions(),
        "policy": policy,
        "model_bundle": model,
        "training_manifest": training,
        "case_database": database,
        "filesystem_permissions": permissions,
    }
    report["ok"] = bool(all(policy.values()) and model.get("ok") and training.get("ok") and database.get("ok") and permissions.get("ok"))
    report["audit_sha256"] = sha256_json({k: v for k, v in report.items() if k != "audit_sha256"})
    return report


def _backup_destination(backup_dir: Path, stem: str = "cases") -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = backup_dir / f"{stem}_{stamp}.sqlite"
    i = 1
    while candidate.exists():
        candidate = backup_dir / f"{stem}_{stamp}_{i}.sqlite"
        i += 1
    return candidate


def backup_database(db_path: Path, backup_dir: Path, *, model_sha256: str | None = None) -> dict[str, Any]:
    db_path = Path(db_path).resolve()
    backup_dir = Path(backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        backup_dir.chmod(0o700)
    except OSError:
        pass
    source_report = database_integrity_report(db_path, model_sha256=model_sha256)
    if not source_report.get("ok"):
        raise ValueError("refusing to back up a database that fails integrity checks")
    backup_path = _backup_destination(backup_dir, stem=db_path.stem)
    with sqlite3.connect(db_path) as src, sqlite3.connect(backup_path) as dst:
        src.backup(dst)
    try:
        backup_path.chmod(0o600)
    except OSError:
        pass
    backup_report = database_integrity_report(backup_path, model_sha256=model_sha256)
    if not backup_report.get("ok"):
        backup_path.unlink(missing_ok=True)
        raise RuntimeError("fresh database backup failed verification")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": utc_now(),
        "source_path": str(db_path),
        "source_sha256": source_report["sha256"],
        "source_logical_fingerprint": source_report["logical_fingerprint"],
        "backup_path": str(backup_path),
        "backup_sha256": backup_report["sha256"],
        "backup_logical_fingerprint": backup_report["logical_fingerprint"],
        "row_counts": backup_report["row_counts"],
        "review_chains_valid": backup_report["review_chains_valid"],
        "research_use_only": True,
    }
    manifest["manifest_sha256"] = sha256_json({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    manifest_path = backup_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        manifest_path.chmod(0o600)
    except OSError:
        pass
    return {**manifest, "manifest_path": str(manifest_path)}


def _verify_backup_manifest(backup_path: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    expected_manifest_hash = manifest.get("manifest_sha256")
    actual_manifest_hash = sha256_json({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    if expected_manifest_hash != actual_manifest_hash:
        raise ValueError("backup manifest hash mismatch")
    actual_backup_hash = sha256_file(backup_path)
    if manifest.get("backup_sha256") != actual_backup_hash:
        raise ValueError("backup file hash mismatch")
    return manifest


def restore_database(
    backup_path: Path,
    manifest_path: Path,
    destination: Path,
    *,
    model_sha256: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    backup_path = Path(backup_path).resolve()
    manifest_path = Path(manifest_path).resolve()
    destination = Path(destination).resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(f"destination exists: {destination}; pass overwrite=True explicitly")
    manifest = _verify_backup_manifest(backup_path, manifest_path)
    backup_report = database_integrity_report(backup_path, model_sha256=model_sha256)
    if not backup_report.get("ok"):
        raise ValueError("backup database fails integrity checks")
    if manifest.get("backup_logical_fingerprint") != backup_report.get("logical_fingerprint"):
        raise ValueError("backup logical fingerprint does not match manifest")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".restore.tmp")
    temp.unlink(missing_ok=True)
    shutil.copy2(backup_path, temp)
    restored_report = database_integrity_report(temp, model_sha256=model_sha256)
    if not restored_report.get("ok"):
        temp.unlink(missing_ok=True)
        raise RuntimeError("restored temporary database failed verification")
    if restored_report.get("logical_fingerprint") != manifest.get("backup_logical_fingerprint"):
        temp.unlink(missing_ok=True)
        raise RuntimeError("restored temporary database logical fingerprint mismatch")
    os.replace(temp, destination)
    try:
        destination.chmod(0o600)
    except OSError:
        pass
    return {
        "schema_version": SCHEMA_VERSION,
        "restored_at_utc": utc_now(),
        "backup_path": str(backup_path),
        "destination": str(destination),
        "destination_sha256": sha256_file(destination),
        "logical_fingerprint": restored_report["logical_fingerprint"],
        "review_chains_valid": restored_report["review_chains_valid"],
        "research_use_only": True,
    }


def recovery_drill(cfg: RuntimeConfig) -> dict[str, Any]:
    cfg.validate()
    model = verify_configured_model(cfg)
    if not model.get("ok"):
        raise ValueError("model bundle must pass verification before recovery drill")
    original_source_sha = sha256_file(cfg.case_db)
    with tempfile.TemporaryDirectory(prefix="mnpi_recovery_drill_") as td:
        root = Path(td)
        source = root / "source.sqlite"
        shutil.copy2(cfg.case_db, source)
        backup = backup_database(source, root / "backups", model_sha256=model["sha256"])
        restored = root / "restored.sqlite"
        restore = restore_database(
            Path(backup["backup_path"]),
            Path(backup["manifest_path"]),
            restored,
            model_sha256=model["sha256"],
        )
        restored_report = database_integrity_report(restored, model_sha256=model["sha256"])

        # Failure path: truncated backup must fail before replacing any destination.
        corrupt = root / "corrupt.sqlite"
        data = Path(backup["backup_path"]).read_bytes()
        corrupt.write_bytes(data[: max(128, len(data) // 3)])
        corruption_detected = not database_integrity_report(corrupt, model_sha256=model["sha256"]).get("ok", False)
        if not corruption_detected:
            raise RuntimeError("recovery drill failed to detect deliberate backup corruption")

        ok = bool(
            restored_report.get("ok")
            and restore["logical_fingerprint"] == backup["backup_logical_fingerprint"]
            and corruption_detected
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "performed_at_utc": utc_now(),
            "source_logical_fingerprint": backup["source_logical_fingerprint"],
            "restored_logical_fingerprint": restore["logical_fingerprint"],
            "review_chains_valid_after_restore": restored_report["review_chains_valid"],
            "deliberate_corruption_detected": corruption_detected,
            "source_database_unchanged": sha256_file(cfg.case_db) == original_source_sha,
            "ok": ok,
            "research_use_only": True,
        }


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(text, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Private prototype deployment hardening and recovery tools")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("harden-permissions")
    a.add_argument("--config", type=Path, required=True)
    a.add_argument("--report", type=Path)

    a = sub.add_parser("self-check")
    a.add_argument("--config", type=Path, required=True)
    a.add_argument("--report", type=Path)

    a = sub.add_parser("backup-db")
    a.add_argument("--config", type=Path, required=True)
    a.add_argument("--report", type=Path)

    a = sub.add_parser("restore-db")
    a.add_argument("--config", type=Path, required=True)
    a.add_argument("--backup", type=Path, required=True)
    a.add_argument("--manifest", type=Path, required=True)
    a.add_argument("--destination", type=Path, required=True)
    a.add_argument("--overwrite", action="store_true")
    a.add_argument("--report", type=Path)

    a = sub.add_parser("recovery-drill")
    a.add_argument("--config", type=Path, required=True)
    a.add_argument("--report", type=Path)
    return p


def main() -> None:
    args = build_parser().parse_args()
    cfg = load_runtime_config(args.config)
    if args.command == "harden-permissions":
        report = apply_private_permissions(cfg)
    elif args.command == "self-check":
        report = self_check(cfg)
    elif args.command == "backup-db":
        model = verify_configured_model(cfg)
        if not model.get("ok"):
            raise SystemExit("model verification failed; backup aborted")
        report = backup_database(cfg.case_db, cfg.backup_dir, model_sha256=model["sha256"])
    elif args.command == "restore-db":
        model = verify_configured_model(cfg)
        if not model.get("ok"):
            raise SystemExit("model verification failed; restore aborted")
        report = restore_database(
            args.backup,
            args.manifest,
            args.destination,
            model_sha256=model["sha256"],
            overwrite=args.overwrite,
        )
    elif args.command == "recovery-drill":
        report = recovery_drill(cfg)
    else:  # pragma: no cover
        raise AssertionError(args.command)
    _write_report(args.report, report)
    if report.get("ok") is False:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
