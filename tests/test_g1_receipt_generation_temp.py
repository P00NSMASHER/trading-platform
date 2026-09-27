from __future__ import annotations

import base64
import json
from pathlib import Path

import metadata_quality
import metadata_resolver
import real_data_replay
import software_readiness_certification


def test_emit_g1_authoritative_receipts() -> None:
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
    software_readiness_certification.certify(
        root,
        runtime_config=root / "config/runtime.demo.toml",
        output_path=root / "data/processed/software_readiness/software_readiness_certification.json",
        run_tests=True,
    )

    targets = [
        "data/processed/authorized_input_real/announcement_resolutions.csv",
        "data/processed/authorized_input_real/metadata_domain_quality.csv",
        "data/processed/authorized_input_real/metadata_quality_summary.json",
        "data/processed/authorized_input_real/metadata_readiness_summary.json",
        "data/processed/authorized_input_real/metadata_source_inventory.json",
        "data/processed/authorized_input_real/metadata_unresolved_gates.csv",
        "data/processed/real_data_replay/real_data_replay_status.json",
        "data/processed/software_readiness/software_readiness_certification.json",
    ]
    payload = {
        path: base64.b64encode((root / path).read_bytes()).decode("ascii")
        for path in targets
    }
    raise AssertionError(
        "G1_RECEIPTS_BEGIN\\n" + json.dumps(payload, sort_keys=True) + "\\nG1_RECEIPTS_END"
    )
