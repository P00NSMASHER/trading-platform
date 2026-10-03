from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

INTEGRATION_BASE = "87ce85b2155ebb1abc12f9247d689a6a78e332ed"
STALE_BASE = "5a2dae64561880c736cb9eeb16b65f67d5894d29"
WORKFLOW = ".github/workflows/g1-public-batch-0077-worker-2.yml"
PROVENANCE_JSON = (
    "data/public/metadata/g1_public_batch_0077_evidence.json",
    "data/processed/authorized_input_real/g1_final_timing_exclusions.json",
    "data/public/metadata/g1_source_research_20260928.json",
)
GENERATOR = "scripts/g1_batch_0077_generate.py"
OWNERSHIP_TEST = "tests/test_g1_public_batch_0077.py"
ALLOWLIST = "config/release_drift_allowlist.json"

def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def _save(path: Path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _entry(allow: dict, path: str) -> dict:
    for section in ("intentional_release_modifications", "repository_additions"):
        if path in allow.get(section, {}):
            return allow[section][path]
    raise AssertionError(f"{path} is not tracked by release-drift policy")

def repair(root: Path) -> dict:
    changed = []
    for rel in PROVENANCE_JSON:
        path = root / rel
        data = _load(path)
        assert data.get("base_main_sha") in {STALE_BASE, INTEGRATION_BASE}, (rel, data.get("base_main_sha"))
        if data.get("base_main_sha") != INTEGRATION_BASE:
            data["base_main_sha"] = INTEGRATION_BASE
            _save(path, data)
            changed.append(rel)

    generator = root / GENERATOR
    text = generator.read_text(encoding="utf-8")
    old = f'BASE="{STALE_BASE}"'
    new = f'BASE="{INTEGRATION_BASE}"'
    assert old in text or new in text
    if old in text:
        assert text.count(old) == 1
        generator.write_text(text.replace(old, new, 1), encoding="utf-8")
        changed.append(GENERATOR)

    ownership = root / OWNERSHIP_TEST
    ownership_text = ownership.read_text(encoding="utf-8")
    assert "test_batch_0077_worker2_shard_ownership" in ownership_text
    assert "hashlib.sha256(eid.encode" in ownership_text
    assert not (root / WORKFLOW).exists()

    allow_path = root / ALLOWLIST
    allow = _load(allow_path)
    assert WORKFLOW not in allow.get("intentional_release_modifications", {})
    assert WORKFLOW not in allow.get("repository_additions", {})
    reason = (
        "G1 batch 0077 post-merge certification repair: bind provenance to actual PR #293 "
        "integration base 87ce85b; preserve 106 exact / 68 fail-closed; lock Worker-2 shard regression."
    )
    for rel in (*PROVENANCE_JSON, GENERATOR, OWNERSHIP_TEST):
        entry = _entry(allow, rel)
        entry["expected_sha256"] = _sha256(root / rel)
        entry["reason"] = reason
    _save(allow_path, allow)
    changed.append(ALLOWLIST)

    return {
        "integration_base_sha": INTEGRATION_BASE,
        "changed": changed,
        "exact_count": 106,
        "reviewed_fail_closed": 68,
        "ownership_test_sha256": _sha256(ownership),
    }

def validate(root: Path) -> dict:
    for rel in PROVENANCE_JSON:
        assert _load(root / rel)["base_main_sha"] == INTEGRATION_BASE
    generator = (root / GENERATOR).read_text(encoding="utf-8")
    assert f'BASE="{INTEGRATION_BASE}"' in generator
    assert STALE_BASE not in generator
    assert not (root / WORKFLOW).exists()

    allow = _load(root / ALLOWLIST)
    for rel in (*PROVENANCE_JSON, GENERATOR, OWNERSHIP_TEST):
        assert _entry(allow, rel)["expected_sha256"] == _sha256(root / rel)
    assert WORKFLOW not in allow.get("intentional_release_modifications", {})
    assert WORKFLOW not in allow.get("repository_additions", {})

    evidence = _load(root / "data/public/metadata/g1_public_batch_0077_evidence.json")
    exclusions = _load(root / "data/processed/authorized_input_real/g1_final_timing_exclusions.json")
    assert evidence["expected_exact_count_after_batch"] == 106
    assert evidence["expected_excluded_after_batch"] == 68
    assert len(evidence["items"]) == 5
    assert len(exclusions["exclusions"]) == 68
    return {"ok": True, "exact_count": 106, "reviewed_fail_closed": 68}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        print(json.dumps(repair(args.root), indent=2, sort_keys=True))
    print(json.dumps(validate(args.root), indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
