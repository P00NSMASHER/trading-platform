from datetime import date

import pytest

import g2_lseg_trth_normalizer as trth


def test_reconstructs_trade_timestamp_from_original_rule():
    row = {
        "Date[G]": "27-Apr-2011",
        "Trd/Qte Date": "27-Apr-2011",
        "Exch Time": "15:22:00.250",
        "GMT Offset": "0",
    }
    assert trth.reconstruct_trade_timestamp(row).isoformat(timespec="microseconds") == (
        "2011-04-27T15:22:00.250000"
    )


def test_reconstructs_quote_timestamp_and_falls_back_to_time_g():
    row = {
        "Date[G]": "27-Apr-2011",
        "Time[G]": "15:21:59.500",
        "Quote Time": "",
        "GMT Offset": "0",
    }
    assert trth.reconstruct_quote_timestamp(row).isoformat(timespec="microseconds") == (
        "2011-04-27T15:21:59.500000"
    )


def test_quote_timestamp_wraps_across_midnight_like_original_code():
    row = {
        "Date[G]": "27-Apr-2011",
        "Time[G]": "00:00:01.000",
        "Quote Time": "23:59:59.000",
        "GMT Offset": "0",
    }
    assert trth.reconstruct_quote_timestamp(row).isoformat(timespec="microseconds") == (
        "2011-04-26T23:59:59.000000"
    )


def test_original_quote_qualifiers_are_preserved():
    flags = trth.quote_qualifier_flags("R[PRC_QL_CD];CQ[PRC_QL3]")
    assert flags == {
        "regular": True,
        "opening": False,
        "closing": True,
        "no_quote": False,
    }


def test_original_trade_qualifiers_are_preserved():
    flags = trth.trade_qualifier_flags("T[LSTSALCOND];ODD[IRGCOND]")
    assert flags["form_t"] is True
    assert flags["odd_lot"] is True
    assert flags["opening"] is False


def test_early_close_calendar_covers_original_2011_2015_rules():
    assert trth.is_early_close(date(2011, 11, 25)) is True
    assert trth.is_early_close(date(2014, 11, 28)) is True
    assert trth.is_early_close(date(2015, 11, 27)) is True
    assert trth.is_early_close(date(2015, 11, 30)) is False


def test_normalizes_equity_trade_to_g2_fields():
    row = {
        "#RIC": "CNMD.O",
        "Type": "Trade",
        "Date[G]": "27-Apr-2011",
        "Trd/Qte Date": "27-Apr-2011",
        "Exch Time": "15:22:00.000",
        "GMT Offset": "0",
        "Ex/Cntrb.ID": "Q",
        "Price": "25.10",
        "Volume": "200",
        "Qualifiers": "",
    }
    out = trth.normalize_equity_trade(row, "CNMD")
    assert out["symbol"] == "CNMD"
    assert out["source_ric"] == "CNMD.O"
    assert out["timestamp"] == "2011-04-27T15:22:00.000000"
    assert out["price"] == 25.10
    assert out["size"] == 200.0
    assert out["exchange"] == "Q"


def test_normalizes_equity_quote_to_g2_fields():
    row = {
        "#RIC": "CNMD.O",
        "Type": "Quote",
        "Date[G]": "27-Apr-2011",
        "Time[G]": "15:21:59.000",
        "Quote Time": "15:21:59.000",
        "GMT Offset": "0",
        "Bid Price": "25.05",
        "Ask Price": "25.15",
        "Bid Size": "3",
        "Ask Size": "4",
        "Qualifiers": "R[PRC_QL_CD]",
    }
    out = trth.normalize_equity_quote(row, "CNMD")
    assert out["symbol"] == "CNMD"
    assert out["bid"] == 25.05
    assert out["ask"] == 25.15
    assert out["bid_size"] == 3.0
    assert out["ask_size"] == 4.0
    assert out["qualifier_flags"]["regular"] is True


def test_option_trade_requires_explicit_contract_metadata():
    row = {
        "#RIC": "CNMD111119C00025000.U",
        "Type": "Trade",
        "Date[G]": "27-Apr-2011",
        "Trd/Qte Date": "27-Apr-2011",
        "Exch Time": "15:22:00.000",
        "GMT Offset": "0",
        "Price": "1.25",
        "Volume": "10",
    }
    with pytest.raises(ValueError, match="missing option metadata"):
        trth.normalize_option_trade(row, {"option_symbol": "CNMD111119C00025000"})


def test_normalizes_option_quote_with_validated_contract_metadata():
    row = {
        "#RIC": "CNMD111119C00025000.U",
        "Type": "Quote",
        "Date[G]": "27-Apr-2011",
        "Time[G]": "15:21:59.000",
        "Quote Time": "15:21:59.000",
        "GMT Offset": "0",
        "Bid Price": "1.20",
        "Ask Price": "1.30",
        "Bid Size": "5",
        "Ask Size": "7",
    }
    meta = {
        "underlying_symbol": "CNMD",
        "option_symbol": "CNMD111119C00025000",
        "expiration": "2011-11-19",
        "strike": "25",
        "option_type": "C",
    }
    out = trth.normalize_option_quote(row, meta)
    assert out["symbol"] == "CNMD111119C00025000"
    assert out["underlying_symbol"] == "CNMD"
    assert out["option_type"] == "call"
    assert out["strike"] == 25.0


def test_fail_closed_quote_validation():
    row = {
        "#RIC": "CNMD.O",
        "Type": "Quote",
        "Date[G]": "27-Apr-2011",
        "Time[G]": "15:21:59.000",
        "Quote Time": "15:21:59.000",
        "GMT Offset": "0",
        "Bid Price": "25.20",
        "Ask Price": "25.10",
        "Bid Size": "3",
        "Ask Size": "4",
    }
    with pytest.raises(ValueError, match="invalid quote economics"):
        trth.normalize_equity_quote(row, "CNMD")
