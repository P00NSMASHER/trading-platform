from __future__ import annotations

import base64
from pathlib import Path

import g1_acquisition_manifest as g1a


def test_emit_acadia_acquisition_manifest() -> None:
    rendered = g1a.render_manifest(g1a.build_manifest())
    encoded = base64.b64encode(rendered.encode("utf-8")).decode("ascii")
    print(f"ACHC_ACQUISITION_MANIFEST_BEGIN::{encoded}::ACHC_ACQUISITION_MANIFEST_END")
    raise AssertionError("ACHC_ACQUISITION_MANIFEST_EMITTED")
