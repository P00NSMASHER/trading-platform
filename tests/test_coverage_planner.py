from pathlib import Path
import csv
import json
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coverage_planner import (
    build,
    build_event_plans,
    build_symbol_date_requirements,
    audit_contract,
)


def write_events(tmp_path, rows):
    p = tmp_path / "events.csv"
    fields = ["event_id", "permno", "gvkey", "historical_symbol", "first_documented_illicit_trade_ts", "public_announcement_ts", "research_use_only"]
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    return p


def event(ts="2015-02-17 14:19:00", symbol="TEST", event_id="E1"):
    return {"event_id": event_id, "permno": "1", "gvkey": "2", "historical_symbol": symbol,
            "first_documented_illicit_trade_ts": ts, "public_announcement_ts": "", "research_use_only": "1"}


def test_event_plan_uses_21_eligible_prior_sessions(tmp_path):
    p = write_events(tmp_path, [event()])
    plans, meta = build_event_plans(p)
    x = plans[0]
    assert x.baseline_required_sessions == 21
    assert len(x.baseline_dates.split(";")) == 21
    assert x.event_window_start_local.endswith("13:49:00-05:00")
    assert x.event_window_end_local.endswith("14:49:00-05:00")
    assert meta["calendar"] == "XNYS"


def test_afternoon_baseline_skips_early_close(tmp_path):
    # 2015-11-30 follows the 2015-11-27 early close. An afternoon same-minute
    # baseline cannot use the shortened Black Friday session.
    p = write_events(tmp_path, [event(ts="2015-11-30 15:30:00")])
    plans, _ = build_event_plans(p)
    dates = plans[0].baseline_dates.split(";")
    assert "2015-11-27" not in dates
    assert plans[0].baseline_scan_sessions > 21


def test_window_clips_at_regular_close_and_marks_posthoc_gap(tmp_path):
    p = write_events(tmp_path, [event(ts="2015-02-17 15:59:00")])
    plans, _ = build_event_plans(p)
    x = plans[0]
    assert x.event_window_end_local.endswith("16:00:00-05:00")
    assert x.posthoc_5m_incomplete_panel_minutes > 0


def test_symbol_date_requirements_include_event_and_baselines(tmp_path):
    p = write_events(tmp_path, [event()])
    plans, _ = build_event_plans(p)
    req = build_symbol_date_requirements(plans)
    assert len(req) == 22
    assert sum("event" in r.roles for r in req) == 1
    assert sum("baseline" in r.roles for r in req) == 21
    assert all(r.require_equity_trades == 1 for r in req)


def test_rejects_non_research_event(tmp_path):
    x = event(); x["research_use_only"] = "0"
    p = write_events(tmp_path, [x])
    with pytest.raises(ValueError, match="not research_use_only"):
        build_event_plans(p)


def test_contract_audit_does_not_count_synthetic_as_real(tmp_path):
    contract = tmp_path / "contract.json"
    data = tmp_path / "data.csv"; data.write_text("x\n1\n")
    contract.write_text(json.dumps({"schema_version":"1", "sources":[{
        "source_id":"s", "source_family":"nyse_daily_taq", "record_kind":"equity_trade",
        "path":str(data), "authorized":True, "data_classification":"synthetic_fixture",
        "license_reference":"", "trade_date":"2015-02-17"
    }]}), encoding="utf-8")
    class R:
        source_family="nyse_daily_taq"; record_kind="equity_trade"; trade_date="2015-02-17"; requirement="required_core"
    report = audit_contract(contract, [R()])
    assert report["real_authorized_required_rows_covered"] == 0
    assert report["synthetic_rows_matching_required_keys"] == 1
    assert report["ready_for_real_backfill"] is False


def test_full_build_real_corpus_counts(tmp_path):
    out = tmp_path / "out"
    report = build(ROOT / "data/processed/historical_events.csv", out,
                   contract_path=ROOT / "config/historical_market_sources.example.json")
    assert report["event_count"] == 174
    assert report["unique_symbols"] == 146
    assert report["unique_event_dates"] == 72
    assert report["unique_market_dates_event_plus_baseline"] >= 400
    assert report["unique_symbol_date_pairs"] >= 3800
    assert report["missing_exact_announcement_timestamps"] == 174
    assert report["ready_for_non_synthetic_champion_challenger_comparison"] is False
    assert (out / "event_coverage_plan.csv").exists()
    assert (out / "source_date_requirements.csv").exists()
