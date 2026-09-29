from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Mapping

import metadata_quality
import metadata_resolver
import real_data_replay

SCHEMA_VERSION = "1"
METADATA_TARGET_DIR = Path("data/processed/authorized_input_real")
REPLAY_STATUS_TARGET = Path("data/processed/real_data_replay/real_data_replay_status.json")
BUNDLE_MANIFEST_TARGET = Path("data/processed/research_receipt_bundle.json")

METADATA_RECEIPTS = (
    "announcement_resolutions.csv",
    "event_exchange_resolutions.csv",
    "shares_outstanding_resolutions.csv",
    "control_universe_readiness.csv",
    "metadata_source_inventory.json",
    "metadata_readiness_summary.json",
    "metadata_unresolved_gates.csv",
    "metadata_quality_issues.csv",
    "metadata_domain_quality.csv",
    "metadata_quarantine.csv",
    "metadata_quality_summary.json",
    "metadata_quality_gate.csv",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict, *, trailing_newline: bool = False) -> None:
    rendered = json.dumps(payload, indent=2)
    if trailing_newline:
        rendered += "\n"
    path.write_text(rendered, encoding="utf-8")


def _canonical_inputs(root: Path) -> dict[str, Path]:
    return {
        "events": root / "data/processed/historical_events.csv",
        "symbol_date_requirements": root / "data/processed/coverage_plan_real/symbol_date_requirements.csv",
        "metadata_contract": root / "config/metadata_sources.public_progress.json",
        "replay_config": root / "config/real_data_replay.software_proof.json",
    }


def _validate_candidates(root: Path, stage_metadata: Path, stage_replay: Path) -> dict:
    readiness = _read_json(stage_metadata / "metadata_readiness_summary.json")
    quality = _read_json(stage_metadata / "metadata_quality_summary.json")
    replay = _read_json(stage_replay / "real_data_replay_status.json")

    event_count = int(readiness.get("event_count", 0) or 0)
    exact = int(readiness.get("announcement_exact_resolved", 0) or 0)
    excluded = int(readiness.get("announcement_events_excluded", 0) or 0)
    unresolved = int(readiness.get("announcement_unresolved", 0) or 0)
    if exact + excluded + unresolved != event_count:
        raise ValueError("announcement receipt counts do not reconcile to event_count")
    if not bool(readiness.get("ready_g1_announcement_times")):
        raise ValueError("G1 receipt bundle is not fully accounted under exact evidence plus reviewed exclusions")
    if int(quality.get("reviewed_announcement_exclusion_count", -1)) != excluded:
        raise ValueError("metadata quality exclusion count disagrees with readiness receipt")

    metadata_stage = replay.get("stages", {}).get("metadata", {})
    if int(metadata_stage.get("announcement_exact_resolved", -1)) != exact:
        raise ValueError("replay metadata exact-count disagrees with authoritative readiness receipt")
    if int(metadata_stage.get("announcement_required", -1)) != event_count:
        raise ValueError("replay metadata required-count disagrees with authoritative readiness receipt")

    return {
        "announcement_exact_resolved": exact,
        "announcement_events_excluded": excluded,
        "announcement_unresolved": unresolved,
        "event_count": event_count,
        "control_dates_resolved": int(readiness.get("control_dates_resolved", 0) or 0),
        "control_dates_required": int(readiness.get("event_date_count", 0) or 0),
        "replay_ready": bool(replay.get("ready_for_non_synthetic_offline_evaluation")),
        "evaluation_release_permitted": bool(replay.get("evaluation_release_permitted")),
    }


def _bundle_manifest(root: Path, receipts: Mapping[Path, bytes], summary: dict) -> bytes:
    inputs = _canonical_inputs(root)
    receipt_hashes = {
        path.as_posix(): _sha256_bytes(data)
        for path, data in sorted(receipts.items(), key=lambda item: item[0].as_posix())
    }
    bundle_material = "".join(
        f"{path}\0{digest}\n" for path, digest in sorted(receipt_hashes.items())
    ).encode("utf-8")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Deterministic manifest for one coherent metadata/quality/real-data-replay receipt generation.",
        "research_use_only": True,
        "input_sha256": {name: _sha256(path) for name, path in sorted(inputs.items())},
        "receipt_sha256": receipt_hashes,
        "bundle_sha256": _sha256_bytes(bundle_material),
        "summary": summary,
        "publication_policy": {
            "all_candidates_validated_before_publish": True,
            "manifest_published_last": True,
            "rollback_on_publish_failure": True,
            "partial_bundle_without_matching_manifest_is_invalid": True,
            "software_readiness_certification_separate": True,
            "software_certification_reason": (
                "software certification executes live hostile/runtime checks and is intentionally "
                "not a deterministic receipt artifact"
            ),
        },
    }
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_candidate_receipts(root: Path, staging_root: Path) -> dict[Path, bytes]:
    root = root.resolve()
    staging_root = staging_root.resolve()
    inputs = _canonical_inputs(root)
    missing = [str(path) for path in inputs.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"receipt rebuild inputs are missing: {missing}")

    stage_metadata = staging_root / "authorized_input_real"
    stage_metadata.mkdir(parents=True, exist_ok=True)
    metadata_resolver.build(
        inputs["events"], inputs["symbol_date_requirements"], inputs["metadata_contract"], stage_metadata
    )
    metadata_quality.build(
        events_path=inputs["events"],
        symbol_dates_path=inputs["symbol_date_requirements"],
        contract_path=inputs["metadata_contract"],
        resolver_dir=stage_metadata,
        outdir=stage_metadata,
    )

    quality_path = stage_metadata / "metadata_quality_summary.json"
    quality = _read_json(quality_path)
    quality["resolver_dir"] = str(root / METADATA_TARGET_DIR)
    quality["resolver_summary_sha256"] = _sha256(stage_metadata / "metadata_readiness_summary.json")
    _write_json(quality_path, quality)

    stage_replay = staging_root / "real_data_replay"
    real_data_replay.run_replay(inputs["replay_config"], output_dir_override=stage_replay)

    summary = _validate_candidates(root, stage_metadata, stage_replay)
    receipts: dict[Path, bytes] = {}
    for name in METADATA_RECEIPTS:
        source = stage_metadata / name
        if not source.exists():
            raise FileNotFoundError(f"expected metadata receipt was not generated: {source}")
        receipts[METADATA_TARGET_DIR / name] = source.read_bytes()
    receipts[REPLAY_STATUS_TARGET] = (stage_replay / "real_data_replay_status.json").read_bytes()
    receipts[BUNDLE_MANIFEST_TARGET] = _bundle_manifest(root, receipts, summary)
    return receipts


def compare_current(root: Path, candidates: Mapping[Path, bytes]) -> dict:
    root = root.resolve()
    changed, missing = [], []
    for relative, expected in sorted(candidates.items(), key=lambda item: item[0].as_posix()):
        target = root / relative
        if not target.exists():
            missing.append(relative.as_posix())
        elif target.read_bytes() != expected:
            changed.append(relative.as_posix())
    return {
        "up_to_date": not changed and not missing,
        "changed": changed,
        "missing": missing,
        "candidate_count": len(candidates),
    }


def _atomic_replace_bytes(target: Path, data: bytes, *, replace_func: Callable = os.replace) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.receipt-", dir=target.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        replace_func(temp, target)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def _publication_lock(root: Path):
    lock_path = root / "data/processed/.research_receipt_rebuild.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:
        fcntl = None
    with lock_path.open("a+b") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def publish_transaction(root: Path, candidates: Mapping[Path, bytes], *, replace_func: Callable = os.replace) -> list[str]:
    root = root.resolve()
    ordered = sorted(
        (path for path in candidates if path != BUNDLE_MANIFEST_TARGET),
        key=lambda p: p.as_posix(),
    ) + [BUNDLE_MANIFEST_TARGET]
    originals: dict[Path, bytes | None] = {}
    replaced: list[Path] = []

    with _publication_lock(root):
        try:
            for relative in ordered:
                target = root / relative
                originals[target] = target.read_bytes() if target.exists() else None
                _atomic_replace_bytes(target, candidates[relative], replace_func=replace_func)
                replaced.append(target)
        except Exception:
            for target in reversed(replaced):
                original = originals[target]
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    _atomic_replace_bytes(target, original, replace_func=os.replace)
            raise

    return [str(path.relative_to(root)) for path in replaced]


def rebuild(root: Path, *, publish: bool = False) -> dict:
    root = root.resolve()
    with tempfile.TemporaryDirectory(prefix="research-receipts-") as td:
        candidates = build_candidate_receipts(root, Path(td))
        before = compare_current(root, candidates)
        published = publish_transaction(root, candidates) if publish else []
        after = compare_current(root, candidates)
    return {
        "schema_version": SCHEMA_VERSION,
        "publish_requested": publish,
        "before": before,
        "published": published,
        "after": after,
        "software_certification_separate": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild one coherent research metadata/quality/replay receipt bundle."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--publish", action="store_true")
    args = parser.parse_args()

    result = rebuild(args.root, publish=args.publish)
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.check and not result["before"]["up_to_date"]:
        return 2
    if args.publish and not result["after"]["up_to_date"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
