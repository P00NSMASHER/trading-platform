from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from baseline_engine import build, build_baselines, load_shares, shares_as_of


def _row(day: date, *, minute="14:30", value=100.0, spread=0.1):
    local = datetime.fromisoformat(f"{day.isoformat()}T{minute}:00").replace(tzinfo=ZoneInfo("America/New_York"))
    utc = local.astimezone(ZoneInfo("UTC")).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {
        "asset_class": "equity",
        "minute_ts_utc": utc,
        "symbol": "TEST",
        "local_date": day,
        "local_minute": minute,
        "values": {"volume": float(value), "mean_relative_spread": float(spread)},
        "source_name": "fixture",
    }


def test_21_day_baseline_excludes_current_observation():
    start = date(2026, 1, 2)
    rows = [_row(start + timedelta(days=i), value=float(i + 1)) for i in range(22)]
    out = build_baselines(rows, lookback_days=21, min_history=3)
    volume = [r for r in out if r.metric == "volume"]
    last = volume[-1]
    assert last.history_n == 21
    assert last.history_status == "full"
    assert float(last.baseline_mean) == pytest.approx(11.0)
    # Current value 22 is not allowed to contaminate the mean.
    assert float(last.baseline_mean) != pytest.approx(11.5)


def test_same_minute_baseline_does_not_mix_clock_times():
    start = date(2026, 2, 1)
    rows = []
    for i in range(5):
        d = start + timedelta(days=i)
        rows.append(_row(d, minute="10:00", value=10 + i))
        rows.append(_row(d, minute="15:00", value=1000 + i))
    rows.append(_row(start + timedelta(days=5), minute="10:00", value=20))
    out = build_baselines(rows, lookback_days=5, min_history=3)
    target = [r for r in out if r.metric == "volume" and r.local_date == "2026-02-06" and r.local_minute == "10:00"][0]
    assert target.history_n == 5
    assert float(target.baseline_mean) == pytest.approx(12.0)


def test_insufficient_history_has_no_zscore():
    start = date(2026, 3, 1)
    rows = [_row(start + timedelta(days=i), value=10 + i) for i in range(3)]
    out = build_baselines(rows, lookback_days=21, min_history=5)
    last = [r for r in out if r.metric == "volume"][-1]
    assert last.history_n == 2
    assert last.history_status == "insufficient"
    assert last.zscore == ""
    assert last.robust_zscore == ""


def test_robust_zscore_is_computed_when_mad_positive():
    start = date(2026, 4, 1)
    values = [10, 11, 12, 13, 14, 15, 16]
    rows = [_row(start + timedelta(days=i), value=v) for i, v in enumerate(values)]
    rows.append(_row(start + timedelta(days=7), value=30))
    out = build_baselines(rows, lookback_days=7, min_history=5)
    last = [r for r in out if r.metric == "volume"][-1]
    assert last.history_n == 7
    assert last.robust_zscore != ""
    assert float(last.robust_zscore) > 3


def test_point_in_time_shares_ignore_future_record(tmp_path):
    p = tmp_path / "shares.csv"
    p.write_text(
        "symbol,effective_date,shares_outstanding\n"
        "TEST,2026-01-01,1000\n"
        "TEST,2026-03-01,2000\n",
        encoding="utf-8",
    )
    shares = load_shares(p)
    assert shares_as_of(shares, "TEST", date(2026, 2, 1)) == 1000
    assert shares_as_of(shares, "TEST", date(2026, 3, 1)) == 2000


def test_build_computes_turnover_and_manifest(tmp_path):
    eq = tmp_path / "equity_minutes.csv"
    with eq.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "minute_ts_utc", "symbol", "trade_count", "volume", "dollar_volume",
            "mean_quoted_spread", "mean_relative_spread", "source_name"
        ])
        w.writeheader()
        for i in range(4):
            d = date(2026, 1, 5) + timedelta(days=i)
            local = datetime.fromisoformat(f"{d.isoformat()}T14:30:00").replace(tzinfo=ZoneInfo("America/New_York"))
            w.writerow({
                "minute_ts_utc": local.astimezone(ZoneInfo("UTC")).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "symbol": "TEST", "trade_count": 10, "volume": 100 + 10*i,
                "dollar_volume": 10000 + 1000*i, "mean_quoted_spread": 0.1,
                "mean_relative_spread": 0.001, "source_name": "fixture"
            })
    shares = tmp_path / "shares.csv"
    shares.write_text("symbol,effective_date,shares_outstanding\nTEST,2020-01-01,1000\n", encoding="utf-8")
    manifest = build(
        equity_minutes=eq,
        option_minutes=None,
        shares_file=shares,
        output_dir=tmp_path / "out",
        lookback_days=3,
        min_history=2,
    )
    rows = list(csv.DictReader((tmp_path / "out/baseline_metrics.csv").open()))
    turnover = [r for r in rows if r["metric"] == "turnover"]
    assert len(turnover) == 4
    assert float(turnover[-1]["value"]) == pytest.approx(0.13)
    saved = json.loads((tmp_path / "out/baseline_manifest.json").read_text())
    assert saved["lookback_trading_days"] == 3
    assert "BUY" in saved["prohibited_outputs"]


def test_duplicate_same_date_replaces_history_not_count(tmp_path):
    # Defensive behavior: if duplicate same-date same-minute rows arrive, later rows replace rather than inflate history_n.
    d0 = date(2026, 5, 1)
    rows = [
        _row(d0, value=10),
        _row(d0, value=20),
        _row(d0 + timedelta(days=1), value=30),
    ]
    out = build_baselines(rows, lookback_days=21, min_history=1)
    target = [r for r in out if r.metric == "volume"][-1]
    assert target.history_n == 1
    assert float(target.baseline_mean) == pytest.approx(20.0)
