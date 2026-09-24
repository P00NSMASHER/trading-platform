from __future__ import annotations

import csv
import json
from datetime import timedelta
from pathlib import Path

import authorized_input_orchestrator as aio
import coverage_planner

ROOT = Path(__file__).resolve().parents[1]
CHAMPION = "0c8c16c9be734152c0018aa40e576fe4db9f4621359fafe521465890f9945616"


def _write_json(path: Path, obj: dict) -> Path:
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    return path


def _announcement_contract(tmp_path: Path) -> Path:
    events = []
    with (ROOT / "data/processed/historical_events.csv").open(newline="", encoding="utf-8") as f:
        events = list(csv.DictReader(f))
    ann = tmp_path / "announcements.csv"
    with ann.open("w", newline="", encoding="utf-8") as f:
        fields = ["event_id", "historical_symbol", "event_date", "public_announcement_ts", "timestamp_kind", "source_grade", "source_reference"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for row in events:
            dt = coverage_planner._parse_first_trade(row["first_documented_illicit_trade_ts"])
            public = dt + timedelta(hours=1)
            w.writerow({
                "event_id": row["event_id"], "historical_symbol": row["historical_symbol"],
                "event_date": dt.date().isoformat(), "public_announcement_ts": public.isoformat(timespec="seconds"),
                "timestamp_kind": "first_public_release", "source_grade": "A", "source_reference": "synthetic://step21-test",
            })
    return _write_json(tmp_path / "metadata_contract.json", {
        "schema_version": "1",
        "sources": [{
            "source_id": "all-announcements", "record_kind": "announcement_timestamp", "source_family": "synthetic_fixture",
            "path": str(ann), "enabled": True, "authorized": True, "data_classification": "synthetic_fixture",
            "license_reference": "synthetic-fixture", "delimiter": ",", "encoding": "utf-8",
            "timezone": "America/New_York", "column_map": {},
        }],
    })


def test_current_real_state_is_blocked_and_no_token(tmp_path):
    result = aio.assess_current(root=ROOT, runtime_dir=tmp_path / "runtime", outdir=tmp_path / "out", expected_champion_sha256=CHAMPION)
    assert result["evaluation_release_permitted"] is False
    assert result["release_token_issued"] is False
    assert result["gate_state"]["G7_TEMPORAL_FEATURE_INTEGRITY"] is True
    assert result["gate_state"]["G8_HOLDOUT_ISOLATION"] is True
    assert result["gate_state"]["G9_PROVENANCE"] is True
    assert result["gate_state"]["G10_CHAMPION_IMMUTABILITY"] is True
    assert result["gate_state"]["G1_ANNOUNCEMENT_TIMES"] is False
    assert result["gate_state"]["G2_REAL_MARKET_DATA"] is False


def test_batch_manifest_rejects_credential_like_fields(tmp_path):
    p = _write_json(tmp_path / "batch.json", {
        "schema_version": "1", "metadata": {"source_contract": "x.json"}, "api_key": "do-not-store-secrets-here"
    })
    try:
        aio.load_batch_manifest(p)
    except aio.OrchestratorError as exc:
        assert "credential-like" in str(exc)
    else:
        raise AssertionError("credential-like batch field should have been rejected")


def test_announcement_file_closes_g1_and_is_attributed(tmp_path):
    contract = _announcement_contract(tmp_path)
    batch = _write_json(tmp_path / "batch.json", {
        "schema_version": "1", "batch_id": "ann-only",
        "metadata": {"source_contract": str(contract), "source_ids": ["all-announcements"]},
    })
    result = aio.orchestrate_batch(root=ROOT, batch_manifest=batch, runtime_dir=tmp_path / "runtime",
                                   outdir=tmp_path / "out", expected_champion_sha256=CHAMPION)
    assert result["evaluation_release_permitted"] is False
    assert result["champion_unchanged"] is True
    assert result["file_receipts"][0]["source_id"] == "all-announcements"
    assert "G1_ANNOUNCEMENT_TIMES" in result["file_receipts"][0]["closed_gates"]
    assert result["batch_end_gate_state"]["G1_ANNOUNCEMENT_TIMES"] is True
    assert result["batch_end_gate_state"]["G6_METADATA_QUALITY"] is False
    assert aio.verify_ledger(tmp_path / "runtime/authorized_input_ingestion_ledger.jsonl")["valid"] is True
    rows = list(csv.DictReader((Path(result["gate_map_path"])).open(newline="", encoding="utf-8")))
    assert "G1_ANNOUNCEMENT_TIMES" in rows[0]["closed_gates"]
    assert "G1_ANNOUNCEMENT_TIMES" in rows[0]["potential_gates"]


def test_identical_reimport_is_noop_and_does_not_claim_new_gate_closure(tmp_path):
    contract = _announcement_contract(tmp_path)
    batch = _write_json(tmp_path / "batch.json", {
        "schema_version": "1", "batch_id": "ann-first",
        "metadata": {"source_contract": str(contract), "source_ids": ["all-announcements"]},
    })
    aio.orchestrate_batch(root=ROOT, batch_manifest=batch, runtime_dir=tmp_path / "runtime",
                          outdir=tmp_path / "out", expected_champion_sha256=CHAMPION)
    batch2 = _write_json(tmp_path / "batch2.json", {
        "schema_version": "1", "batch_id": "ann-second",
        "metadata": {"source_contract": str(contract), "source_ids": ["all-announcements"]},
    })
    result = aio.orchestrate_batch(root=ROOT, batch_manifest=batch2, runtime_dir=tmp_path / "runtime",
                                   outdir=tmp_path / "out", expected_champion_sha256=CHAMPION)
    r = result["file_receipts"][0]
    assert r["import_status"] == "NO_OP"
    assert r["closed_gates"] == []
    assert result["batch_start_gate_state"] == result["batch_end_gate_state"]


def test_synthetic_market_file_is_mapped_to_g2_but_cannot_close_it(tmp_path):
    batch = _write_json(tmp_path / "batch.json", {
        "schema_version": "1", "batch_id": "market-one",
        "market": {
            "source_contract": str(ROOT / "config/historical_market_sources.example.json"),
            "source_ids": ["example_taq_trades"],
        },
    })
    result = aio.orchestrate_batch(root=ROOT, batch_manifest=batch, runtime_dir=tmp_path / "runtime",
                                   outdir=tmp_path / "out", expected_champion_sha256=CHAMPION)
    r = result["file_receipts"][0]
    assert r["potential_gates"] == ["G2_REAL_MARKET_DATA"]
    assert "G2_REAL_MARKET_DATA" not in r["closed_gates"]
    assert result["batch_end_gate_state"]["G2_REAL_MARKET_DATA"] is False
    assert result["evaluation_release_token_issued"] is False
    assert result["raw_input_files_copied_to_report_bundle"] is False
