import csv
import gzip
from pathlib import Path

import g2_lseg_delivery_normalizer as delivery
import licensed_data_intake as intake


RAW_FIELDS = [
    "#RIC",
    "Date-Time",
    "GMT Offset",
    "Type",
    "Ex/Cntrb.ID",
    "Price",
    "Volume",
    "Bid Price",
    "Bid Size",
    "Ask Price",
    "Ask Size",
    "Qualifiers",
    "Seq. No.",
    "Exch Time",
]


def _write_raw(path: Path, rows: list[dict[str, str]], *, gz: bool = False) -> None:
    opener = gzip.open if gz else open
    kwargs = {"mode": "wt", "encoding": "utf-8", "newline": ""} if gz else {
        "mode": "w",
        "encoding": "utf-8",
        "newline": "",
    }
    with opener(path, **kwargs) as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_equity_delivery_normalizes_to_existing_intake_contract(tmp_path):
    raw = tmp_path / "raw_equity.csv"
    _write_raw(
        raw,
        [
            {
                "#RIC": "JNPR.K",
                "Date-Time": "2011-03-21T10:00:00.000000-04:00",
                "Type": "Trade",
                "Ex/Cntrb.ID": "Q",
                "Price": "40.00",
                "Volume": "100",
            },
            {
                "#RIC": "JNPR.K",
                "Date-Time": "2011-03-21T10:00:01.000000-04:00",
                "Type": "Quote",
                "Bid Price": "39.90",
                "Bid Size": "10",
                "Ask Price": "40.10",
                "Ask Size": "12",
            },
        ],
    )

    output = tmp_path / "canonical"
    summary = delivery.normalize_delivery(
        raw,
        lane="equity",
        trade_date="2011-03-21",
        output_dir=output,
    )

    assert summary["raw_rows"] == 2
    assert summary["rejected_rows"] == 0
    assert summary["normalized_rows"] == {"equity_trade": 1, "equity_quote": 1}
    assert summary["authorization_asserted"] is False
    assert summary["g2_coverage_change"] == 0

    trade = intake.inspect_file(Path(summary["outputs"]["equity_trade"]), output)
    quote = intake.inspect_file(Path(summary["outputs"]["equity_quote"]), output)
    assert trade.candidate_record_kind == "equity_trade"
    assert quote.candidate_record_kind == "equity_quote"
    assert trade.candidate_source_family == "generic_authorized_market_data"
    assert quote.candidate_source_family == "generic_authorized_market_data"
    assert trade.confidence == "high"
    assert quote.confidence == "high"
    assert trade.detected_trade_date == "2011-03-21"
    assert quote.detected_trade_date == "2011-03-21"


def test_option_gzip_delivery_decodes_ric_metadata_and_is_intake_ready(tmp_path):
    raw = tmp_path / "raw_option.csv.gz"
    _write_raw(
        raw,
        [
            {
                "#RIC": "CNMDD271102500.U",
                "Date-Time": "2011-04-27T15:22:00.250000-04:00",
                "Type": "Trade",
                "Price": "1.25",
                "Volume": "10",
            },
            {
                "#RIC": "CNMDP271102500.U",
                "Date-Time": "2011-04-27T15:22:01.000000-04:00",
                "Type": "Quote",
                "Bid Price": "1.20",
                "Bid Size": "5",
                "Ask Price": "1.30",
                "Ask Size": "7",
            },
        ],
        gz=True,
    )

    output = tmp_path / "canonical-option"
    summary = delivery.normalize_delivery(
        raw,
        lane="option",
        trade_date="2011-04-27",
        output_dir=output,
    )

    assert summary["rejected_rows"] == 0
    assert summary["normalized_rows"] == {"option_trade": 1, "option_quote": 1}

    trade = intake.inspect_file(Path(summary["outputs"]["option_trade"]), output)
    quote = intake.inspect_file(Path(summary["outputs"]["option_quote"]), output)
    assert trade.candidate_record_kind == "option_trade"
    assert quote.candidate_record_kind == "option_quote"
    assert trade.candidate_source_family == "generic_authorized_market_data"
    assert quote.candidate_source_family == "generic_authorized_market_data"

    with Path(summary["outputs"]["option_trade"]).open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        row = next(csv.DictReader(handle))
    assert row["underlying_symbol"] == "CNMD"
    assert row["expiration"] == "2011-04-27"
    assert row["strike"] == "25.0"
    assert row["option_type"] == "call"


def test_delivery_rejects_unknown_equity_ric_and_wrong_local_date(tmp_path):
    raw = tmp_path / "raw_bad.csv"
    _write_raw(
        raw,
        [
            {
                "#RIC": "NOTREAL.N",
                "Date-Time": "2011-03-21T10:00:00.000000-04:00",
                "Type": "Trade",
                "Price": "1",
                "Volume": "1",
            },
            {
                "#RIC": "JNPR.K",
                "Date-Time": "2011-03-22T10:00:00.000000-04:00",
                "Type": "Trade",
                "Price": "40",
                "Volume": "100",
            },
        ],
    )

    summary = delivery.normalize_delivery(
        raw,
        lane="equity",
        trade_date="2011-03-21",
        output_dir=tmp_path / "bad-out",
    )

    assert summary["raw_rows"] == 2
    assert summary["rejected_rows"] == 2
    assert summary["outputs"] == {}
    reasons = [row["reason"] for row in summary["rejects"]]
    assert any("frozen candidate map" in reason for reason in reasons)
    assert any("does not match expected" in reason for reason in reasons)


def test_equity_candidate_map_is_unambiguous():
    mapping = delivery.build_equity_ric_symbol_map()
    assert mapping["JNPR.K"] == "JNPR"
    assert len(mapping) >= 146
