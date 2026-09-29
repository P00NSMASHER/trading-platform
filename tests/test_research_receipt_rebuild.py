from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import research_receipt_rebuild as rebuild


def test_current_receipts_reproduce_from_canonical_inputs(tmp_path: Path):
    candidates = rebuild.build_candidate_receipts(ROOT, tmp_path / "stage")
    report = rebuild.compare_current(ROOT, candidates)
    assert report["up_to_date"] is True
    assert report["changed"] == []
    assert report["missing"] == []
    assert rebuild.BUNDLE_MANIFEST_TARGET in candidates


def test_bundle_manifest_is_order_independent(tmp_path: Path):
    root = tmp_path
    for path in rebuild._canonical_inputs(root).values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")
    a = {Path("data/b.csv"): b"b", Path("data/a.csv"): b"a"}
    b = {Path("data/a.csv"): b"a", Path("data/b.csv"): b"b"}
    summary = {
        "announcement_exact_resolved": 1, "announcement_events_excluded": 1,
        "announcement_unresolved": 0, "event_count": 2, "control_dates_resolved": 0,
        "control_dates_required": 1, "replay_ready": False,
        "evaluation_release_permitted": False,
    }
    assert rebuild._bundle_manifest(root, a, summary) == rebuild._bundle_manifest(root, b, summary)


def test_publish_transaction_rolls_back_and_never_leaves_partial_manifest(tmp_path: Path):
    root = tmp_path
    first = Path("data/processed/authorized_input_real/a.txt")
    second = Path("data/processed/authorized_input_real/b.txt")
    manifest = rebuild.BUNDLE_MANIFEST_TARGET
    for path, content in [(first, b"old-a"), (second, b"old-b"), (manifest, b"old-manifest")]:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    candidates = {first: b"new-a", second: b"new-b", manifest: b"new-manifest"}
    calls = 0

    def fail_on_second(src, dst):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated publish interruption")
        os.replace(src, dst)

    with pytest.raises(OSError, match="simulated publish interruption"):
        rebuild.publish_transaction(root, candidates, replace_func=fail_on_second)

    assert (root / first).read_bytes() == b"old-a"
    assert (root / second).read_bytes() == b"old-b"
    assert (root / manifest).read_bytes() == b"old-manifest"


def test_manifest_is_always_published_last(tmp_path: Path):
    root = tmp_path
    first = Path("data/processed/authorized_input_real/a.txt")
    manifest = rebuild.BUNDLE_MANIFEST_TARGET
    seen = []

    def record_replace(src, dst):
        seen.append(Path(dst).relative_to(root))
        os.replace(src, dst)

    rebuild.publish_transaction(root, {manifest: b"manifest", first: b"a"}, replace_func=record_replace)
    assert seen[-1] == manifest
