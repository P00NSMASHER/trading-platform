from __future__ import annotations

import csv
import zipfile
from pathlib import Path

import g4_materialize_batch as materialize
import g4_taq_master_shares as taq


def _master_line(*, exchange: str, symbol: str, shares: str) -> str:
    chars = [" "] * 251
    chars[taq.SOURCE_LISTED_EXCHANGE_OFFSET:taq.SOURCE_LISTED_EXCHANGE_OFFSET + 2] = list(
        exchange.ljust(2)[:2]
    )
    chars[taq.SYMBOL_OFFSET:taq.SYMBOL_OFFSET + taq.SYMBOL_SIZE] = list(
        symbol.ljust(taq.SYMBOL_SIZE)[:taq.SYMBOL_SIZE]
    )
    chars[
        taq.SHARES_OUTSTANDING_OFFSET:
        taq.SHARES_OUTSTANDING_OFFSET + taq.SHARES_OUTSTANDING_SIZE
    ] = list(shares.rjust(taq.SHARES_OUTSTANDING_SIZE))
    return "".join(chars)


def _zip_master(path: Path, lines: list[str]) -> None:
    payload = ("HEADER\n" + "\n".join(lines) + "\n").encode("ascii")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(path.stem + ".txt", payload)


def test_fixed_width_parser_uses_documented_nyse_shares_offsets():
    row = taq.parse_master_record(
        _master_line(exchange="00", symbol="WLL", shares="167041054")
    )
    assert row == {
        "historical_symbol": "WLL",
        "shares_outstanding": 167041054,
        "source_listed_exchange": "00",
    }


def test_fixed_width_parser_rejects_non_nyse_shares_field():
    # The historical Daily TAQ specification defines this field as NYSE-only.
    assert (
        taq.parse_master_record(
            _master_line(exchange="07", symbol="CGNX", shares="86544015")
        )
        is None
    )


def test_fixed_width_parser_fails_closed_on_malformed_nyse_share_count():
    line = _master_line(exchange="00", symbol="ACO", shares="32184110")
    chars = list(line)
    chars[taq.SHARES_OUTSTANDING_OFFSET] = "X"
    try:
        taq.parse_master_record("".join(chars))
    except ValueError as exc:
        assert "non-integer" in str(exc)
    else:
        raise AssertionError("expected malformed NYSE shares field to fail closed")


def test_extracts_deterministic_anchor_from_historical_zip(tmp_path: Path):
    master = tmp_path / "EQY_US_ALL_REF_MASTER_20150223.zip"
    _zip_master(
        master,
        [
            _master_line(exchange="00", symbol="WLL", shares="167041054"),
            _master_line(exchange="07", symbol="CGNX", shares="86544015"),
        ],
    )

    rows = taq.extract_anchors(
        [master],
        symbols={"WLL", "CGNX"},
        cik_map={"WLL": "0001255474", "CGNX": "0000851205"},
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["historical_symbol"] == "WLL"
    assert row["cik"] == "0001255474"
    assert row["fact_date"] == "2015-02-23"
    assert row["filed_date"] == "2015-02-23"
    assert row["shares_outstanding"] == "167041054"
    assert row["source_tag"] == "nyse_daily_taq_master:shares_outstanding"
    assert row["source_grade"] == "A"
    assert row["source_reference"].endswith(
        "/EQY_US_ALL_REF_MASTER_2015/EQY_US_ALL_REF_MASTER_201502/"
        "EQY_US_ALL_REF_MASTER_20150223.zip"
    )
    assert "file_sha256=" in row["notes"]


def test_materializer_accepts_prior_master_but_rejects_same_day_lookahead(tmp_path: Path):
    req = tmp_path / "requirements.csv"
    anchors = tmp_path / "anchors.csv"
    out = tmp_path / "out.csv"
    report = tmp_path / "report.json"

    with req.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["historical_symbol", "trade_date", "window_intervals_local"])
        writer.writerow(["WLL", "2015-02-24", "15:24-16:00"])

    prior = {
        "historical_symbol": "WLL",
        "cik": "0001255474",
        "fact_date": "2015-02-23",
        "shares_outstanding": "167041054",
        "filed_date": "2015-02-23",
        "form": "NYSE Daily TAQ Master",
        "accession": "EQY_US_ALL_REF_MASTER_20150223.zip",
        "source_tag": "nyse_daily_taq_master:shares_outstanding",
        "source_reference": "sftp.nyse.com:/prior.zip",
        "source_grade": "A",
        "max_staleness_days": "",
        "staleness_exception_reason": "",
        "notes": "",
    }
    same_day = dict(prior)
    same_day["fact_date"] = "2015-02-24"
    same_day["filed_date"] = "2015-02-24"
    same_day["accession"] = "EQY_US_ALL_REF_MASTER_20150224.zip"

    taq.write_anchors([prior, same_day], anchors)
    result = materialize.build(req, anchors, 0, 1, out, report)

    assert result["resolved_count"] == 1
    row = next(csv.DictReader(out.open(newline="", encoding="utf-8")))
    assert row["status"] == "RESOLVED"
    assert row["fact_date"] == "2015-02-23"
    assert row["accession"] == "EQY_US_ALL_REF_MASTER_20150223.zip"
    assert row["staleness_days"] == "1"


def test_same_day_master_alone_is_rejected_before_intraday_cutoff(tmp_path: Path):
    req = tmp_path / "requirements.csv"
    anchors = tmp_path / "anchors.csv"
    out = tmp_path / "out.csv"
    report = tmp_path / "report.json"

    with req.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["historical_symbol", "trade_date", "window_intervals_local"])
        writer.writerow(["ACO", "2013-03-26", "14:10-15:00"])

    taq.write_anchors(
        [
            {
                "historical_symbol": "ACO",
                "cik": "0000813621",
                "fact_date": "2013-03-26",
                "shares_outstanding": "32184110",
                "filed_date": "2013-03-26",
                "form": "NYSE Daily TAQ Master",
                "accession": "EQY_US_ALL_REF_MASTER_20130326.zip",
                "source_tag": "nyse_daily_taq_master:shares_outstanding",
                "source_reference": "sftp.nyse.com:/same-day.zip",
                "source_grade": "A",
                "max_staleness_days": "",
                "staleness_exception_reason": "",
                "notes": "",
            }
        ],
        anchors,
    )
    result = materialize.build(req, anchors, 0, 1, out, report)

    assert result["resolved_count"] == 0
    row = next(csv.DictReader(out.open(newline="", encoding="utf-8")))
    assert row["status"] == "UNRESOLVED"
