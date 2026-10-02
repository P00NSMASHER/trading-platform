from __future__ import annotations

import csv
import json
from pathlib import Path

import g2_cheap_route_partitions as partitions


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/processed/g2_vendor_requests/cheap_route_partitions"


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_exact_cheap_route_partition_accounting():
    generated, summary = partitions.build_partitions(
        partitions._read_csv(ROOT / partitions.DEFAULT_EQUITY_REQUIREMENTS),
        partitions._read_csv(ROOT / partitions.DEFAULT_OPTION_REQUIREMENTS),
        partitions._read_csv(ROOT / partitions.DEFAULT_LISTINGS),
    )

    assert summary["accounting"] == {
        "equity_trade_required_pairs": 3828,
        "equity_quote_required_pairs": 3828,
        "option_trade_required_pairs": 3828,
        "option_quote_required_pairs": 3828,
        "thetadata_equity_pairs_per_record_kind": 1430,
        "residual_equity_pairs_per_record_kind": 2398,
        "thetadata_option_pairs_per_record_kind": 3014,
        "lseg_option_residual_pairs_per_record_kind": 814,
    }

    assert summary["partitions"]["thetadata_equity.csv"] == {
        "equity_quote": {
            "source_date_rows": 230,
            "symbol_date_pairs": 1430,
            "unique_historical_symbols": 55,
        },
        "equity_trade": {
            "source_date_rows": 230,
            "symbol_date_pairs": 1430,
            "unique_historical_symbols": 55,
        },
    }
    assert summary["partitions"]["residual_equity.csv"] == {
        "equity_quote": {
            "source_date_rows": 380,
            "symbol_date_pairs": 2398,
            "unique_historical_symbols": 92,
        },
        "equity_trade": {
            "source_date_rows": 380,
            "symbol_date_pairs": 2398,
            "unique_historical_symbols": 92,
        },
    }
    assert summary["partitions"]["thetadata_options.csv"] == {
        "option_quote": {
            "source_date_rows": 291,
            "symbol_date_pairs": 3014,
            "unique_historical_symbols": 115,
        },
        "option_trade": {
            "source_date_rows": 291,
            "symbol_date_pairs": 3014,
            "unique_historical_symbols": 115,
        },
    }
    assert summary["partitions"]["lseg_option_residual.csv"] == {
        "option_quote": {
            "source_date_rows": 123,
            "symbol_date_pairs": 814,
            "unique_historical_symbols": 35,
        },
        "option_trade": {
            "source_date_rows": 123,
            "symbol_date_pairs": 814,
            "unique_historical_symbols": 35,
        },
    }

    # Pair conservation is the procurement safety invariant: partitioning can
    # shrink vendor scopes but may not drop or duplicate frozen requirements.
    for kind in ("equity_trade", "equity_quote"):
        theta = sum(
            int(row["symbol_date_pair_count"])
            for row in generated["thetadata_equity.csv"]
            if row["record_kind"] == kind
        )
        residual = sum(
            int(row["symbol_date_pair_count"])
            for row in generated["residual_equity.csv"]
            if row["record_kind"] == kind
        )
        assert theta + residual == 3828

    for kind in ("option_trade", "option_quote"):
        theta = sum(
            int(row["symbol_date_pair_count"])
            for row in generated["thetadata_options.csv"]
            if row["record_kind"] == kind
        )
        residual = sum(
            int(row["symbol_date_pair_count"])
            for row in generated["lseg_option_residual.csv"]
            if row["record_kind"] == kind
        )
        assert theta + residual == 3828


def test_committed_cheap_route_partitions_match_generator():
    generated, summary = partitions.build_partitions(
        partitions._read_csv(ROOT / partitions.DEFAULT_EQUITY_REQUIREMENTS),
        partitions._read_csv(ROOT / partitions.DEFAULT_OPTION_REQUIREMENTS),
        partitions._read_csv(ROOT / partitions.DEFAULT_LISTINGS),
    )

    for name, expected in generated.items():
        assert _read(OUT / name) == expected

    assert json.loads((OUT / "summary.json").read_text(encoding="utf-8")) == summary


def test_thetadata_equity_partition_requires_xnas_and_history_floor():
    generated, _ = partitions.build_partitions(
        partitions._read_csv(ROOT / partitions.DEFAULT_EQUITY_REQUIREMENTS),
        partitions._read_csv(ROOT / partitions.DEFAULT_OPTION_REQUIREMENTS),
        partitions._read_csv(ROOT / partitions.DEFAULT_LISTINGS),
    )
    listings = partitions._listing_map(
        partitions._read_csv(ROOT / partitions.DEFAULT_LISTINGS)
    )

    for row in generated["thetadata_equity.csv"]:
        assert row["trade_date"] >= partitions.THETADATA_HISTORY_START
        assert all(
            listings[symbol] == "XNAS"
            for symbol in row["historical_symbols"].split(";")
            if symbol
        )
