from datetime import date, datetime

import g2_lseg_trth_event_slice as slicing


def test_quote_window_uses_one_day_before_and_two_days_after():
    out = slicing.event_slice_window(
        datetime(2015, 2, 12, 15, 0),
        datetime(2015, 2, 12, 16, 0),
        lane="quotes",
    )
    assert out["start_date"] == "2015-02-11"
    assert out["end_date"] == "2015-02-17"
    assert out["calendar_dates"][0] == "2015-02-11"
    assert out["calendar_dates"][-1] == "2015-02-17"


def test_trade_window_uses_only_one_business_day_after_later_timestamp():
    out = slicing.event_slice_window(
        datetime(2015, 2, 12, 15, 0),
        datetime(2015, 2, 12, 16, 0),
        lane="trades",
    )
    assert out["start_date"] == "2015-02-11"
    assert out["end_date"] == "2015-02-13"


def test_window_uses_earlier_and_later_of_event_and_ibes():
    out = slicing.event_slice_window(
        datetime(2015, 2, 13, 8, 0),
        datetime(2015, 2, 12, 16, 0),
        lane="trades",
    )
    assert out["start_date"] == "2015-02-11"
    assert out["end_date"] == "2015-02-17"


def test_source_filename_matches_original_research_conventions():
    assert slicing.source_filename("NMQ", date(2015, 2, 12), lane="quotes") == (
        "NMQ-Quotes-2015-02-12.csv.gz"
    )
    assert slicing.source_filename("NMQ", "2015-02-12", lane="trades") == (
        "NMQ-TradesParsed-2015-02-12.csv.gz"
    )


def test_event_output_filename_matches_original_research_conventions():
    assert slicing.event_output_filename(
        "NMQ", date(2015, 2, 12), 12026, lane="quotes"
    ) == "NMQ-QuotesAroundEvent-2015-02-12_12026.csv.gz"
    assert slicing.event_output_filename(
        "NMQ", "2015-02-12", "12026", lane="trades"
    ) == "NMQ-TradesAroundEvent-2015-02-12_12026.csv.gz"


def test_filter_rows_keeps_only_exact_ric():
    rows = [
        {"#RIC": "QLIK.O", "Price": 1},
        {"#RIC": "QLIK.K", "Price": 2},
        {"RIC": "QLIK.O", "Price": 3},
    ]
    out = slicing.filter_rows_to_ric(rows, "QLIK.O")
    assert [row["Price"] for row in out] == [1, 3]


def test_build_event_slice_plan_is_non_authoritative_and_complete():
    out = slicing.build_event_slice_plan(
        permno=12026,
        ric="QLIK.O",
        exchange="NMQ",
        event_timestamp="2015-02-12T15:39:00",
        ibes_timestamp="2015-02-12T16:00:00",
    )

    assert out["schema_version"] == "1"
    assert out["coverage_claim"] is False
    assert out["quotes"]["output_file"] == (
        "NMQ-QuotesAroundEvent-2015-02-12_12026.csv.gz"
    )
    assert out["trades"]["output_file"] == (
        "NMQ-TradesAroundEvent-2015-02-12_12026.csv.gz"
    )
    assert out["quotes"]["source_files"][0] == "NMQ-Quotes-2015-02-11.csv.gz"
    assert out["trades"]["source_files"][-1] == "NMQ-TradesParsed-2015-02-13.csv.gz"
