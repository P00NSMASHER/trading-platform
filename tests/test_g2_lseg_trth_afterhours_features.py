from datetime import date, datetime
import math

import pytest

import g2_lseg_trth_afterhours_features as features


def _trade(ts, price, volume, exchange="NAS", **flags):
    base = {
        "form_t": False,
        "sweep": False,
        "odd_lot": False,
    }
    base.update(flags)
    return {
        "timestamp": ts,
        "price": price,
        "size": volume,
        "exchange": exchange,
        "qualifier_flags": base,
    }


def test_primary_code_maps_match_original_research():
    assert features.primary_contributor_codes("NMQ") == {"NAS", "THM"}
    assert features.primary_contributor_codes("NYQ") == {"PSE", "NYS", "ASE"}
    with pytest.raises(ValueError, match="unknown listing exchange"):
        features.primary_contributor_codes("UNKNOWN")


def test_after_hours_form_t_sequence_reproduces_trade_ids_dark_primary_and_returns():
    event_ts = datetime(2015, 2, 12, 15, 0)
    rows = [
        _trade("2015-02-12T14:59:30", 10.0, 100, exchange="NAS"),
        _trade("2015-02-12T16:30:00", 11.0, 50, exchange="ADF", form_t=True, sweep=True),
        _trade("2015-02-12T17:00:00", 12.0, 70, exchange="THM", form_t=True, odd_lot=True),
        _trade("2015-02-13T09:31:00", 13.0, 80, exchange="NAS", form_t=True),
    ]

    out = features.after_hours_form_t_features(
        rows,
        event_timestamp=event_ts,
        event_date=event_ts.date(),
        listing_exchange="NMQ",
    )

    assert [row["trade_id"] for row in out] == [1, 2]
    assert out[0]["dark"] is True
    assert out[0]["primary"] is False
    assert out[0]["sweep"] is True
    assert out[1]["dark"] is False
    assert out[1]["primary"] is True
    assert out[1]["odd_lot"] is True
    assert out[0]["duration_seconds"] == 5400.0
    assert out[1]["duration_seconds"] == 1800.0
    assert out[0]["log_return"] == pytest.approx(math.log(11.0) - math.log(10.0))
    assert out[1]["log_return"] == pytest.approx(math.log(12.0) - math.log(11.0))
    assert out[1]["cumulative_log_return"] == pytest.approx(math.log(12.0) - math.log(10.0))


def test_after_hours_sequence_without_pre_event_trade_keeps_first_return_missing():
    event_ts = datetime(2015, 2, 12, 15, 0)
    rows = [
        _trade("2015-02-12T16:30:00", 11.0, 50, exchange="PSE", form_t=True),
        _trade("2015-02-12T17:00:00", 12.0, 70, exchange="NYS", form_t=True),
    ]
    out = features.after_hours_form_t_features(
        rows,
        event_timestamp=event_ts,
        event_date=event_ts.date(),
        listing_exchange="NYQ",
    )
    assert math.isnan(out[0]["log_return"])
    assert math.isnan(out[0]["cumulative_log_return"])
    assert out[1]["log_return"] == pytest.approx(math.log(12.0) - math.log(11.0))


def test_pre_noon_event_uses_previous_business_day_as_pre_sample():
    pre, post = features.descriptive_sample_dates(
        event_timestamp=datetime(2015, 2, 12, 8, 0),
        event_date=date(2015, 2, 12),
    )
    assert pre == date(2015, 2, 11)
    assert post == date(2015, 2, 12)


def test_after_noon_event_uses_event_day_and_next_business_day():
    pre, post = features.descriptive_sample_dates(
        event_timestamp=datetime(2015, 2, 12, 15, 0),
        event_date=date(2015, 2, 12),
    )
    assert pre == date(2015, 2, 12)
    assert post == date(2015, 2, 13)


def test_descriptive_stats_match_original_bins_and_exclude_form_t():
    event_ts = datetime(2015, 2, 12, 15, 0)
    rows = [
        _trade("2015-02-12T10:00:00", 10.0, 50),
        _trade("2015-02-12T11:00:00", 10.0, 100),
        _trade("2015-02-12T12:00:00", 10.0, 500),
        _trade("2015-02-12T13:00:00", 100.0, 1000),
        _trade("2015-02-12T16:30:00", 20.0, 20, form_t=True),
        _trade("2015-02-13T10:00:00", 10.0, 50),
    ]
    out = features.descriptive_trade_stats(
        rows,
        event_timestamp=event_ts,
        event_date=event_ts.date(),
    )

    pre = out["pre_all"]
    assert pre is not None
    assert pre["number_of_trades"] == 4
    assert pre["volume_[0,100)"] == pytest.approx(0.25)
    assert pre["volume_[100,500)"] == pytest.approx(0.25)
    assert pre["volume_[500,1000)"] == pytest.approx(0.25)
    assert pre["volume_[1000,inf)"] == pytest.approx(0.25)
    assert pre["value_[0,1000)"] == pytest.approx(0.25)
    assert pre["value_[1000,5000)"] == pytest.approx(0.25)
    assert pre["value_[5000,50000)"] == pytest.approx(0.25)
    assert pre["value_[50000,inf)"] == pytest.approx(0.25)

    post = out["post_all"]
    assert post is not None
    assert post["number_of_trades"] == 1
    assert post["volume_[0,100)"] == pytest.approx(1.0)
    assert post["value_[0,1000)"] == pytest.approx(1.0)


def test_descriptive_stats_return_none_when_sample_side_has_no_regular_trades():
    event_ts = datetime(2015, 2, 12, 15, 0)
    rows = [_trade("2015-02-12T16:30:00", 10.0, 50, form_t=True)]
    out = features.descriptive_trade_stats(
        rows,
        event_timestamp=event_ts,
        event_date=event_ts.date(),
    )
    assert out == {"pre_all": None, "post_all": None}


def test_selected_form_t_trade_requires_positive_price_and_volume():
    event_ts = datetime(2015, 2, 12, 15, 0)
    with pytest.raises(ValueError, match="price and volume must be positive"):
        features.after_hours_form_t_features(
            [_trade("2015-02-12T16:30:00", 0.0, 50, form_t=True)],
            event_timestamp=event_ts,
            event_date=event_ts.date(),
            listing_exchange="NMQ",
        )
