from __future__ import annotations

import csv
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g1_ibes_timestamp_adapter as g1
import metadata_resolver


def _write_events(path: Path) -> Path:
    path.write_text(
        "event_id,historical_symbol,first_documented_illicit_trade_ts\n"
        "E1,ABC,2015-01-01 15:00:00\n"
        "E2,XYZ,2015-02-03 14:30:00\n",
        encoding="utf-8",
    )
    return path


def _write_ibes(path: Path, *, conflict: bool = False) -> Path:
    rows = [
        "TICKER,OFTIC,ANNDATS_ACT,ANNTIMS_ACT,ACTUAL",
        "ABC,ABC,2015-01-02,16:05:00,1.00",
        # Duplicate analyst/detail-history rows with the same actual time are normal and collapse safely.
        "ABC,ABC,2015-01-02,16:05:00,1.00",
        "XYZ,XYZ,2015-02-03,16:00:00,2.00",
    ]
    if conflict:
        rows.append("ABC,ABC,2015-01-02,16:06:00,1.00")
    text = "\n".join(rows) + "\n"
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
            f.write(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def test_adapter_resolves_same_day_and_next_day_without_leaking_raw_rows(tmp_path: Path):
    events = _write_events(tmp_path / "events.csv")
    ibes = _write_ibes(tmp_path / "ibes.csv")
    output = tmp_path / "announcement_timestamps.csv"
    report = tmp_path / "g1_report.json"

    result = g1.adapt_ibes(
        events_path=events,
        ibes_detail_path=ibes,
        output_path=output,
        report_path=report,
        entitlement_reference="TEST-ENTITLEMENT",
    )

    assert result["g1_ready"] is True
    assert result["resolved_exact_count"] == 2
    assert result["unresolved_count"] == 0
    rows = list(csv.DictReader(output.open(newline="", encoding="utf-8")))
    assert rows[0]["event_id"] == "E1"
    assert rows[0]["event_date"] == "2015-01-02"
    assert rows[0]["public_announcement_ts"] == "2015-01-02T21:05:00Z"
    assert rows[0]["timestamp_kind"] == "first_public_release"
    assert rows[0]["source_grade"] == "A"
    assert "ACTUAL" not in output.read_text(encoding="utf-8")
    assert result["raw_licensed_rows_embedded_in_output"] is False


def test_conflicting_vendor_times_fail_closed(tmp_path: Path):
    events = _write_events(tmp_path / "events.csv")
    ibes = _write_ibes(tmp_path / "ibes.csv", conflict=True)
    output = tmp_path / "announcement_timestamps.csv"
    report = tmp_path / "g1_report.json"

    result = g1.adapt_ibes(
        events_path=events,
        ibes_detail_path=ibes,
        output_path=output,
        report_path=report,
        entitlement_reference="TEST-ENTITLEMENT",
    )

    assert result["g1_ready"] is False
    assert result["resolved_exact_count"] == 1
    unresolved = {x["event_id"]: x for x in result["unresolved"]}
    assert unresolved["E1"]["reason"] == "ambiguous_multiple_announcement_times"


def test_candidate_before_illicit_trade_is_not_accepted(tmp_path: Path):
    events = _write_events(tmp_path / "events.csv")
    ibes = tmp_path / "ibes.csv"
    ibes.write_text(
        "TICKER,OFTIC,ANNDATS_ACT,ANNTIMS_ACT\n"
        "ABC,ABC,2015-01-01,14:00:00\n"
        "XYZ,XYZ,2015-02-03,16:00:00\n",
        encoding="utf-8",
    )
    result = g1.adapt_ibes(
        events_path=events,
        ibes_detail_path=ibes,
        output_path=tmp_path / "out.csv",
        report_path=tmp_path / "report.json",
        entitlement_reference="TEST-ENTITLEMENT",
    )
    unresolved = {x["event_id"]: x for x in result["unresolved"]}
    assert unresolved["E1"]["reason"] == "missing_candidate"


def test_entitlement_reference_is_mandatory(tmp_path: Path):
    events = _write_events(tmp_path / "events.csv")
    ibes = _write_ibes(tmp_path / "ibes.csv")
    with pytest.raises(g1.G1AdapterError, match="entitlement_reference"):
        g1.adapt_ibes(
            events_path=events,
            ibes_detail_path=ibes,
            output_path=tmp_path / "out.csv",
            report_path=tmp_path / "report.json",
            entitlement_reference="",
        )


def test_gzip_detail_history_is_supported(tmp_path: Path):
    events = _write_events(tmp_path / "events.csv")
    ibes = _write_ibes(tmp_path / "ibes.csv.gz")
    result = g1.adapt_ibes(
        events_path=events,
        ibes_detail_path=ibes,
        output_path=tmp_path / "out.csv",
        report_path=tmp_path / "report.json",
        entitlement_reference="TEST-ENTITLEMENT",
    )
    assert result["g1_ready"] is True


def test_adapter_output_closes_real_metadata_resolver_g1_semantics(tmp_path: Path):
    events = _write_events(tmp_path / "events.csv")
    ibes = _write_ibes(tmp_path / "ibes.csv")
    normalized = tmp_path / "announcement_timestamps.csv"
    g1.adapt_ibes(
        events_path=events,
        ibes_detail_path=ibes,
        output_path=normalized,
        report_path=tmp_path / "g1_report.json",
        entitlement_reference="TEST-ENTITLEMENT",
    )

    contract = tmp_path / "metadata_sources.json"
    contract.write_text(json.dumps({
        "schema_version": "1",
        "sources": [{
            "source_id": "licensed-ibes-announcements",
            "record_kind": "announcement_timestamp",
            "source_family": "ibes_announcement",
            "path": str(normalized),
            "enabled": True,
            "authorized": True,
            "data_classification": "authorized_reference_data",
            "license_reference": "TEST-ENTITLEMENT",
            "delimiter": ",",
            "encoding": "utf-8",
            "timezone": "America/New_York",
            "column_map": {},
        }],
    }), encoding="utf-8")
    symbol_dates = tmp_path / "symbol_dates.csv"
    symbol_dates.write_text("historical_symbol,trade_date\n", encoding="utf-8")

    summary = metadata_resolver.build(events, symbol_dates, contract, tmp_path / "resolved")
    assert summary["announcement_exact_resolved"] == 2
    assert summary["announcement_unresolved"] == 0
    assert summary["ready_g1_announcement_times"] is True
    assert summary["ready_g3_primary_listing_history"] is False
    assert summary["ready_g4_shares_outstanding"] is True  # zero required rows in this focused fixture
    assert summary["ready_g5_matched_control_universe"] is False
