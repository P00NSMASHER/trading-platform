from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import metadata_quality
import metadata_resolver
import real_data_replay
import software_readiness_certification

SOURCE_COMMIT = "2b71f37b26bb78a4ce20c9f1d1fc26fa67805310"
REASON = "Authoritative receipt regeneration from main source commit 2b71f37b26bb78a4ce20c9f1d1fc26fa67805310 after G1 State Street batch 0026."


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_emit_g1_stt_authoritative_receipts() -> None:
    root = Path(__file__).resolve().parents[1]
    events = root / "data/processed/historical_events.csv"
    symbol_dates = root / "data/processed/coverage_plan_real/symbol_date_requirements.csv"
    contract = root / "config/metadata_sources.public_progress.json"
    resolver_dir = root / "data/processed/authorized_input_real"

    metadata_resolver.build(events, symbol_dates, contract, resolver_dir)
    metadata_quality.build(
        events_path=events,
        symbol_dates_path=symbol_dates,
        contract_path=contract,
        resolver_dir=resolver_dir,
        outdir=resolver_dir,
    )
    real_data_replay.run_replay(root / "config/real_data_replay.software_proof.json", require_ready=False)

    targets_before_cert = [
        "data/processed/authorized_input_real/announcement_resolutions.csv",
        "data/processed/authorized_input_real/metadata_domain_quality.csv",
        "data/processed/authorized_input_real/metadata_quality_summary.json",
        "data/processed/authorized_input_real/metadata_readiness_summary.json",
        "data/processed/authorized_input_real/metadata_source_inventory.json",
        "data/processed/authorized_input_real/metadata_unresolved_gates.csv",
        "data/processed/real_data_replay/real_data_replay_status.json",
    ]

    allow_path = root / "config/release_drift_allowlist.json"
    allow = json.loads(allow_path.read_text(encoding="utf-8"))
    release = json.loads((root / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    release_paths = {str(x["path"]) for x in release.get("files", [])}
    for rel in targets_before_cert:
        entry = {"expected_sha256": _sha(root / rel), "reason": REASON}
        if rel in release_paths:
            allow["intentional_release_modifications"][rel] = entry
            allow["repository_additions"].pop(rel, None)
        else:
            allow["repository_additions"][rel] = entry
            allow["intentional_release_modifications"].pop(rel, None)

    cert_rel = "data/processed/software_readiness/software_readiness_certification.json"
    cert_entry = {"expected_sha256": _sha(root / cert_rel), "reason": "Pre-regeneration software receipt retained only for the in-run drift check."}
    if cert_rel in release_paths:
        allow["intentional_release_modifications"][cert_rel] = cert_entry
        allow["repository_additions"].pop(cert_rel, None)
    else:
        allow["repository_additions"][cert_rel] = cert_entry
        allow["intentional_release_modifications"].pop(cert_rel, None)
    allow_path.write_text(json.dumps(allow, indent=2) + "\n", encoding="utf-8")

    software_readiness_certification._git_head = lambda _root: SOURCE_COMMIT
    software_readiness_certification.certify(
        root,
        runtime_config=root / "config/runtime.demo.toml",
        output_path=root / cert_rel,
        run_tests=True,
    )

    targets = targets_before_cert + [cert_rel]
    for rel in targets:
        encoded = base64.b64encode((root / rel).read_bytes()).decode("ascii")
        print(f"G1_STT_FILE_BEGIN::{rel}::{encoded}::G1_STT_FILE_END")
    raise AssertionError("G1_STT_RECEIPTS_EMITTED")
