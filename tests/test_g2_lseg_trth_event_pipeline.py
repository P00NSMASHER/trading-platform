from datetime import date, datetime

import pandas as pd

import g2_lseg_trth_event_pipeline as event


def _quote(ts, bid=10.0, ask=10.2, bid_size=5.0, ask_size=6.0, no_quote=False):
    return {
        "timestamp": ts,
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "qualifier_flags": {"no_quote": no_quote},
    }


def _trade(ts, price=10.1, **flags):
    base_flags = {
        "next_day": False,
        "prior_reference_price": False,
        "derivatively_priced": False,
        "sold_out_of_sequence": False,
        "form_t": False,
    }
    base_flags.update(flags)
    return {"timestamp": ts, "price": price, "qualifier_flags": base_flags}


def test_aligns_current_and_next_utc_partitions_to_target_et_date():
    rows = event.align_utc_partitioned_trade_rows(
        date(2015, 2, 12),
        [
            {"Date": "2015-02-12", "id": "current-good"},
            {"Date": "2015-02-11", "id": "current-old"},
        ],
        [
            {"Date": "2015-02-12", "id": "next-late-report"},
            {"Date": "2015-02-13", "id": "next-day"},
        ],
    )
    assert [row["id"] for row in rows] == ["current-good", "next-late-report"]


def test_extended_hours_filter_matches_original_0400_2000_window():
    assert event.in_extended_hours("2015-02-12T04:00:00") is True
    assert event.in_extended_hours("2015-02-12T20:00:00") is True
    assert event.in_extended_hours("2015-02-12T03:59:59") is False
    assert event.in_extended_hours("2015-02-12T20:00:01") is False


def test_quote_cleaning_matches_zero_and_noquote_rules():
    assert event.clean_quote_for_original_resample(
        _quote("2015-02-12T15:00:00", bid=0.0)
    )["bid"] is None
    assert event.clean_quote_for_original_resample(
        _quote("2015-02-12T15:00:00", ask_size=0.0)
    )["ask"] is None

    cleaned = event.clean_quote_for_original_resample(
        _quote("2015-02-12T15:00:00", no_quote=True)
    )
    assert cleaned["bid"] is None
    assert cleaned["ask"] is None


def test_regular_trade_filter_matches_original_exclusions():
    assert event.keep_regular_trade_for_original_resample(
        _trade("2015-02-12T15:00:00")
    ) is True
    for flag in (
        "next_day",
        "prior_reference_price",
        "derivatively_priced",
        "sold_out_of_sequence",
    ):
        assert event.keep_regular_trade_for_original_resample(
            _trade("2015-02-12T15:00:00", **{flag: True})
        ) is False


def test_research_open_anchor_shifts_only_for_after_noon_announcements():
    day = date(2015, 2, 12)
    assert event.research_open_timestamp(
        day, datetime(2015, 2, 12, 8, 0)
    ) == datetime(2015, 2, 12, 9, 30)

    assert event.research_open_timestamp(
        day, datetime(2015, 2, 12, 15, 0)
    ) == datetime(2015, 2, 13, 9, 30)


def test_quote_grids_match_original_lengths_and_boundaries():
    ts = datetime(2015, 2, 12, 15, 0)
    grids = event.quote_event_grids(ts, ts.date())

    assert len(grids["announcement_1s"]) == 601
    assert grids["announcement_1s"][0] == datetime(2015, 2, 12, 14, 55)
    assert grids["announcement_1s"][-1] == datetime(2015, 2, 12, 15, 5)

    assert len(grids["announcement_1m"]) == 126
    assert grids["announcement_1m"][0] == datetime(2015, 2, 12, 14, 55)
    assert grids["announcement_1m"][-1] == datetime(2015, 2, 12, 17, 0)

    assert grids["opening_1m"][5] == datetime(2015, 2, 13, 9, 30)


def test_trade_grid_extends_to_30_minutes_after_relevant_open():
    ts = datetime(2015, 2, 12, 15, 0)
    grid = event.trade_event_grid(ts, ts.date())
    assert grid[0] == datetime(2015, 2, 12, 14, 55)
    assert grid[-1] == datetime(2015, 2, 13, 10, 0)


def test_quote_resample_uses_last_observation_without_tolerance():
    ts = datetime(2015, 2, 12, 10, 0)
    rows = [
        _quote("2015-02-12T09:59:58", bid=10.0, ask=10.2),
        _quote("2015-02-12T10:00:02", bid=10.1, ask=10.3),
    ]
    out = event.resample_quotes_original(rows, ts, ts.date())["announcement_1s"]
    at_event = out[out["SecondsAfter"] == 0].iloc[0]
    assert at_event["bid"] == 10.0
    assert at_event["ask"] == 10.2


def test_trade_resample_uses_one_minute_backward_tolerance():
    ts = datetime(2015, 2, 12, 10, 0)
    rows = [
        _trade("2015-02-12T09:58:30", price=9.9),
        _trade("2015-02-12T09:59:30", price=10.1),
    ]
    out = event.resample_trades_original(rows, ts, ts.date())
    at_event = out[out["MinutesAfter"] == 0].iloc[0]
    assert at_event["price"] == 10.1

    rows = [_trade("2015-02-12T09:58:30", price=9.9)]
    out = event.resample_trades_original(rows, ts, ts.date())
    at_event = out[out["MinutesAfter"] == 0].iloc[0]
    assert pd.isna(at_event["price"])


def test_after_hours_form_t_selection_runs_event_to_relevant_open():
    ts = datetime(2015, 2, 12, 15, 0)
    rows = [
        _trade("2015-02-12T16:30:00", price=10.1, form_t=True),
        _trade("2015-02-12T17:00:00", price=10.2, form_t=False),
        _trade("2015-02-13T09:29:00", price=10.3, form_t=True),
        _trade("2015-02-13T09:31:00", price=10.4, form_t=True),
    ]
    selected = event.after_hours_form_t_trades(rows, ts, ts.date())
    assert [row["price"] for row in selected] == [10.1, 10.3]


def test_quote_resample_handles_empty_event_slice_without_merge_dtype_error():
    ts = datetime(2015, 2, 12, 15, 0)
    out = event.resample_quotes_original([], ts, ts.date())
    assert set(out) == {
        "announcement_1s",
        "announcement_1m",
        "opening_1s",
        "opening_1m",
    }
    at_event = out["announcement_1s"][out["announcement_1s"]["SecondsAfter"] == 0].iloc[0]
    assert pd.isna(at_event["bid"])
    assert pd.isna(at_event["ask"])


def test_trade_resample_handles_empty_event_slice_without_merge_dtype_error():
    ts = datetime(2015, 2, 12, 15, 0)
    out = event.resample_trades_original([], ts, ts.date())
    at_event = out[out["MinutesAfter"] == 0].iloc[0]
    assert pd.isna(at_event["price"])
    assert out.iloc[-1]["MinutesAfterOpen"] == 30


def test_offset_aware_tick_timestamp_is_compared_in_new_york_wall_time():
    ts = datetime(2015, 2, 12, 10, 0)
    rows = [
        _quote("2015-02-12T14:59:58+00:00", bid=10.0, ask=10.2),
        _quote("2015-02-12T15:00:02+00:00", bid=10.1, ask=10.3),
    ]
    out = event.resample_quotes_original(rows, ts, ts.date())["announcement_1s"]
    at_event = out[out["SecondsAfter"] == 0].iloc[0]
    assert at_event["bid"] == 10.0
    assert at_event["ask"] == 10.2


def test_trailing_z_tick_timestamp_is_supported():
    assert event.in_extended_hours("2015-02-12T15:00:00Z") is True
