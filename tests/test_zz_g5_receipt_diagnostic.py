from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import research_receipt_rebuild as rebuild


def test_dump_stale_receipt_candidates(tmp_path: Path):
    candidates = rebuild.build_candidate_receipts(ROOT, tmp_path / "stage")
    report = rebuild.compare_current(ROOT, candidates)
    payload = {
        "report": report,
        "candidates_base64": {
            path: base64.b64encode(candidates[Path(path)]).decode("ascii")
            for path in report["changed"]
        },
    }
    print("G5_RECEIPT_DIAGNOSTIC=" + json.dumps(payload, sort_keys=True))
    assert False, "intentional receipt diagnostic"
