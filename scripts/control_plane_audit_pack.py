from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import secret_scan
import verify_release_drift as drift

SCHEMA_VERSION = "1"
EXPECTED_CHAMPION_SHA256 = "0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616"
PINNED_ACTION_RE = re.compile(r"^\s*uses:\s*[^#\s]+@([0-9a-f]{40})\b", re.MULTILINE)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _git(root: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(root.resolve()), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return p.stdout.strip()


def _tracked_paths(root: Path) -> list[str]:
    raw = subprocess.run(
        ["git", "-C", str(root.resolve()), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.decode("utf-8")
    return sorted(x for x in raw.split("\0") if x)


def _tracked_tree_sha256(root: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    paths = _tracked_paths(root)
    for rel in paths:
        p = root / rel
        if not p.is_file():
            raise ValueError(f"tracked path is not a regular file: {rel}")
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(_sha256(p).encode("ascii"))
        h.update(b"\0")
        h.update(str(p.stat().st_size).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest(), len(paths)


def _commit_time(root: Path) -> str:
    return _git(root, "show", "-s", "--format=%cI", "HEAD")


def _junit_summary(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    if root.tag == "testsuites":
        suites = list(root.findall("testsuite"))
    elif root.tag == "testsuite":
        suites = [root]
    else:
        raise ValueError(f"unsupported JUnit root element: {root.tag}")

    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    duration = 0.0
    for suite in suites:
        for key in totals:
            totals[key] += int(float(suite.attrib.get(key, "0") or 0))
        duration += float(suite.attrib.get("time", "0") or 0)
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    totals["duration_seconds"] = round(duration, 6)
    totals["ok"] = totals["tests"] > 0 and totals["failures"] == 0 and totals["errors"] == 0
    return totals


def _workflow_audit(root: Path) -> dict[str, Any]:
    workflow_dir = root / ".github" / "workflows"
    workflows = sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml"))
    rows = []
    all_pinned = True
    read_only = True
    no_persisted_credentials = True
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        action_refs = re.findall(r"^\s*uses:\s*([^#\s]+)", text, flags=re.MULTILINE)
        pinned = all(re.search(r"@[0-9a-f]{40}$", ref) for ref in action_refs)
        contents_read = bool(re.search(r"(?ms)^permissions:\s*\n(?:\s+[^\n]+\n)*?\s+contents:\s*read\s*$", text))
        persist_false = "persist-credentials: false" in text
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "external_action_refs": action_refs,
                "all_external_actions_sha_pinned": pinned,
                "contents_read_permission_present": contents_read,
                "persist_credentials_false_present": persist_false,
            }
        )
        all_pinned = all_pinned and pinned
        read_only = read_only and contents_read
        no_persisted_credentials = no_persisted_credentials and persist_false
    pr_ci = (workflow_dir / "pr-ci.yml").read_text(encoding="utf-8")
    pr_head_checkout = "github.event.pull_request.head.sha" in pr_ci
    return {
        "workflow_count": len(rows),
        "workflows": rows,
        "all_external_actions_sha_pinned": all_pinned,
        "all_workflows_contents_read": read_only,
        "all_workflows_disable_persisted_checkout_credentials": no_persisted_credentials,
        "pr_ci_explicit_head_sha_checkout": pr_head_checkout,
        "ok": bool(rows and all_pinned and read_only and no_persisted_credentials and pr_head_checkout),
    }


def _policy_file_audit(root: Path) -> dict[str, Any]:
    security = (root / "SECURITY.md").read_text(encoding="utf-8").lower()
    required = [
        "broker",
        "order",
        "trade",
        "private key",
        "release-drift",
        "loopback",
    ]
    missing = [x for x in required if x not in security]
    return {"required_terms": required, "missing_terms": missing, "ok": not missing}


def _build_report(
    *,
    root: Path,
    junit_xml: Path,
    expected_champion_sha256: str,
    expected_drift_trust_root_sha256: str,
) -> dict[str, Any]:
    root = root.resolve()
    head = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    tracked_tree_sha, tracked_count = _tracked_tree_sha256(root)
    champion = root / "data/processed/model_demo/model_bundle.joblib"
    champion_sha = _sha256(champion)
    allowlist = root / "config/release_drift_allowlist.json"
    allowlist_sha = _sha256(allowlist)

    internal_drift = drift.verify_release_drift(
        root=root,
        release_manifest=root / "RELEASE_MANIFEST.json",
        sha256sums=root / "SHA256SUMS",
        exceptions=allowlist,
        expected_exceptions_sha256=allowlist_sha,
    )

    external_hash = str(expected_drift_trust_root_sha256 or "").strip().lower()
    external_supplied = bool(external_hash)
    external_drift_ok = False
    external_drift_error = None
    if external_supplied:
        try:
            external_result = drift.verify_release_drift(
                root=root,
                release_manifest=root / "RELEASE_MANIFEST.json",
                sha256sums=root / "SHA256SUMS",
                exceptions=allowlist,
                expected_exceptions_sha256=external_hash,
            )
            external_drift_ok = bool(external_result.get("ok"))
            if not external_drift_ok:
                external_drift_error = "external trust-root release-drift verification returned ok=false"
        except Exception as exc:
            external_drift_error = f"{type(exc).__name__}: {exc}"

    findings = secret_scan.scan_paths(root)
    secret_result = {
        "finding_count": len(findings),
        "findings": [
            {"path": x.path, "line": x.line, "kind": x.kind}
            for x in findings
        ],
        "ok": not findings,
    }

    junit = _junit_summary(junit_xml)
    workflows = _workflow_audit(root)
    policy = _policy_file_audit(root)

    checks = {
        "adversarial_tests": bool(junit["ok"]),
        "secret_scan": bool(secret_result["ok"]),
        "champion_hash": champion_sha == expected_champion_sha256,
        "internal_release_drift_identities": bool(internal_drift.get("ok")),
        "workflow_supply_chain": bool(workflows["ok"]),
        "security_policy_presence": bool(policy["ok"]),
    }
    audit_pass = all(checks.values())
    release_ready = bool(audit_pass and external_supplied and external_drift_ok)
    core = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Final adversarial CI and audit pack for the research-only control plane.",
        "git_commit": head,
        "git_tree": tree,
        "git_commit_time": _commit_time(root),
        "tracked_tree_sha256": tracked_tree_sha,
        "tracked_file_count": tracked_count,
        "champion_sha256": champion_sha,
        "expected_champion_sha256": expected_champion_sha256,
        "release_drift_allowlist_sha256": allowlist_sha,
        "external_release_drift_trust_root_supplied": external_supplied,
        "external_release_drift_trust_root_verified": external_drift_ok,
        "external_release_drift_error": external_drift_error,
        "adversarial_junit": junit,
        "secret_scan": secret_result,
        "workflow_audit": workflows,
        "security_policy_audit": policy,
        "internal_release_drift": {
            "ok": bool(internal_drift.get("ok")),
            "tracked_file_count": internal_drift.get("tracked_file_count"),
            "repository_addition_count": internal_drift.get("repository_addition_count"),
            "intentional_modified_count": internal_drift.get("intentional_modified_count"),
            "failed_check_count": internal_drift.get("failed_check_count"),
            "unexpected_tracked_paths": internal_drift.get("unexpected_tracked_paths", []),
            "missing_tracked_paths": internal_drift.get("missing_tracked_paths", []),
        },
        "checks": checks,
        "audit_pack_pass": audit_pass,
        "release_ready": release_ready,
        "release_blockers": (
            []
            if release_ready
            else (
                [name for name, passed in checks.items() if not passed]
                + ([] if external_supplied and external_drift_ok else ["external_release_drift_trust_root_not_verified"])
            )
        ),
        "research_use_only": True,
        "automatic_promotion_permitted": False,
        "active_champion_modification_permitted": False,
        "broker_or_execution_integration_permitted": False,
        "trade_outputs_permitted": False,
    }
    core["audit_pack_id"] = hashlib.sha256(_canonical(core)).hexdigest()
    return core


def _markdown(report: dict[str, Any]) -> str:
    status = "PASS" if report["audit_pack_pass"] else "FAIL"
    release = "READY" if report["release_ready"] else "BLOCKED"
    checks = "\n".join(
        f"- {'PASS' if passed else 'FAIL'} — {name}"
        for name, passed in report["checks"].items()
    )
    blockers = ", ".join(report["release_blockers"]) if report["release_blockers"] else "none"
    j = report["adversarial_junit"]
    return f"""# Control-Plane Final Audit Pack

**Audit pack:** {status}  
**Release readiness:** {release}  
**Git commit:** `{report['git_commit']}`  
**Git tree:** `{report['git_tree']}`  
**Tracked-tree SHA-256:** `{report['tracked_tree_sha256']}`  
**Frozen champion SHA-256:** `{report['champion_sha256']}`  
**Release-drift allowlist SHA-256:** `{report['release_drift_allowlist_sha256']}`  
**Audit pack ID:** `{report['audit_pack_id']}`

## CI evidence

Adversarial suite: **{j['passed']} passed**, {j['failures']} failures, {j['errors']} errors, {j['skipped']} skipped.

{checks}

## External trust boundary

External release-drift trust root supplied: **{report['external_release_drift_trust_root_supplied']}**  
External release-drift trust root verified: **{report['external_release_drift_trust_root_verified']}**

Release blockers: **{blockers}**

A PR audit can pass while release readiness remains blocked. Final release requires the independently stored SHA-256 of `config/release_drift_allowlist.json` to be supplied and verified; the repository's own copy is not an independent trust anchor.

## Safety boundary

This pack is for historical market-surveillance research. It does not authorize automatic model promotion, champion modification, broker connectivity, order generation, trade recommendations, position sizing, expected-return output, or live confidential-data ingestion.
"""


def write_pack(*, output_dir: Path, report: dict[str, Any]) -> dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "control_plane_audit.json"
    md_path = output_dir / "CONTROL_PLANE_AUDIT.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    sums_path = output_dir / "SHA256SUMS"
    sums_path.write_text(
        f"{_sha256(json_path)}  {json_path.name}\n{_sha256(md_path)}  {md_path.name}\n",
        encoding="utf-8",
    )
    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "sha256sums": str(sums_path),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Generate the final control-plane adversarial audit pack")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--junit-xml", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--expected-champion-sha256", default=EXPECTED_CHAMPION_SHA256)
    p.add_argument(
        "--expected-drift-trust-root-sha256",
        default=os.environ.get("RELEASE_DRIFT_TRUST_ROOT_SHA256", ""),
    )
    p.add_argument("--require-external-trust-root", action="store_true")
    args = p.parse_args()

    report = _build_report(
        root=args.root,
        junit_xml=args.junit_xml,
        expected_champion_sha256=str(args.expected_champion_sha256).strip().lower(),
        expected_drift_trust_root_sha256=str(args.expected_drift_trust_root_sha256).strip().lower(),
    )
    paths = write_pack(output_dir=args.output_dir, report=report)
    print(json.dumps({"report": report, "paths": paths}, indent=2, sort_keys=True))

    if not report["audit_pack_pass"]:
        return 1
    if args.require_external_trust_root and not report["release_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
