from pathlib import Path

import g2_combined_equity_cheap_route as plan


ROOT = Path(__file__).resolve().parents[1]
RESIDUAL = ROOT / "data/processed/g2_vendor_requests/cheap_route_partitions/residual_equity.csv"


def test_combined_equity_cheap_route_preserves_frozen_pairs():
    outputs, summary = plan.build(plan._read(RESIDUAL))

    assert summary["accounting_per_record_kind"] == {
        "required_pairs": 3828,
        "thetadata_pairs": 1430,
        "firstrate_additional_pairs": 814,
        "combined_cheap_route_pairs": 2244,
        "tickdata_residual_pairs": 1584,
    }
    assert summary["first_rate"]["additional_residual_symbols"] == 31
    assert summary["first_rate"]["pairs_per_record_kind"] == {
        "equity_trade": 814,
        "equity_quote": 814,
    }
    assert summary["first_rate"]["source_date_rows_touched"] == {
        "equity_trade": 265,
        "equity_quote": 265,
    }
    assert summary["first_rate"]["fully_covered_residual_dates"] == {
        "equity_trade": 36,
        "equity_quote": 36,
    }
    assert summary["tickdata_residual"]["pairs_per_record_kind"] == {
        "equity_trade": 1584,
        "equity_quote": 1584,
    }
    assert summary["tickdata_residual"]["unique_symbols"] == 61
    assert summary["tickdata_residual"]["unique_symbol_years"] == 82
    assert summary["tickdata_residual"]["market_dates"] == 344

    first_rate = outputs["firstrate_equity_additional.csv"]
    tickdata = outputs["tickdata_equity_residual.csv"]
    assert sum(r["record_kind"] == "equity_trade" for r in first_rate) == 265
    assert sum(r["record_kind"] == "equity_quote" for r in first_rate) == 265
    assert sum(r["record_kind"] == "equity_trade" for r in tickdata) == 344
    assert sum(r["record_kind"] == "equity_quote" for r in tickdata) == 344


def test_first_rate_residual_matches_are_disjoint_from_tickdata_residual():
    outputs, _ = plan.build(plan._read(RESIDUAL))
    first = {
        (row["record_kind"], row["trade_date"], symbol)
        for row in outputs["firstrate_equity_additional.csv"]
        for symbol in row["historical_symbols"].split(";")
        if symbol
    }
    tick = {
        (row["record_kind"], row["trade_date"], symbol)
        for row in outputs["tickdata_equity_residual.csv"]
        for symbol in row["historical_symbols"].split(";")
        if symbol
    }
    assert first.isdisjoint(tick)


def test_committed_combined_equity_outputs_match_generator():
    import csv
    import json

    outputs, summary = plan.build(plan._read(RESIDUAL))
    committed = ROOT / "data/processed/g2_vendor_requests/combined_equity_cheap_route"

    for filename, expected in outputs.items():
        with (committed / filename).open(newline="", encoding="utf-8") as handle:
            actual = list(csv.DictReader(handle))
        assert actual == expected

    assert json.loads((committed / "summary.json").read_text(encoding="utf-8")) == summary
