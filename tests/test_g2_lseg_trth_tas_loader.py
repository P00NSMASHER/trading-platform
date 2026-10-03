from __future__ import annotations

import csv
import gzip
import hashlib
from datetime import date
from pathlib import Path

import pytest

import g2_lseg_trth_tas_loader as tas


ALL_COLUMNS = list(dict.fromkeys(tas.RAW_TRADE_COLUMNS + tas.RAW_QUOTE_COLUMNS))


def _write_part(root: Path, name: str, rows: list[dict[str, object]]) -> Path:
    path = root / name
    with gzip.open(path, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ALL_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in ALL_COLUMNS})

    digest = hashlib.md5(path.read_bytes()).hexdigest()
    Path(str(path) + ".md5sum").write_text(
        digest + "  " + path.name + "\n",
        encoding="utf-8",
    )
    return path


def _trade(ric: str, price: float = 10.0) -> dict[str, object]:
    return {
        "#RIC": ric,
        "Date[G]": "27-Apr-2011",
        "Time[G]": "15:22:00.000",
        "GMT Offset": 0,
        "Type": "Trade",
        "Ex/Cntrb.ID": "NAS",
        "Price": price,
        "Volume": 100,
        "Market VWAP": price,
        "Qualifiers": "",
        "Seq. No.": 1,
        "Exch Time": "15:22:00.000",
        "Trd/Qte Date": "27-Apr-2011",
    }


def _quote(ric: str) -> dict[str, object]:
    return {
        "#RIC": ric,
        "Date[G]": "27-Apr-2011",
        "Time[G]": "15:21:59.500",
        "GMT Offset": 0,
        "Type": "Quote",
        "Buyer ID": "",
        "Bid Price": 9.9,
        "Bid Size": 5,
        "Seller ID": "",
        "Ask Price": 10.1,
        "Ask Size": 6,
        "Qualifiers": "R[PRC_QL_CD]",
        "Quote Time": "15:21:59.500",
    }


def test_fixed_position_filename_parser_matches_original_layout():
    name = "ABCD2011-04-27_TAS-Data_part01.gz"
    assert tas.tas_filename_date(name) == date(2011, 4, 27)

    with pytest.raises(ValueError, match="not an original-layout"):
        tas.tas_filename_date("2011-04-27.csv.gz")


def test_discovers_multiple_parts_by_partition_date(tmp_path):
    _write_part(
        tmp_path,
        "ABCD2011-04-27_TAS-Data_part02.gz",
        [_trade("CNMD.O")],
    )
    _write_part(
        tmp_path,
        "ABCD2011-04-27_TAS-Data_part01.gz",
        [_quote("CNMD.O")],
    )
    _write_part(
        tmp_path,
        "ABCD2011-04-28_TAS-Data_part01.gz",
        [_trade("CNMD.O")],
    )
    (tmp_path / "README.txt").write_text("ignore me", encoding="utf-8")

    grouped = tas.discover_tas_parts(tmp_path)
    assert list(grouped) == [date(2011, 4, 27), date(2011, 4, 28)]
    assert [p.name for p in grouped[date(2011, 4, 27)]] == [
        "ABCD2011-04-27_TAS-Data_part01.gz",
        "ABCD2011-04-27_TAS-Data_part02.gz",
    ]


def test_md5_sidecar_is_required_and_verified(tmp_path):
    path = _write_part(
        tmp_path,
        "ABCD2011-04-27_TAS-Data_part01.gz",
        [_trade("CNMD.O")],
    )
    receipt = tas.verify_md5_sidecar(path)
    assert receipt["data_file"] == path.name
    assert receipt["md5"] == hashlib.md5(path.read_bytes()).hexdigest()

    Path(str(path) + ".md5sum").write_text("0" * 32 + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="MD5 mismatch"):
        tas.verify_md5_sidecar(path)


def test_missing_md5_sidecar_fails_closed(tmp_path):
    path = tmp_path / "ABCD2011-04-27_TAS-Data_part01.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("#RIC,Type\nCNMD.O,Trade\n")

    with pytest.raises(FileNotFoundError, match="checksum sidecar"):
        list(tas.iter_tas_rows([path], kind="trade"))


def test_trade_loader_filters_type_and_optional_ric_universe(tmp_path):
    path = _write_part(
        tmp_path,
        "ABCD2011-04-27_TAS-Data_part01.gz",
        [
            _trade("CNMD.O", 10.0),
            _trade("OTHER.O", 20.0),
            _quote("CNMD.O"),
        ],
    )

    rows = list(
        tas.iter_tas_rows(
            [path],
            kind="trade",
            allowed_rics={"CNMD.O"},
            chunksize=1,
        )
    )
    assert len(rows) == 1
    assert rows[0]["#RIC"] == "CNMD.O"
    assert rows[0]["Type"] == "Trade"
    assert rows[0]["Price"] == 10.0


def test_quote_loader_keeps_original_quote_columns(tmp_path):
    path = _write_part(
        tmp_path,
        "ABCD2011-04-27_TAS-Data_part01.gz",
        [_quote("CNMD.O"), _trade("CNMD.O")],
    )

    rows = list(tas.iter_tas_rows([path], kind="quote"))
    assert len(rows) == 1
    row = rows[0]
    assert row["Type"] == "Quote"
    assert row["Bid Price"] == 9.9
    assert row["Ask Price"] == 10.1
    assert row["Quote Time"] == "15:21:59.500"


def test_load_tas_day_returns_non_authoritative_receipt(tmp_path):
    _write_part(
        tmp_path,
        "ABCD2011-04-27_TAS-Data_part01.gz",
        [_trade("CNMD.O"), _quote("CNMD.O")],
    )

    payload = tas.load_tas_day(
        tmp_path,
        date(2011, 4, 27),
        kind="trade",
        allowed_rics={"CNMD.O"},
    )
    assert payload["partition_date"] == "2011-04-27"
    assert payload["part_count"] == 1
    assert payload["row_count"] == 1
    assert payload["rows"][0]["#RIC"] == "CNMD.O"
    assert payload["coverage_claim"] is False


def test_unknown_kind_and_bad_chunksize_fail_closed(tmp_path):
    with pytest.raises(ValueError, match="kind must be"):
        list(tas.iter_tas_rows([], kind="depth"))

    with pytest.raises(ValueError, match="chunksize must be positive"):
        list(tas.iter_tas_rows([], kind="trade", chunksize=0))
