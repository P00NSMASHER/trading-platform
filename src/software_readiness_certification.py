from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import deployment_hardening as hardening

SCHEMA_VERSION = "1.0.0"

HOSTILE_TEST_GROUPS: dict[str, tuple[str, ...]] = {
    "temporal_and_point_in_time": (
        "tests/test_baseline_engine.py",
        "tests/test_feature_engine.py",
        "tests/test_historical_market_backfill.py",
        "tests/test_metadata_resolver.py",
        "tests/test_graph_feature_engine.py",
    ),
    "control_and_metadata_integrity": (
        "tests/test_metadata_quality.py",
        "tests/test_matched_control_generator.py",
        "tests/test_coverage_planner.py",
    ),
    "model_and_release_isolation": (
        "tests/test_model_training_harness.py",
        "tests/test_graph_challenger_harness.py",
        "tests/test_evaluation_release_controller.py",
    ),
    "intake_and_replay_fail_closed": (
        "tests/test_licensed_data_intake.py",
        "tests/test_licensed_data_drop_processor.py",
        "tests/test_real_data_replay.py",
        "tests/test_real_data_release_sprint.py",
    ),
    "control_plane_and_runtime_security": (
        "tests/test_control_plane_adversarial.py",
        "tests/test_control_plane_dashboard_accounts.py",
        "tests/test_private_dashboard.py",
        "tests/test_deployment_hardening.py",
        "tests/test_software_readiness_certification.py",
    ),
}

REQUIRED_SOFTWARE = (
    "src/licensed_data_intake.py",
    "src/licensed_data_drop_processor.py",
    "src/real_data_replay.py",
    "src/historical_market_backfill.py",
    "src/metadata_resolver.py",
    "src/metadata_quality.py",
    "src/matched_control_generator.py",
    "src/model_training_harness.py",
    "src/graph_challenger_harness.py",
    "src/evaluation_release_controller.py",
    "src/private_dashboard.py",
    "src/private_runtime.py",
)

PROHIBITED_OUTPUTS = [
    "BUY", "SELL", "expected_return", "target_price",
    "position_size", "order", "execution_instruction",
]


@dataclass(frozen=True)
class Check:
    check_id: str
    passed: bool
    detail: str
    category: str


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


def _git_head(root: Path) -> str:
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def _parse_pytest_count(output: str) -> int:
    matches = re.findall(r"(\d+)\s+passed", output)
    return int(matches[-1]) if matches else 0


def run_hostile_suite(root: Path) -> dict[str, Any]:
    test_paths: list[str] = []
    for names in HOSTILE_TEST_GROUPS.values():
        for name in names:
            if name not in test_paths:
                test_paths.append(name)

    missing = [p for p in test_paths if not (root / p).exists()]
    if missing:
        return {
            "ok": False,
            "returncode": -1,
            "passed_count": 0,
            "test_files": test_paths,
            "missing_test_files": missing,
            "stdout_tail": "",
        }

    cmd = [sys.executable, "-m", "pytest", "-q", *test_paths]
    p = subprocess.run(
        cmd,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = p.stdout or ""
    return {
        "ok": p.returncode == 0,
        "returncode": p.returncode,
        "passed_count": _parse_pytest_count(output),
        "test_files": test_paths,
        "missing_test_files": [],
        "stdout_tail": output[-6000:],
    }


def _real_data_state(root: Path) -> dict[str, Any]:
    coverage_path = root / "data/processed/coverage_plan_real/coverage_summary.json"
    readiness_path = root / "data/processed/authorized_input_real/metadata_readiness_summary.json"
    quality_path = root / "data/processed/authorized_input_real/metadata_quality_summary.json"
    replay_path = root / "data/processed/real_data_replay/real_data_replay_status.json"

    coverage = _read_json(coverage_path)
    readiness = _read_json(readiness_path)
    quality = _read_json(quality_path)

    audit = coverage.get("contract_audit") or {}
    g2_ready = bool(audit.get("ready_for_real_backfill"))
    g1_exact = bool(readiness.get("ready_g1_exact_timing_analysis"))
    g3 = bool(readiness.get("ready_g3_primary_listing_history"))
    g4 = bool(readiness.get("ready_g4_shares_outstanding"))
    g5_real = bool(readiness.get("ready_g5_model_evaluation_controls"))
    quality_real = bool(quality.get("quality_cleared_for_non_synthetic_model_evaluation"))

    replay_exists = replay_path.exists()
    replay = _read_json(replay_path) if replay_exists else {}
    replay_ready = bool(replay.get("ready_for_non_synthetic_offline_evaluation"))
    release_permitted = bool(replay.get("evaluation_release_permitted"))

    validated = all((
        g2_ready,
        g1_exact,
        g3,
        g4,
        g5_real,
        quality_real,
        replay_exists,
        replay_ready,
        release_permitted,
    ))

    return {
        "validated": validated,
        "gates": {
            "G1_EXACT_TIMING_ANALYSIS": g1_exact,
            "G2_REAL_MARKET_DATA": g2_ready,
            "G3_PRIMARY_LISTING_HISTORY": g3,
            "G4_SHARES_OUTSTANDING": g4,
            "G5_MODEL_EVALUATION_CONTROLS": g5_real,
            "G6_METADATA_QUALITY": quality_real,
            "REAL_DATA_REPLAY": replay_ready,
            "EVALUATION_RELEASE": release_permitted,
        },
        "coverage": {
            "required_source_date_rows": int(audit.get("required_source_date_rows", 0) or 0),
            "covered_real_source_date_rows": int(audit.get("real_authorized_required_rows_covered", 0) or 0),
            "missing_real_source_date_rows": int(audit.get("missing_real_authorized_required_rows", 0) or 0),
        },
        "metadata": {
            "announcement_exact_resolved": int(readiness.get("announcement_exact_resolved", 0) or 0),
            "announcement_required": int(readiness.get("event_count", 0) or 0),
            "control_dates_resolved": int(readiness.get("control_dates_resolved", 0) or 0),
            "control_dates_required": int(readiness.get("event_date_count", 0) or 0),
        },
        "replay_status_exists": replay_exists,
        "replay_status_path": str(replay_path.relative_to(root)),
        "input_hashes": {
            "coverage_summary": _sha256(coverage_path),
            "metadata_readiness": _sha256(readiness_path),
            "metadata_quality": _sha256(quality_path),
            "real_data_replay_status": _sha256(replay_path) if replay_exists else None,
        },
    }


def certify(
    root: Path,
    *,
    runtime_config: Path,
    output_path: Path,
    run_tests: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    runtime_config = runtime_config if runtime_config.is_absolute() else (root / runtime_config)
    output_path = output_path if output_path.is_absolute() else (root / output_path)

    checks: list[Check] = []

    missing_software = [p for p in REQUIRED_SOFTWARE if not (root / p).exists()]
    checks.append(Check(
        "SOFTWARE_COMPONENTS",
        not missing_software,
        f"missing={missing_software}",
        "software",
    ))

    missing_test_groups: dict[str, list[str]] = {}
    for group, paths in HOSTILE_TEST_GROUPS.items():
        missing = [p for p in paths if not (root / p).exists()]
        if missing:
            missing_test_groups[group] = missing
    checks.append(Check(
        "HOSTILE_TEST_COVERAGE",
        not missing_test_groups,
        f"groups={len(HOSTILE_TEST_GROUPS)}; missing={missing_test_groups}",
        "adversarial_testing",
    ))

    if run_tests:
        hostile = run_hostile_suite(root)
    else:
        hostile = {
            "ok": True,
            "returncode": 0,
            "passed_count": 0,
            "test_files": sorted({p for v in HOSTILE_TEST_GROUPS.values() for p in v}),
            "missing_test_files": [],
            "stdout_tail": "test execution skipped by caller",
            "skipped": True,
        }
    checks.append(Check(
        "HOSTILE_REGRESSION_SUITE",
        bool(hostile.get("ok")),
        f"returncode={hostile.get('returncode')}; passed={hostile.get('passed_count')}",
        "adversarial_testing",
    ))

    try:
        cfg = hardening.load_runtime_config(runtime_config)
        runtime = hardening.self_check(cfg)
        runtime_ok = bool(runtime.get("ok"))
        runtime_detail = (
            f"ok={runtime_ok}; audit_sha256={runtime.get('audit_sha256', '')}; "
            f"model_sha256={(runtime.get('model_bundle') or {}).get('sha256', '')}"
        )
    except Exception as exc:
        runtime = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        runtime_ok = False
        runtime_detail = runtime["error"]
    checks.append(Check(
        "PRIVATE_RUNTIME_INTEGRITY",
        runtime_ok,
        runtime_detail,
        "runtime",
    ))

    real_data = _real_data_state(root)

    # Real-data validation is deliberately NOT part of software_ready. These are
    # separate state dimensions so a missing vendor corpus cannot be painted green.
    software_failures = [c for c in checks if not c.passed]
    software_ready = not software_failures
    real_data_validated = bool(real_data["validated"])

    if not software_ready:
        overall = "SOFTWARE_NOT_READY"
    elif real_data_validated:
        overall = "SOFTWARE_READY_REAL_DATA_VALIDATED"
    else:
        overall = "SOFTWARE_READY_REAL_DATA_PENDING"

    result = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Independent certification of software readiness versus real-data validation "
            "for the offline historical market-surveillance research platform."
        ),
        "git_commit": _git_head(root),
        "software_ready": software_ready,
        "real_data_validated": real_data_validated,
        "overall_status": overall,
        "checks": [asdict(c) for c in checks],
        "software_failure_count": len(software_failures),
        "software_failures": [asdict(c) for c in software_failures],
        "hostile_regression_suite": hostile,
        "runtime_self_check": runtime,
        "real_data_state": real_data,
        "semantics": {
            "software_ready_means": (
                "required pipeline components exist; hostile regression suite passes; "
                "private runtime integrity self-check passes"
            ),
            "software_ready_does_not_mean": (
                "licensed historical market data has been received or that real-world "
                "model performance has been validated"
            ),
            "real_data_validated_requires": (
                "G1 exact timing, G2 real market data, G3 listing, G4 shares, genuine G5 controls, "
                "metadata quality, real-data replay, and fail-closed evaluation release all green"
            ),
            "automatic_promotion_permitted": False,
            "active_champion_modification_permitted": False,
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    p = argparse.ArgumentParser(
        description="Certify software readiness separately from real-data validation."
    )
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--runtime-config", type=Path, default=Path("config/runtime.demo.toml"))
    p.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/software_readiness/software_readiness_certification.json"),
    )
    p.add_argument("--skip-tests", action="store_true")
    p.add_argument("--require-software-ready", action="store_true")
    p.add_argument("--require-real-data-validated", action="store_true")
    args = p.parse_args()

    result = certify(
        args.root,
        runtime_config=args.runtime_config,
        output_path=args.output,
        run_tests=not args.skip_tests,
    )
    print(json.dumps(result, indent=2, sort_keys=True))

    if args.require_software_ready and not result["software_ready"]:
        raise SystemExit(2)
    if args.require_real_data_validated and not result["real_data_validated"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
