from __future__ import annotations

import csv
from pathlib import Path

import pytest

import g1_announcement_adapter as g1
from metadata_resolver import _load_source_rows, load_contract, resolve_announcements


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _events(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "events.csv",
        "event_id,permno,gvkey,historical_symbol,first_documented_illicit_trade_ts\n"
        "E1,10145,1300,HON,2012-01-26 15:53:00\n"
        "E2,10104,12142,ORCL,2012-09-19 14:00:00\n",
    )


def test_direct_permno_ibes_export_builds_exact_g1_contract(tmp_path: Path):
    events = _events(tmp_path)
    ibes = _write(
        tmp_path / "ibes.csv",
        "PERMNO,ANNDATS_ACT,ANNTIMS_ACT\n"
        "10145,2012-01-27,07:30:00\n"
        "10145,2012-01-27,07:30:00\n"
        "10104,2012-09-20,16:05:00\n",
    )
    out = tmp_path / "out"
    result = g1.build(events_path=events, ibes_path=ibes, output_dir=out, source_reference="TEST-ENTITLEMENT")
    assert result["ready_for_g1"] is True
    assert result["matched_exact_count"] == 2
    rows = list(csv.DictReader((out / "announcement_timestamps.csv").open(newline="", encoding="utf-8")))
    assert rows[0]["timestamp_kind"] == "first_public_release"
    assert rows[0]["source_grade"] == "A"
    assert rows[0]["source_reference"] == "TEST-ENTITLEMENT"
    assert rows[0]["public_announcement_ts"].endswith("-05:00")
    assert rows[1]["public_announcement_ts"].endswith("-04:00")


def test_blank_actual_time_never_becomes_exact(tmp_path: Path):
    events = _events(tmp_path)
    ibes = _write(
        tmp_path / "ibes.csv",
        "PERMNO,ANNDATS_ACT,ANNTIMS_ACT\n"
        "10145,2012-01-27,\n"
        "10104,2012-09-20,16:05:00\n",
    )
    out = tmp_path / "out"
    result = g1.build(events_path=events, ibes_path=ibes, output_dir=out)
    assert result["ready_for_g1"] is False
    assert result["matched_exact_count"] == 1
    assert result["unresolved_count"] == 1


def test_same_release_date_conflict_fails_closed(tmp_path: Path):
    events = _write(
        tmp_path / "events.csv",
        "event_id,permno,gvkey,historical_symbol,first_documented_illicit_trade_ts\n"
        "E1,10145,1300,HON,2012-01-26 15:53:00\n",
    )
    ibes = _write(
        tmp_path / "ibes.csv",
        "PERMNO,ANNDATS_ACT,ANNTIMS_ACT\n"
        "10145,2012-01-27,07:30:00\n"
        "10145,2012-01-27,08:00:00\n",
    )
    out = tmp_path / "out"
    result = g1.build(events_path=events, ibes_path=ibes, output_dir=out)
    assert result["ready_for_g1"] is False
    assert result["ambiguous_count"] == 1
    assert result["matched_exact_count"] == 0


def test_ticker_export_can_use_ibes_permno_link(tmp_path: Path):
    events = _write(
        tmp_path / "events.csv",
        "event_id,permno,gvkey,historical_symbol,first_documented_illicit_trade_ts\n"
        "E1,10145,1300,HON,2012-01-26 15:53:00\n",
    )
    ibes = _write(
        tmp_path / "ibes.csv",
        "TICKER,ANNDATS_ACT,ANNTIMS_ACT\n"
        "HON,2012-01-27,073000\n",
    )
    link = _write(
        tmp_path / "link.csv",
        "TICKER,PERMNO,sdate,edate\n"
        "HON,10145,01JAN2010,31DEC2015\n",
    )
    result = g1.build(events_path=events, ibes_path=ibes, ibes_link_path=link, output_dir=tmp_path / "out")
    assert result["ready_for_g1"] is True


def test_source_hash_pin_rejects_wrong_input(tmp_path: Path):
    events = _events(tmp_path)
    ibes = _write(
        tmp_path / "ibes.csv",
        "PERMNO,ANNDATS_ACT,ANNTIMS_ACT\n"
        "10145,2012-01-27,07:30:00\n"
        "10104,2012-09-20,16:05:00\n",
    )
    with pytest.raises(g1.G1AdapterError, match="SHA-256 mismatch"):
        g1.build(events_path=events, ibes_path=ibes, output_dir=tmp_path / "out", expected_ibes_sha256="0" * 64)


def test_generated_contract_closes_metadata_resolver_g1(tmp_path: Path):
    events = _events(tmp_path)
    ibes = _write(
        tmp_path / "ibes.csv",
        "PERMNO,ANNDATS_ACT,ANNTIMS_ACT\n"
        "10145,2012-01-27,07:30:00\n"
        "10104,2012-09-20,16:05:00\n",
    )
    out = tmp_path / "out"
    result = g1.build(events_path=events, ibes_path=ibes, output_dir=out, source_reference="TEST-ENTITLEMENT")
    assert result["ready_for_g1"] is True

    contracts, _ = load_contract(out / "metadata_source_contract.json")
    loaded = []
    for source in contracts:
        rows, path = _load_source_rows(source, Path("/"))
        loaded.append((source, rows, path))

    event_rows = list(csv.DictReader(events.open(newline="", encoding="utf-8")))
    resolved = resolve_announcements(event_rows, loaded)
    assert len(resolved) == 2
    assert all(x.resolution_status == "resolved_exact_public_timestamp" for x in resolved)
    assert all(x.timestamp_confidence == "A-EXACT" for x in resolved)
