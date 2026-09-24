from __future__ import annotations

import json
from pathlib import Path

import pytest

from metadata_population import PopulationError, populate_batch, validate_source_file, verify_ledger

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data/examples/metadata/events.csv"
SYMBOL_DATES = ROOT / "data/examples/metadata/symbol_dates.csv"
DEMO = ROOT / "config/metadata_sources.demo.json"


def test_population_batch_closes_demo_gates(tmp_path):
    res = populate_batch(events=EVENTS, symbol_dates=SYMBOL_DATES, source_contract=DEMO,
                         runtime_dir=tmp_path/"runtime", outdir=tmp_path/"out", batch_id="b1")
    s = res["current_readiness"]
    assert s["ready_g1_announcement_times"]
    assert s["ready_g3_primary_listing_history"]
    assert s["ready_g4_shares_outstanding"]
    assert s["ready_g5_matched_control_universe"]
    assert res["ledger"]["valid"]


def test_idempotent_reimport_is_noop(tmp_path):
    kwargs=dict(events=EVENTS, symbol_dates=SYMBOL_DATES, source_contract=DEMO,
                runtime_dir=tmp_path/"runtime", outdir=tmp_path/"out")
    populate_batch(**kwargs, batch_id="b1")
    ledger = tmp_path/"runtime/metadata_population_ledger.jsonl"
    before=ledger.read_text()
    res=populate_batch(**kwargs, batch_id="b2")
    assert res["status"] == "NO_OP"
    assert ledger.read_text() == before


def test_partial_batches_report_delta(tmp_path):
    kwargs=dict(events=EVENTS, symbol_dates=SYMBOL_DATES, source_contract=DEMO,
                runtime_dir=tmp_path/"runtime", outdir=tmp_path/"out")
    r1=populate_batch(**kwargs, source_ids=["demo-announcement"], batch_id="ann")
    assert r1["current_readiness"]["ready_g1_announcement_times"]
    assert not r1["current_readiness"]["ready_g3_primary_listing_history"]
    assert r1["last_coverage_delta"]["numeric_progress"]["announcement_exact_resolved"] > 0
    r2=populate_batch(**kwargs, source_ids=["demo-taq-master"], batch_id="master")
    assert r2["current_readiness"]["ready_g3_primary_listing_history"]
    assert r2["current_readiness"]["ready_g4_shares_outstanding"]
    assert r2["last_coverage_delta"]["numeric_progress"]["event_exchange_resolved"] > 0


def test_ledger_tamper_detected(tmp_path):
    populate_batch(events=EVENTS, symbol_dates=SYMBOL_DATES, source_contract=DEMO,
                   runtime_dir=tmp_path/"runtime", outdir=tmp_path/"out", source_ids=["demo-announcement"], batch_id="b1")
    ledger=tmp_path/"runtime/metadata_population_ledger.jsonl"
    obj=json.loads(ledger.read_text().strip())
    obj["batch_id"]="evil"
    ledger.write_text(json.dumps(obj)+"\n")
    assert not verify_ledger(ledger)["valid"]


def test_rejects_missing_license_reference_for_authorized_source(tmp_path):
    raw=json.loads(DEMO.read_text())
    raw["sources"][0]["data_classification"]="authorized_reference_data"
    raw["sources"][0]["license_reference"]=""
    p=tmp_path/"contract.json"; p.write_text(json.dumps(raw))
    # paths in copied contract are resolved relative to tmp root and would fail later; validation must reject license first.
    with pytest.raises(PopulationError, match="license_reference"):
        validate_source_file(p, raw["sources"][0])


def test_source_selection_unknown_id_rejected(tmp_path):
    with pytest.raises(PopulationError, match="not found"):
        populate_batch(events=EVENTS, symbol_dates=SYMBOL_DATES, source_contract=DEMO,
                       runtime_dir=tmp_path/"runtime", outdir=tmp_path/"out", source_ids=["nope"], batch_id="x")


def test_batch_reports_contain_no_trading_outputs(tmp_path):
    res=populate_batch(events=EVENTS, symbol_dates=SYMBOL_DATES, source_contract=DEMO,
                       runtime_dir=tmp_path/"runtime", outdir=tmp_path/"out", batch_id="b1")
    txt=(Path(res["batch_dir"])/"batch_receipt.json").read_text()
    for forbidden in ["expected_return", "target_price", "position_size", "execution_instruction"]:
        # Forbidden labels may appear only in the explicit prohibited_outputs policy list.
        assert txt.count(forbidden) <= 1
