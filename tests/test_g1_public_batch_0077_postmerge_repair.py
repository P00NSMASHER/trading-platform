from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/g1_batch_0077_postmerge_repair.py"

def _module():
    spec = importlib.util.spec_from_file_location("g1_batch_0077_postmerge_repair", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module

def test_postmerge_repair_is_narrow_and_deterministic(tmp_path):
    repair = _module()
    needed = [
        *repair.PROVENANCE_JSON,
        repair.GENERATOR,
        repair.OWNERSHIP_TEST,
        repair.ALLOWLIST,
    ]
    for rel in needed:
        src = ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    result = repair.repair(tmp_path)
    validated = repair.validate(tmp_path)
    assert validated["ok"] is True
    assert result["integration_base_sha"] == repair.INTEGRATION_BASE
    assert result["exact_count"] == 106
    assert result["reviewed_fail_closed"] == 68

    evidence = json.loads((tmp_path / repair.PROVENANCE_JSON[0]).read_text())
    assert evidence["base_main_sha"] == repair.INTEGRATION_BASE
    assert len(evidence["items"]) == 5

def test_postmerge_repair_never_reintroduces_publisher(tmp_path):
    repair = _module()
    needed = [
        *repair.PROVENANCE_JSON,
        repair.GENERATOR,
        repair.OWNERSHIP_TEST,
        repair.ALLOWLIST,
    ]
    for rel in needed:
        src = ROOT / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    repair.repair(tmp_path)
    allow = json.loads((tmp_path / repair.ALLOWLIST).read_text())
    assert repair.WORKFLOW not in allow.get("repository_additions", {})
    assert repair.WORKFLOW not in allow.get("intentional_release_modifications", {})
    assert not (tmp_path / repair.WORKFLOW).exists()
