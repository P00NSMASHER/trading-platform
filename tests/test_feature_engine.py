from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from feature_engine import build, build_features, load_baselines


def _metric(ts: str, metric: str, *, asset="equity", z="", robust="", ratio="", status="full", value="1"):
    return {
        "asset_class": asset,
        "minute_ts_utc": ts,
        "symbol": "TEST",
        "local_date": "2026-01-05",
        "local_minute": ts[11:16],
        "metric": metric,
        "value": value,
        "history_n": "21",
        "baseline_mean": "1",
        "baseline_std": "1",
        "baseline_median": "1",
        "baseline_mad": "1",
        "zscore": z,
        "robust_zscore": robust,
        "baseline_ratio": ratio,
        "history_status": status,
        "source_name": "fixture",
        "research_use_only": "1",
    }


def _index(rows):
    out = {}
    for r in rows:
        out.setdefault((r["asset_class"], r["symbol"], r["minute_ts_utc"]), {})[r["metric"]] = r
    return out


def test_robust_zscore_preferred_over_standard():
    ts = "2026-01-05T19:30:00.000Z"
    idx = _index([_metric(ts, "volume", z="9", robust="2.5", ratio="3")])
    got = build_features(idx)[0]
    assert float(got.equity_volume_z) == pytest.approx(2.5)
    assert float(got.equity_volume_ratio) == pytest.approx(3.0)


def test_multivariate_score_is_positive_side_only():
    ts = "2026-01-05T19:30:00.000Z"
    idx = _index([
        _metric(ts, "volume", robust="3"),
        _metric(ts, "turnover", robust="-4"),
        _metric(ts, "mean_relative_spread", robust="2"),
        _metric(ts, "contract_volume", asset="option", robust="1"),
    ])
    got = build_features(idx)[0]
    assert float(got.multivariate_l2) == pytest.approx((9 + 4 + 1) ** 0.5)
    assert got.multivariate_2sigma_count == 2


def test_persistence_and_slope_use_only_current_and_prior_minutes():
    rows = []
    for minute, z in [(30, 0.0), (31, 1.0), (32, 2.0), (33, 3.0), (34, 4.0)]:
        ts = f"2026-01-05T19:{minute:02d}:00.000Z"
        rows.append(_metric(ts, "volume", robust=str(z)))
    got = build_features(_index(rows))[-1]
    assert got.equity_volume_anomaly_count_5m == 3
    assert float(got.equity_volume_peak_z_5m) == pytest.approx(4.0)
    assert float(got.equity_volume_z_slope_5m) == pytest.approx(1.0)
    assert float(got.equity_volume_acceleration_5m) == pytest.approx(2.5)


def test_sequence_resets_across_dates():
    a = _metric("2026-01-05T19:30:00.000Z", "volume", robust="5")
    b = _metric("2026-01-06T19:30:00.000Z", "volume", robust="1")
    b["local_date"] = "2026-01-06"
    got = build_features(_index([a, b]))[-1]
    assert got.equity_volume_anomaly_count_30m == 0
    assert float(got.equity_volume_peak_z_30m) == pytest.approx(1.0)


def test_backward_returns_do_not_use_future_prices():
    rows = []
    equity = {}
    for minute, close in [(30, 100.0), (31, 101.0), (32, 102.0), (35, 105.0)]:
        ts = f"2026-01-05T19:{minute:02d}:00.000Z"
        rows.append(_metric(ts, "volume", robust="0"))
        equity[("TEST", ts)] = {
            "_ts": __import__("datetime").datetime.fromisoformat(ts.replace("Z", "+00:00")),
            "_volume": 100.0,
            "_close": close,
            "_source_name": "fixture",
            "symbol": "TEST",
            "minute_ts_utc": ts,
        }
    got = build_features(_index(rows), equity)[-1]
    assert float(got.return_5m) == pytest.approx(0.05)
    # No exact/near 1-minute prior at 19:34, so no fabricated 1-minute return.
    assert got.return_1m == ""


def test_call_put_and_option_equity_ratio():
    ts = "2026-01-05T19:30:00.000Z"
    idx = _index([
        _metric(ts, "volume", robust="1"),
        _metric(ts, "contract_volume", asset="option", robust="2"),
    ])
    equity = {("TEST", ts): {"_ts": None, "_volume": 2000.0, "_close": 10.0, "_source_name": "fixture"}}
    options = {("TEST", ts): {"_ts": None, "_contract_volume": 50.0, "_call_volume": 40.0, "_put_volume": 10.0, "_source_name": "fixture"}}
    got = build_features(idx, equity, options)[0]
    assert float(got.call_put_imbalance) == pytest.approx(0.6)
    assert float(got.option_contracts_per_100_equity_shares) == pytest.approx(2.5)


def test_feature_status_tracks_baseline_readiness():
    ts = "2026-01-05T19:30:00.000Z"
    idx = _index([
        _metric(ts, "volume", robust="1", status="full"),
        _metric(ts, "contract_volume", asset="option", robust="1", status="partial"),
    ])
    got = build_features(idx)[0]
    assert got.feature_status == "partial"
    assert float(got.full_history_fraction) == pytest.approx(0.5)


def test_build_writes_manifest_and_prohibits_trading_outputs(tmp_path: Path):
    baseline = tmp_path / "baseline.csv"
    fields = [
        "asset_class", "minute_ts_utc", "symbol", "local_date", "local_minute", "metric", "value",
        "history_n", "baseline_mean", "baseline_std", "baseline_median", "baseline_mad", "zscore",
        "robust_zscore", "baseline_ratio", "history_status", "source_name", "research_use_only",
    ]
    with baseline.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow(_metric("2026-01-05T19:30:00.000Z", "volume", robust="2.2"))
    manifest = build(baseline_metrics=baseline, output_dir=tmp_path / "out")
    assert manifest["outputs"]["feature_vector_rows"] == 1
    saved = json.loads((tmp_path / "out/feature_manifest.json").read_text())
    assert "BUY" in saved["prohibited_outputs"]
    assert "future price" in saved["lookahead_policy"]
    assert (tmp_path / "out/feature_vectors.csv").exists()


def test_load_baselines_rejects_missing_columns(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text("minute_ts_utc,symbol\n2026-01-01T15:00:00Z,X\n")
    with pytest.raises(ValueError):
        load_baselines(p)
