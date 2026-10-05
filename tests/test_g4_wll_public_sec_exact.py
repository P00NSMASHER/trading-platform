"""Regression checks for the public post-Kodiak WLL share-count repair."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import metadata_resolver as resolver

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/public/metadata/g4_shares_wll_20150204_25.csv"
CONTRACT = ROOT / "config/metadata_sources.public_progress.json"
SOURCE_ID = "public-sec-shares-wll-20150105"
EXPECTED_DATES = [
    "2015-02-04", "2015-02-05", "2015-02-06", "2015-02-09", "2015-02-10",
    "2015-02-11", "2015-02-12", "2015-02-13", "2015-02-17", "2015-02-18",
    "2015-02-19", "2015-02-20", "2015-02-23", "2015-02-24", "2015-02-25",
]


def _rows():
    with SOURCE.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _source():
    sources, _ = resolver.load_contract(CONTRACT)
    matches = [source for source in sources if source.source_id == SOURCE_ID]
    assert len(matches) == 1
    return matches[0]


def _requirements():
    return [
        {"historical_symbol": "WLL", "trade_date": day,
         "window_intervals_local": "15:24-16:00"}
        for day in EXPECTED_DATES
    ]


def test_wll_source_contains_exact_explicit_post_acquisition_count():
    rows = _rows()
    assert [row["target_trade_date"] for row in rows] == EXPECTED_DATES
    assert len(rows) == 15
    assert {row["historical_symbol"] for row in rows} == {"WLL"}
    assert {row["shares_outstanding"] for row in rows} == {"166889152"}
    assert {row["fact_date"] for row in rows} == {"2014-12-31"}
    assert {row["available_at"] for row in rows} == {"2015-01-05T16:02:59-05:00"}
    assert all("000119312515001735/d844890d8k.htm" in row["source_reference"] for row in rows)


def test_production_resolver_accepts_all_fifteen_wll_rows_without_exceptions():
    result = resolver.resolve_shares(_requirements(), [(_source(), _rows(), SOURCE)])
    assert len(result) == 15
    assert all(row.resolution_status == "resolved" for row in result)
    assert all(row.shares_outstanding == "166889152" for row in result)
    assert all(row.source_id == SOURCE_ID for row in result)
    assert all(0 <= int(row.staleness_days) <= 130 for row in result)
    assert all(datetime.fromisoformat(row.available_at) <
               datetime.fromisoformat(row.trade_date + "T15:24:00-05:00") for row in result)


def test_wll_future_available_mutation_remains_rejected():
    rows = [dict(row, available_at="2015-02-26T00:00:00-05:00") for row in _rows()]
    result = resolver.resolve_shares(_requirements(), [(_source(), rows, SOURCE)])
    assert all(row.resolution_status == "unresolved" for row in result)
    assert all(not row.shares_outstanding for row in result)


def test_wll_old_fact_mutation_cannot_override_130_day_limit():
    rows = [dict(row, fact_date="2014-01-01") for row in _rows()]
    result = resolver.resolve_shares(_requirements(), [(_source(), rows, SOURCE)])
    assert all(row.resolution_status == "unresolved" for row in result)


def test_only_wll_is_removed_from_reviewed_exclusions():
    payload = json.loads((ROOT / "data/processed/authorized_input_real/g4_final_blockers.json").read_text())
    assert payload["unresolved_by_symbol"] == {"ACO": 10, "CGNX": 5}
    assert payload["g4_state"]["exact_resolved"] == 3813
    assert payload["g4_state"]["reviewed_excluded"] == 15
    assert all(row["historical_symbol"] != "WLL" for row in payload["blockers"])
