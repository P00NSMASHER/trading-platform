from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_release_drift as drift

SCHEMA_VERSION = "1"
DEFAULT_NAMESPACE = "mnpi-release"
DEFAULT_CHAMPION = Path("data/processed/model_demo/model_bundle.joblib")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _validated_sha256(value: str, *, label: str) -> str:
    value = str(value or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{label} must be a trusted 64-character SHA-256 hex digest")
    return value


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root.resolve()), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.stdout.strip()


def tracked_paths(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root.resolve()), "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return sorted(x for x in proc.stdout.decode("utf-8").split("\0") if x)


def tracked_tree_sha256(root: Path) -> tuple[str, int]:
    root = root.resolve()
    h = hashlib.sha256()
    count = 0
    for rel in tracked_paths(root):
        path = root / rel
        if not path.is_file():
            raise ValueError(f"tracked path is not a regular file: {rel}")
        digest = sha256_file(path)
        size = path.stat().st_size
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(digest.encode("ascii"))
        h.update(b"\0")
        h.update(str(size).encode("ascii"))
        h.update(b"\n")
        count += 1
    return h.hexdigest(), count


def _require_clean_tracked_tree(root: Path) -> None:
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise ValueError("tracked working tree must be clean before building/verifying an attestation")


def build_attestation(
    *,
    root: Path,
    expected_drift_trust_root_sha256: str,
    expected_champion_sha256: str,
) -> dict[str, Any]:
    root = root.resolve()
    _require_clean_tracked_tree(root)

    drift_hash = _validated_sha256(
        expected_drift_trust_root_sha256, label="expected_drift_trust_root_sha256"
    )
    champion_hash = _validated_sha256(
        expected_champion_sha256, label="expected_champion_sha256"
    )

    release_manifest = root / "RELEASE_MANIFEST.json"
    sha256sums = root / "SHA256SUMS"
    exceptions = root / "config/release_drift_allowlist.json"
    champion = root / DEFAULT_CHAMPION

    drift_result = drift.verify_release_drift(
        root=root,
        release_manifest=release_manifest,
        sha256sums=sha256sums,
        exceptions=exceptions,
        expected_exceptions_sha256=drift_hash,
    )
    if not drift_result.get("ok"):
        raise ValueError("release drift verification failed; refusing to build attestation")

    actual_champion = sha256_file(champion)
    if actual_champion != champion_hash:
        raise ValueError(
            f"champion hash mismatch: actual={actual_champion}; expected={champion_hash}"
        )

    tree_hash, tracked_count = tracked_tree_sha256(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "attestation_type": "private_surveillance_release",
        "signature_namespace": DEFAULT_NAMESPACE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "git_commit": _git(root, "rev-parse", "HEAD"),
        "tracked_tree_sha256": tree_hash,
        "tracked_file_count": tracked_count,
        "historical_release_manifest_sha256": sha256_file(release_manifest),
        "sha256sums_sha256": sha256_file(sha256sums),
        "drift_allowlist_sha256": sha256_file(exceptions),
        "champion_sha256": actual_champion,
        "research_use_only": True,
        "prohibited_capabilities": [
            "broker_connectivity",
            "order_generation",
            "trade_recommendations",
            "position_sizing",
            "expected_return_outputs",
        ],
    }


def write_attestation(path: Path, attestation: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sign_attestation(
    *,
    attestation: Path,
    private_key: Path,
    namespace: str = DEFAULT_NAMESPACE,
) -> Path:
    attestation = Path(attestation)
    private_key = Path(private_key)
    if not attestation.is_file():
        raise FileNotFoundError(attestation)
    if not private_key.is_file():
        raise FileNotFoundError(private_key)
    subprocess.run(
        [
            "ssh-keygen", "-Y", "sign",
            "-f", str(private_key),
            "-n", namespace,
            str(attestation),
        ],
        check=True,
    )
    signature = Path(str(attestation) + ".sig")
    if not signature.is_file():
        raise RuntimeError(f"ssh-keygen did not create expected signature file: {signature}")
    return signature


def _verify_ssh_signature(
    *,
    attestation: Path,
    signature: Path,
    allowed_signers: Path,
    expected_allowed_signers_sha256: str,
    identity: str,
    namespace: str,
) -> None:
    expected = _validated_sha256(
        expected_allowed_signers_sha256, label="expected_allowed_signers_sha256"
    )
    actual = sha256_file(allowed_signers)
    if actual != expected:
        raise ValueError(
            f"allowed-signers hash mismatch: actual={actual}; expected={expected}"
        )
    if not identity.strip():
        raise ValueError("identity is required for SSH signature verification")
    proc = subprocess.run(
        [
            "ssh-keygen", "-Y", "verify",
            "-f", str(allowed_signers),
            "-I", identity,
            "-n", namespace,
            "-s", str(signature),
        ],
        input=Path(attestation).read_bytes(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise PermissionError(f"release attestation signature verification failed: {detail}")


def verify_attestation_against_checkout(*, root: Path, attestation: dict[str, Any]) -> dict[str, Any]:
    root = root.resolve()
    _require_clean_tracked_tree(root)

    if attestation.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported attestation schema_version")
    if attestation.get("signature_namespace") != DEFAULT_NAMESPACE:
        raise ValueError(f"attestation signature_namespace must equal {DEFAULT_NAMESPACE!r}")
    if attestation.get("research_use_only") is not True:
        raise ValueError("attestation must preserve research_use_only=true")

    required_prohibitions = {
        "broker_connectivity",
        "order_generation",
        "trade_recommendations",
        "position_sizing",
        "expected_return_outputs",
    }
    if not required_prohibitions.issubset(set(attestation.get("prohibited_capabilities", []))):
        raise ValueError("attestation is missing required prohibited capabilities")

    expected_commit = str(attestation.get("git_commit", "")).strip()
    actual_commit = _git(root, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise ValueError(f"git commit mismatch: actual={actual_commit}; expected={expected_commit}")

    tree_hash, tracked_count = tracked_tree_sha256(root)
    if tree_hash != attestation.get("tracked_tree_sha256"):
        raise ValueError("tracked tree SHA-256 mismatch")
    if tracked_count != int(attestation.get("tracked_file_count", -1)):
        raise ValueError("tracked file count mismatch")

    release_manifest = root / "RELEASE_MANIFEST.json"
    sha256sums = root / "SHA256SUMS"
    exceptions = root / "config/release_drift_allowlist.json"
    champion = root / DEFAULT_CHAMPION

    checks = {
        "historical_release_manifest_sha256": sha256_file(release_manifest),
        "sha256sums_sha256": sha256_file(sha256sums),
        "drift_allowlist_sha256": sha256_file(exceptions),
        "champion_sha256": sha256_file(champion),
    }
    for key, actual in checks.items():
        expected = str(attestation.get(key, "")).strip().lower()
        if actual != expected:
            raise ValueError(f"{key} mismatch: actual={actual}; expected={expected}")

    drift_result = drift.verify_release_drift(
        root=root,
        release_manifest=release_manifest,
        sha256sums=sha256sums,
        exceptions=exceptions,
        expected_exceptions_sha256=checks["drift_allowlist_sha256"],
    )
    if not drift_result.get("ok"):
        raise ValueError("signed checkout fails release drift verification")

    return {
        "ok": True,
        "git_commit": actual_commit,
        "tracked_tree_sha256": tree_hash,
        "tracked_file_count": tracked_count,
        "champion_sha256": checks["champion_sha256"],
        "drift_allowlist_sha256": checks["drift_allowlist_sha256"],
        "research_use_only": True,
    }


def verify_signed_attestation(
    *,
    root: Path,
    attestation_path: Path,
    signature: Path,
    allowed_signers: Path,
    expected_allowed_signers_sha256: str,
    identity: str,
) -> dict[str, Any]:
    attestation = json.loads(Path(attestation_path).read_text(encoding="utf-8"))
    if not isinstance(attestation, dict):
        raise ValueError("attestation JSON root must be an object")
    namespace = str(attestation.get("signature_namespace", DEFAULT_NAMESPACE))
    _verify_ssh_signature(
        attestation=attestation_path,
        signature=signature,
        allowed_signers=allowed_signers,
        expected_allowed_signers_sha256=expected_allowed_signers_sha256,
        identity=identity,
        namespace=namespace,
    )
    result = verify_attestation_against_checkout(root=root, attestation=attestation)
    result["signature_verified"] = True
    result["signer_identity"] = identity
    result["allowed_signers_sha256"] = sha256_file(allowed_signers)
    return result


def main() -> int:
    p = argparse.ArgumentParser(description="Build, sign, and verify external release attestations")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build")
    b.add_argument("--root", type=Path, default=Path.cwd())
    b.add_argument("--expected-drift-trust-root-sha256", required=True)
    b.add_argument("--expected-champion-sha256", required=True)
    b.add_argument("--output", type=Path, required=True)

    s = sub.add_parser("sign")
    s.add_argument("--attestation", type=Path, required=True)
    s.add_argument("--private-key", type=Path, required=True)
    s.add_argument("--namespace", default=DEFAULT_NAMESPACE)

    v = sub.add_parser("verify")
    v.add_argument("--root", type=Path, default=Path.cwd())
    v.add_argument("--attestation", type=Path, required=True)
    v.add_argument("--signature", type=Path, required=True)
    v.add_argument("--allowed-signers", type=Path, required=True)
    v.add_argument("--expected-allowed-signers-sha256", required=True)
    v.add_argument("--identity", required=True)

    args = p.parse_args()
    if args.command == "build":
        att = build_attestation(
            root=args.root,
            expected_drift_trust_root_sha256=args.expected_drift_trust_root_sha256,
            expected_champion_sha256=args.expected_champion_sha256,
        )
        write_attestation(args.output, att)
        print(json.dumps(att, indent=2, sort_keys=True))
        return 0
    if args.command == "sign":
        sig = sign_attestation(
            attestation=args.attestation,
            private_key=args.private_key,
            namespace=args.namespace,
        )
        print(sig)
        return 0
    result = verify_signed_attestation(
        root=args.root,
        attestation_path=args.attestation,
        signature=args.signature,
        allowed_signers=args.allowed_signers,
        expected_allowed_signers_sha256=args.expected_allowed_signers_sha256,
        identity=args.identity,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
