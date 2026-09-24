from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Iterable


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha1(path: Path) -> str:
    data = Path(path).read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _read_json(path: Path) -> dict:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return obj


def _parse_sums(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ValueError(f"invalid SHA256SUMS row {line_no}")
        out[parts[1].strip()] = parts[0].lower()
    return out


def _tracked_paths(root: Path) -> set[str]:
    root = root.resolve()
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return {x for x in proc.stdout.decode("utf-8").split("\0") if x}
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return {
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.parts
        }


def _exception_map(raw: dict, key: str) -> dict[str, dict]:
    block = raw.get(key, {})
    if not isinstance(block, dict):
        raise ValueError(f"{key} must be an object keyed by repository path")
    out: dict[str, dict] = {}
    for path, detail in block.items():
        if not isinstance(path, str) or not path.strip() or not isinstance(detail, dict):
            raise ValueError(f"invalid {key} entry")
        blob = str(detail.get("expected_git_blob_sha1", "")).strip().lower()
        reason = str(detail.get("reason", "")).strip()
        if len(blob) != 40 or any(ch not in "0123456789abcdef" for ch in blob):
            raise ValueError(f"{key}.{path} requires expected_git_blob_sha1")
        if not reason:
            raise ValueError(f"{key}.{path} requires a reason")
        out[path] = {"expected_git_blob_sha1": blob, "reason": reason}
    return out


def verify_release_drift(
    *,
    root: Path,
    release_manifest: Path,
    sha256sums: Path,
    exceptions: Path,
    tracked_paths: Iterable[str] | None = None,
) -> dict:
    root = root.resolve()
    manifest = _read_json(release_manifest)
    exception_raw = _read_json(exceptions)
    historical_sums = _parse_sums(sha256sums)

    entries = manifest.get("files", [])
    if not isinstance(entries, list):
        raise ValueError("release manifest files must be a list")
    release = {str(x["path"]): x for x in entries}
    modified = _exception_map(exception_raw, "intentional_release_modifications")
    additions = _exception_map(exception_raw, "repository_additions")

    if set(modified) - set(release):
        raise ValueError("intentional_release_modifications contains paths absent from historical release")
    if set(additions) & set(release):
        raise ValueError("repository_additions overlaps historical release paths")

    tracked = set(tracked_paths) if tracked_paths is not None else _tracked_paths(root)
    known = set(release) | set(additions)
    try:
        trust_root_path = exceptions.resolve().relative_to(root).as_posix()
    except ValueError:
        trust_root_path = str(exceptions.resolve())
    if not Path(trust_root_path).is_absolute():
        known.add(trust_root_path)
    unexpected_tracked = sorted(tracked - known)
    missing_tracked = sorted((set(release) | set(additions)) - tracked)

    checks: list[dict] = []
    for path, entry in sorted(release.items()):
        full = root / path
        if path in modified:
            exists = full.is_file()
            actual_blob = git_blob_sha1(full) if exists else ""
            expected_blob = modified[path]["expected_git_blob_sha1"]
            checks.append({
                "path": path,
                "status": "intentional_modified",
                "ok": exists and actual_blob == expected_blob,
                "actual_git_blob_sha1": actual_blob,
                "expected_git_blob_sha1": expected_blob,
                "reason": modified[path]["reason"],
            })
            continue

        exists = full.is_file()
        actual_sha = sha256_file(full) if exists else ""
        actual_size = full.stat().st_size if exists else -1
        expected_sha = str(entry.get("sha256", "")).lower()
        expected_size = int(entry.get("size_bytes", -1))
        sums_sha = historical_sums.get(path, "")
        ok = (
            exists
            and actual_sha == expected_sha
            and actual_size == expected_size
            and (not sums_sha or sums_sha == expected_sha)
        )
        checks.append({
            "path": path,
            "status": "historical_unchanged",
            "ok": ok,
            "actual_sha256": actual_sha,
            "expected_sha256": expected_sha,
            "actual_size_bytes": actual_size,
            "expected_size_bytes": expected_size,
            "sha256sums_agrees": (not sums_sha or sums_sha == expected_sha),
        })

    for path, detail in sorted(additions.items()):
        full = root / path
        exists = full.is_file()
        actual_blob = git_blob_sha1(full) if exists else ""
        checks.append({
            "path": path,
            "status": "repository_addition",
            "ok": exists and actual_blob == detail["expected_git_blob_sha1"],
            "actual_git_blob_sha1": actual_blob,
            "expected_git_blob_sha1": detail["expected_git_blob_sha1"],
            "reason": detail["reason"],
        })

    failed = [x for x in checks if not x["ok"]]
    try:
        manifest_rel = release_manifest.resolve().relative_to(root).as_posix()
    except ValueError:
        manifest_rel = str(release_manifest.resolve())
    manifest_self_expected = historical_sums.get(manifest_rel, "")
    manifest_self_actual = sha256_file(release_manifest)
    manifest_self_hash_ok = (
        not manifest_self_expected or manifest_self_actual == manifest_self_expected
    )
    ok = (
        not failed
        and not unexpected_tracked
        and not missing_tracked
        and manifest_self_hash_ok
    )
    return {
        "schema_version": "1",
        "historical_release_file_count": len(release),
        "intentional_modified_count": len(modified),
        "repository_addition_count": len(additions),
        "tracked_file_count": len(tracked),
        "trust_root_path": trust_root_path,
        "unexpected_tracked_paths": unexpected_tracked,
        "missing_tracked_paths": missing_tracked,
        "failed_check_count": len(failed),
        "historical_manifest_sha256": manifest_self_actual,
        "historical_manifest_expected_sha256": manifest_self_expected or None,
        "historical_manifest_hash_ok": manifest_self_hash_ok,
        "ok": ok,
        "checks": checks,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Verify repository drift from the historical release manifest")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--release-manifest", type=Path, default=Path("RELEASE_MANIFEST.json"))
    p.add_argument("--sha256sums", type=Path, default=Path("SHA256SUMS"))
    p.add_argument("--exceptions", type=Path, default=Path("config/release_drift_allowlist.json"))
    p.add_argument("--output", type=Path)
    args = p.parse_args()

    result = verify_release_drift(
        root=args.root,
        release_manifest=args.release_manifest,
        sha256sums=args.sha256sums,
        exceptions=args.exceptions,
    )
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
