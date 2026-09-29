from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import research_receipt_rebuild as rebuild


def test_emit_changed_acadia_receipts() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="achc-receipts-") as td:
        candidates = rebuild.build_candidate_receipts(root, Path(td))
        report = rebuild.compare_current(root, candidates)
        for rel in report["changed"] + report["missing"]:
            path = Path(rel)
            encoded = base64.b64encode(candidates[path]).decode("ascii")
            print(f"ACHC_RECEIPT_BEGIN::{rel}::{encoded}::ACHC_RECEIPT_END")
        raise AssertionError(
            "ACHC_RECEIPTS_EMITTED changed="
            + ",".join(report["changed"])
            + " missing="
            + ",".join(report["missing"])
        )
