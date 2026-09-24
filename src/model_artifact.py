from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import joblib


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _validated_expected_sha256(expected_sha256: str) -> str:
    expected = str(expected_sha256 or "").strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("expected_sha256 must be a trusted 64-character SHA-256 hex digest")
    return expected


def verify_hash_before_load(path: Path, expected_sha256: str) -> str:
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    expected = _validated_expected_sha256(expected_sha256)
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"model artifact hash mismatch: actual={actual}; expected={expected}")
    return actual


def load_verified_joblib(path: Path, expected_sha256: str) -> Any:
    verify_hash_before_load(path, expected_sha256)
    return joblib.load(path)


def _skops_io():
    try:
        import skops.io as sio
    except ImportError as exc:
        raise RuntimeError(
            "skops is required for safer model persistence; install requirements-skops.lock"
        ) from exc
    return sio


def read_trusted_types(
    path: Path | None,
    *,
    expected_sha256: str | None = None,
) -> tuple[str, ...]:
    if path is None:
        return ()
    if expected_sha256 is not None:
        verify_hash_before_load(Path(path), expected_sha256)
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(obj, dict):
        values = obj.get("trusted_types", [])
    elif isinstance(obj, list):
        values = obj
    else:
        raise ValueError("trusted-types JSON must be an array or an object with trusted_types")
    if not isinstance(values, list) or not all(isinstance(x, str) and x.strip() for x in values):
        raise ValueError("trusted_types must be a list of non-blank strings")
    return tuple(sorted(set(x.strip() for x in values)))


def inspect_skops_types(path: Path) -> tuple[str, ...]:
    sio = _skops_io()
    unknown = sio.get_untrusted_types(file=str(Path(path)))
    return tuple(sorted(set(str(x) for x in unknown)))


def load_verified_skops(
    path: Path,
    expected_sha256: str,
    *,
    trusted_types_file: Path | None,
    expected_trusted_types_sha256: str | None,
) -> Any:
    verify_hash_before_load(path, expected_sha256)
    if trusted_types_file is None:
        raise ValueError("skops loading requires a reviewed trusted-types file")
    approved = set(read_trusted_types(
        trusted_types_file,
        expected_sha256=expected_trusted_types_sha256,
    ))
    unknown = set(inspect_skops_types(path))
    unapproved = sorted(unknown - approved)
    if unapproved:
        raise PermissionError(
            "skops artifact contains unapproved types; inspect and explicitly approve them: "
            + ", ".join(unapproved)
        )
    sio = _skops_io()
    return sio.load(str(Path(path)), trusted=sorted(approved))


def export_verified_joblib_to_skops(
    source_joblib: Path,
    expected_joblib_sha256: str,
    output_skops: Path,
    inspection_report: Path,
) -> dict[str, Any]:
    source_joblib = Path(source_joblib)
    output_skops = Path(output_skops)
    inspection_report = Path(inspection_report)
    bundle = load_verified_joblib(source_joblib, expected_joblib_sha256)
    sio = _skops_io()

    output_skops.parent.mkdir(parents=True, exist_ok=True)
    sio.dump(bundle, str(output_skops))
    unknown = inspect_skops_types(output_skops)
    result = {
        "schema_version": "1",
        "source_format": "joblib",
        "target_format": "skops",
        "source_path": str(source_joblib),
        "source_sha256": sha256_file(source_joblib),
        "output_path": str(output_skops),
        "output_sha256": sha256_file(output_skops),
        "untrusted_types": list(unknown),
        "explicit_type_review_required": bool(unknown),
        "runtime_load_permitted": not bool(unknown),
        "warning": (
            "Do not copy untrusted_types into the trusted list automatically. "
            "Review every type before approving runtime loading."
        ),
        "research_use_only": True,
    }
    inspection_report.parent.mkdir(parents=True, exist_ok=True)
    inspection_report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _cmd_export(args: argparse.Namespace) -> None:
    result = export_verified_joblib_to_skops(
        args.source_joblib,
        args.expected_joblib_sha256,
        args.output_skops,
        args.inspection_report,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _cmd_inspect(args: argparse.Namespace) -> None:
    actual = verify_hash_before_load(args.skops_file, args.expected_sha256)
    print(json.dumps({
        "path": str(args.skops_file),
        "sha256": actual,
        "untrusted_types": list(inspect_skops_types(args.skops_file)),
    }, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Verified model artifact migration and inspection")
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("export-skops")
    e.add_argument("--source-joblib", type=Path, required=True)
    e.add_argument("--expected-joblib-sha256", required=True)
    e.add_argument("--output-skops", type=Path, required=True)
    e.add_argument("--inspection-report", type=Path, required=True)
    e.set_defaults(func=_cmd_export)

    i = sub.add_parser("inspect-skops")
    i.add_argument("--skops-file", type=Path, required=True)
    i.add_argument("--expected-sha256", required=True)
    i.set_defaults(func=_cmd_inspect)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
