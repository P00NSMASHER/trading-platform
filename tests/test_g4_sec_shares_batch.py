from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import g4_sec_shares_batch as g4

NY = ZoneInfo("America/New_York")


def test_target_cutoff_uses_earliest_market_window():
    req = {"trade_date": "2011-03-21", "window_intervals_local": "15:20-16:00;10:15-10:45"}
    cutoff = g4._target_cutoff(req)
    assert cutoff.astimezone(NY).isoformat().startswith("2011-03-21T10:15:00")


def test_select_fact_rejects_future_filed_and_after_cutoff():
    req = {"trade_date": "2011-03-21", "window_intervals_local": "15:20-16:00"}
    cands = [
        {"tag": "dei:EntityCommonStockSharesOutstanding", "tag_rank": 0, "val": 10,
         "end": date(2011, 3, 1), "filed": date(2011, 3, 21), "form": "10-Q", "accn": "late", "frame": ""},
        {"tag": "dei:EntityCommonStockSharesOutstanding", "tag_rank": 0, "val": 9,
         "end": date(2011, 2, 28), "filed": date(2011, 3, 20), "form": "10-K", "accn": "good", "frame": ""},
        {"tag": "dei:EntityCommonStockSharesOutstanding", "tag_rank": 0, "val": 11,
         "end": date(2011, 3, 22), "filed": date(2011, 3, 22), "form": "10-Q", "accn": "future", "frame": ""},
    ]
    acceptance = {
        "late": "2011-03-21T20:00:00Z",
        "good": "2011-03-20T18:00:00Z",
        "future": "2011-03-22T12:00:00Z",
    }
    chosen, reason = g4._select_fact(req, cands, acceptance)
    assert reason == ""
    assert chosen["accn"] == "good"
    assert chosen["val"] == 9


def test_select_fact_enforces_130_day_staleness():
    req = {"trade_date": "2011-08-01", "window_intervals_local": "10:00-11:00"}
    cands = [{
        "tag": "dei:EntityCommonStockSharesOutstanding", "tag_rank": 0, "val": 10,
        "end": date(2011, 1, 1), "filed": date(2011, 1, 10), "form": "10-K", "accn": "old", "frame": "",
    }]
    chosen, reason = g4._select_fact(req, cands, {"old": "2011-01-10T12:00:00Z"})
    assert chosen is None
    assert reason == "no_public_pre_cutoff_share_fact_within_staleness_limit"
