from __future__ import annotations

import csv
import json
from pathlib import Path

from metadata_quality import build
from metadata_resolver import build as resolve
from metadata_population import populate_batch

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data/examples/metadata/events.csv"
SYMBOL_DATES = ROOT / "data/examples/metadata/symbol_dates.csv"
DEMO = ROOT / "config/metadata_sources.demo.json"


def _run(contract: Path, tmp_path: Path):
    rdir = tmp_path / "resolver"
    resolve(EVENTS, SYMBOL_DATES, contract, rdir)
    return build(events_path=EVENTS, symbol_dates_path=SYMBOL_DATES, contract_path=contract,
                 resolver_dir=rdir, outdir=tmp_path / "quality")


def _write_contract(tmp_path: Path, sources: list[dict]) -> Path:
    p = tmp_path / "config" / "contract.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema_version":"1","sources":sources}, indent=2), encoding="utf-8")
    return p


def _source(source_id: str, kind: str, family: str, path: Path, classification="synthetic_fixture", **extra):
    d = {
        "source_id": source_id, "record_kind": kind, "source_family": family,
        "path": str(path.resolve()), "enabled": True, "authorized": True,
        "data_classification": classification, "license_reference": "fixture-or-entitlement",
        "delimiter": ",", "encoding": "utf-8", "timezone": "America/New_York", "column_map": {},
    }
    d.update(extra)
    return d


def test_clean_demo_quality_clear_but_synthetic_only(tmp_path):
    s = _run(DEMO, tmp_path)
    assert s["quality_gate_clear"] is True
    assert s["only_synthetic_sources"] is True
    assert s["quality_cleared_for_non_synthetic_model_evaluation"] is False
    assert s["blocking_issue_count"] == 0


def test_authorized_non_synthetic_clean_sources_clear_real_gate(tmp_path):
    base = json.loads(DEMO.read_text())
    for src in base["sources"]:
        src["path"] = str((ROOT / src["path"]).resolve())
        src["data_classification"] = "authorized_reference_data"
        src["license_reference"] = "TEST-ENTITLEMENT"
        if src["record_kind"] == "announcement_timestamp":
            src["source_family"] = "official_newswire_archive"
        elif src["record_kind"] == "security_master":
            src["source_family"] = "nyse_daily_taq_master"
        else:
            src["source_family"] = "generic_authorized_reference_data"
    c = _write_contract(tmp_path, base["sources"])
    s = _run(c, tmp_path)
    assert s["quality_gate_clear"] is True
    assert s["only_synthetic_sources"] is False
    assert s["quality_cleared_for_non_synthetic_model_evaluation"] is True


def test_conflicting_exact_announcements_quarantine_event(tmp_path):
    conflict = tmp_path / "ann2.csv"
    conflict.write_text(
        "event_id,historical_symbol,event_date,public_announcement_ts,timestamp_kind,source_grade,source_reference\n"
        "E1,TEST,2015-02-17,2015-02-17T16:35:00-05:00,first_public_release,A,synthetic://conflict\n",
        encoding="utf-8")
    base = json.loads(DEMO.read_text())
    sources=[]
    for src in base["sources"]:
        src=dict(src); src["path"] = str((ROOT / src["path"]).resolve()); sources.append(src)
    sources.append(_source("ann-conflict","announcement_timestamp","synthetic_fixture",conflict))
    c=_write_contract(tmp_path,sources)
    s=_run(c,tmp_path)
    assert s["quarantined_announcement_events"] == 1
    assert s["quality_gate_clear"] is False
    issues=(tmp_path/"quality/metadata_quality_issues.csv").read_text()
    assert "ANN_EXACT_CONFLICT" in issues


def test_overlapping_exchange_conflict_quarantines_event(tmp_path):
    conflict=tmp_path/"master2.csv"
    conflict.write_text("symbol,trade_date,listed_exchange,shares_outstanding_millions\nTEST,2015-02-17,N,10\n",encoding="utf-8")
    base=json.loads(DEMO.read_text()); sources=[]
    for src in base["sources"]:
        src=dict(src); src["path"]=str((ROOT/src["path"]).resolve()); sources.append(src)
    sources.append(_source("master-conflict","security_master","synthetic_fixture",conflict))
    c=_write_contract(tmp_path,sources); s=_run(c,tmp_path)
    assert s["quarantined_exchange_events"] == 1
    assert "EXCHANGE_OVERLAP_CONFLICT" in (tmp_path/"quality/metadata_quality_issues.csv").read_text()


def test_same_date_shares_conflict_quarantines_symbol_date(tmp_path):
    conflict=tmp_path/"shares2.csv"
    conflict.write_text("symbol,trade_date,listed_exchange,shares_outstanding_millions\nTEST,2015-02-17,Q,15\n",encoding="utf-8")
    base=json.loads(DEMO.read_text()); sources=[]
    for src in base["sources"]:
        src=dict(src); src["path"]=str((ROOT/src["path"]).resolve()); sources.append(src)
    sources.append(_source("shares-conflict","security_master","synthetic_fixture",conflict))
    c=_write_contract(tmp_path,sources); s=_run(c,tmp_path)
    assert s["quarantined_share_symbol_dates"] >= 1
    assert "SHARES_SAME_DATE_CONFLICT" in (tmp_path/"quality/metadata_quality_issues.csv").read_text()


def test_conflicting_control_duplicate_quarantines_date(tmp_path):
    conflict=tmp_path/"controls2.csv"
    rows=list(csv.DictReader((ROOT/"data/examples/metadata/control_universe.csv").open()))
    rows[0]["market_cap"]="2000000000"
    with conflict.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerow(rows[0])
    base=json.loads(DEMO.read_text()); sources=[]
    for src in base["sources"]:
        src=dict(src); src["path"]=str((ROOT/src["path"]).resolve()); sources.append(src)
    sources.append(_source("controls-conflict","control_universe","synthetic_fixture",conflict))
    c=_write_contract(tmp_path,sources); s=_run(c,tmp_path)
    assert s["quarantined_control_dates"] == 1
    assert "CONTROL_DUPLICATE_CONFLICT" in (tmp_path/"quality/metadata_quality_issues.csv").read_text()


def test_quality_outputs_include_quarantine_and_gate(tmp_path):
    _run(DEMO,tmp_path)
    assert (tmp_path/"quality/metadata_quality_summary.json").exists()
    assert (tmp_path/"quality/metadata_domain_quality.csv").exists()
    assert (tmp_path/"quality/metadata_quality_gate.csv").exists()
    assert (tmp_path/"quality/metadata_quarantine.csv").exists()


def test_population_integrates_quality_gate(tmp_path):
    res=populate_batch(events=EVENTS,symbol_dates=SYMBOL_DATES,source_contract=DEMO,
                       runtime_dir=tmp_path/"runtime",outdir=tmp_path/"out",batch_id="q1")
    assert res["current_quality"]["quality_gate_clear"] is True
    assert res["evaluation_release_gate"] is False  # synthetic-only can never unlock real evaluation
    assert "quality_cleared_for_non_synthetic_model_evaluation" in res["last_coverage_delta"]["gate_transitions"]


def test_real_empty_contract_is_blocked_not_quality_promoted(tmp_path):
    rdir=tmp_path/"real-resolver"
    events=ROOT/"data/processed/historical_events.csv"
    symbol_dates=ROOT/"data/processed/coverage_plan_real/symbol_date_requirements.csv"
    contract=ROOT/"config/metadata_sources.example.json"
    resolve(events,symbol_dates,contract,rdir)
    s=build(events_path=events,symbol_dates_path=symbol_dates,contract_path=contract,
            resolver_dir=rdir,outdir=tmp_path/"real-quality")
    assert s["coverage_ready_before_quality"] is False
    assert s["quality_cleared_for_non_synthetic_model_evaluation"] is False
    assert s["status"] == "BLOCKED"
