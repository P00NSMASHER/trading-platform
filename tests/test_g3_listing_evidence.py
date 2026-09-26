from __future__ import annotations

import csv
from pathlib import Path

import g3_listing_evidence as g3

ROOT = Path(__file__).resolve().parents[1]


def test_strict_classifier_prioritizes_nyse_mkt_over_nyse():
    found, _ = g3.classify_exchange("Gold Resource Corporation (NYSE MKT: GORO)", "GORO")
    assert found == {"XASE"}


def test_strict_classifier_maps_nasdaq_and_nyse():
    assert g3.classify_exchange("Example Corp (NASDAQ Global Select: ABC)", "ABC")[0] == {"XNAS"}
    assert g3.classify_exchange("Example Corp (NYSE: XYZ)", "XYZ")[0] == {"XNYS"}


def test_classifier_requires_symbol_binding():
    found, _ = g3.classify_exchange("NYSE: OTHER; Example Corp ABC", "ABC")
    assert found == set()


def test_g3_supplement_is_event_bound_and_canonical():
    p = ROOT / "data/public/metadata/g3_listing_supplement.csv"
    rows = list(csv.DictReader(p.open(newline="", encoding="utf-8")))
    assert len(rows) == 28
    assert len({r["event_id"] for r in rows}) == 28
    assert {r["primary_exchange"] for r in rows} <= {"XNYS", "XNAS", "XASE"}
    assert all(r["source_reference"] for r in rows)


def test_generated_g3_evidence_is_complete_when_present():
    p = ROOT / "data/public/metadata/g3_primary_listing_history.csv"
    if not p.exists():
        return
    rows = list(csv.DictReader(p.open(newline="", encoding="utf-8")))
    assert len(rows) == 174
    assert len({r["event_id"] for r in rows}) == 174
    counts = {}
    for r in rows:
        counts[r["primary_exchange"]] = counts.get(r["primary_exchange"], 0) + 1
    assert counts == {"XASE": 2, "XNAS": 80, "XNYS": 92}
    assert all(r["source_reference"] for r in rows)
