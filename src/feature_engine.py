from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = "0.4.0"

# Feature windows are backward-looking and include the current minute.
WINDOWS = (5, 15, 30)


@dataclass(frozen=True)
class FeatureVector:
    minute_ts_utc: str
    symbol: str
    local_date: str
    local_minute: str
    feature_status: str
    full_history_fraction: str

    equity_volume_z: str
    equity_turnover_z: str
    equity_spread_z: str
    option_volume_z: str
    option_dollar_volume_z: str

    equity_volume_ratio: str
    option_volume_ratio: str
    call_put_imbalance: str
    option_contracts_per_100_equity_shares: str

    return_1m: str
    return_5m: str
    return_15m: str
    return_30m: str
    realized_vol_5m: str
    realized_vol_15m: str
    realized_vol_30m: str

    equity_volume_peak_z_5m: str
    equity_volume_peak_z_15m: str
    equity_volume_peak_z_30m: str
    equity_volume_anomaly_count_5m: int
    equity_volume_anomaly_count_15m: int
    equity_volume_anomaly_count_30m: int
    equity_volume_z_slope_5m: str
    equity_volume_z_slope_15m: str
    equity_volume_z_slope_30m: str
    equity_volume_acceleration_5m: str

    spread_widen_count_5m: int
    option_volume_anomaly_count_5m: int

    multivariate_l2: str
    multivariate_2sigma_count: int
    multivariate_change_5m: str

    source_names: str
    research_use_only: int = 1


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _parse_float(value: str | None) -> float | None:
    value = _clean(value)
    if not value:
        return None
    try:
        out = float(value)
    except Exception as exc:
        raise ValueError(f"invalid numeric value {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"non-finite numeric value {value!r}")
    return out


def _parse_int(value: str | None) -> int | None:
    value = _clean(value)
    if not value:
        return None
    try:
        x = float(value)
    except Exception as exc:
        raise ValueError(f"invalid integer value {value!r}") from exc
    if not x.is_integer():
        raise ValueError(f"non-integral value {value!r}")
    return int(x)


def _parse_ts(value: str) -> datetime:
    value = _clean(value)
    if not value:
        raise ValueError("blank minute timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid timestamp {value!r}") from exc
    if dt.tzinfo is None:
        raise ValueError("feature timestamps must include timezone")
    return dt.astimezone(timezone.utc)


def _fmt(value: float | None, digits: int = 10) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return (f"{value:.{digits}f}").rstrip("0").rstrip(".")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _preferred_score(metric: dict | None) -> float | None:
    if not metric:
        return None
    robust = _parse_float(metric.get("robust_zscore"))
    if robust is not None:
        return robust
    return _parse_float(metric.get("zscore"))


def _baseline_ratio(metric: dict | None) -> float | None:
    return _parse_float(metric.get("baseline_ratio")) if metric else None


def _status(metric_rows: list[dict]) -> tuple[str, float]:
    relevant = [r for r in metric_rows if r]
    if not relevant:
        return "insufficient", 0.0
    statuses = [r.get("history_status", "insufficient") for r in relevant]
    full_fraction = sum(s == "full" for s in statuses) / len(statuses)
    if all(s == "full" for s in statuses):
        return "full", full_fraction
    if any(s in {"partial", "full"} for s in statuses):
        return "partial", full_fraction
    return "insufficient", full_fraction


def load_baselines(path: Path) -> tuple[dict[tuple[str, str, str], dict[str, dict]], list[dict]]:
    """Return baseline metrics keyed by (asset_class, symbol, minute_ts_utc)."""
    index: dict[tuple[str, str, str], dict[str, dict]] = defaultdict(dict)
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "asset_class", "minute_ts_utc", "symbol", "local_date", "local_minute",
            "metric", "value", "history_status", "source_name",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"baseline file missing required columns: {sorted(missing)}")
        for row_number, row in enumerate(reader, start=2):
            asset = _clean(row.get("asset_class")).lower()
            if asset not in {"equity", "option"}:
                raise ValueError(f"baseline row {row_number}: unsupported asset_class={asset!r}")
            symbol = _clean(row.get("symbol")).upper()
            ts = _parse_ts(row.get("minute_ts_utc", ""))
            ts_key = ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            metric = _clean(row.get("metric"))
            if not symbol or not metric:
                raise ValueError(f"baseline row {row_number}: blank symbol/metric")
            norm = dict(row)
            norm["asset_class"] = asset
            norm["symbol"] = symbol
            norm["minute_ts_utc"] = ts_key
            index[(asset, symbol, ts_key)][metric] = norm
            rows.append(norm)
    return dict(index), rows


def _load_equity_minutes(path: Path | None) -> dict[tuple[str, str], dict]:
    if path is None:
        return {}
    out: dict[tuple[str, str], dict] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"minute_ts_utc", "symbol", "volume", "close"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"equity minutes missing required columns: {sorted(missing)}")
        for row_number, row in enumerate(reader, start=2):
            symbol = _clean(row.get("symbol")).upper()
            ts = _parse_ts(row.get("minute_ts_utc", ""))
            ts_key = ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            volume = _parse_float(row.get("volume"))
            close = _parse_float(row.get("close"))
            if not symbol or volume is None or volume < 0 or close is None or close <= 0:
                raise ValueError(f"equity row {row_number}: invalid symbol/volume/close")
            out[(symbol, ts_key)] = {
                **row,
                "symbol": symbol,
                "minute_ts_utc": ts_key,
                "_ts": ts,
                "_volume": volume,
                "_close": close,
                "_source_name": _clean(row.get("source_name")) or "historical_market_data",
            }
    return out


def _load_option_minutes(path: Path | None) -> dict[tuple[str, str], dict]:
    if path is None:
        return {}
    out: dict[tuple[str, str], dict] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"minute_ts_utc", "underlying_symbol", "contract_volume", "call_volume", "put_volume"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"option minutes missing required columns: {sorted(missing)}")
        for row_number, row in enumerate(reader, start=2):
            symbol = _clean(row.get("underlying_symbol")).upper()
            ts = _parse_ts(row.get("minute_ts_utc", ""))
            ts_key = ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            contract_volume = _parse_float(row.get("contract_volume"))
            call_volume = _parse_float(row.get("call_volume"))
            put_volume = _parse_float(row.get("put_volume"))
            if not symbol or any(x is None or x < 0 for x in (contract_volume, call_volume, put_volume)):
                raise ValueError(f"option row {row_number}: invalid symbol/volumes")
            out[(symbol, ts_key)] = {
                **row,
                "underlying_symbol": symbol,
                "minute_ts_utc": ts_key,
                "_ts": ts,
                "_contract_volume": float(contract_volume),
                "_call_volume": float(call_volume),
                "_put_volume": float(put_volume),
                "_source_name": _clean(row.get("source_name")) or "historical_market_data",
            }
    return out


def _window(points: deque[dict], now: datetime, minutes: int) -> list[dict]:
    cutoff = now - timedelta(minutes=minutes - 1)
    return [p for p in points if p["ts"] >= cutoff and p["ts"] <= now]


def _peak(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return max(vals) if vals else None


def _count_ge(values: Iterable[float | None], threshold: float) -> int:
    return sum(v is not None and v >= threshold for v in values)


def _slope(points: list[dict], field: str) -> float | None:
    usable = [(p["ts"], p.get(field)) for p in points if p.get(field) is not None]
    if len(usable) < 2:
        return None
    t0 = usable[0][0]
    xs = [(ts - t0).total_seconds() / 60.0 for ts, _ in usable]
    ys = [float(y) for _, y in usable]
    xbar = statistics.fmean(xs)
    ybar = statistics.fmean(ys)
    denom = sum((x - xbar) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / denom


def _lagged_return(price_points: deque[dict], now: datetime, close: float, minutes: int) -> float | None:
    target = now - timedelta(minutes=minutes)
    candidates = [p for p in price_points if p["ts"] <= target]
    if not candidates:
        return None
    prior = candidates[-1]
    # Refuse stale overnight/large-gap references. This is intraday behavior only.
    if prior["date"] != now.date() or abs((target - prior["ts"]).total_seconds()) > 5:
        return None
    prev_close = prior["close"]
    if prev_close <= 0:
        return None
    return close / prev_close - 1.0


def _realized_vol(price_points: deque[dict], now: datetime, minutes: int) -> float | None:
    cutoff = now - timedelta(minutes=minutes)
    pts = [p for p in price_points if p["ts"] >= cutoff and p["ts"] <= now and p["date"] == now.date()]
    if len(pts) < 3:
        return None
    rets: list[float] = []
    for a, b in zip(pts, pts[1:]):
        if a["close"] > 0 and b["close"] > 0:
            rets.append(math.log(b["close"] / a["close"]))
    if len(rets) < 2:
        return None
    return statistics.stdev(rets)


def _positive_l2(values: Iterable[float | None]) -> float | None:
    vals = [max(float(v), 0.0) for v in values if v is not None]
    if not vals:
        return None
    return math.sqrt(sum(v * v for v in vals))


def _mean(values: Iterable[float | None]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return statistics.fmean(vals) if vals else None


def build_features(
    baseline_index: dict[tuple[str, str, str], dict[str, dict]],
    equity_minutes: dict[tuple[str, str], dict] | None = None,
    option_minutes: dict[tuple[str, str], dict] | None = None,
) -> list[FeatureVector]:
    equity_minutes = equity_minutes or {}
    option_minutes = option_minutes or {}

    keys = {(symbol, ts) for _, symbol, ts in baseline_index.keys()}
    keys.update(equity_minutes.keys())
    keys.update(option_minutes.keys())

    ordered = sorted(keys, key=lambda x: (_parse_ts(x[1]), x[0]))

    sequence: dict[str, deque[dict]] = defaultdict(deque)
    prices: dict[str, deque[dict]] = defaultdict(deque)
    out: list[FeatureVector] = []

    for symbol, ts_key in ordered:
        now = _parse_ts(ts_key)
        eq_metrics = baseline_index.get(("equity", symbol, ts_key), {})
        op_metrics = baseline_index.get(("option", symbol, ts_key), {})
        eq_min = equity_minutes.get((symbol, ts_key))
        op_min = option_minutes.get((symbol, ts_key))

        # Baseline-score inputs. Robust z is preferred; standard z is fallback.
        eq_volume_z = _preferred_score(eq_metrics.get("volume"))
        eq_turnover_z = _preferred_score(eq_metrics.get("turnover"))
        eq_spread_z = _preferred_score(eq_metrics.get("mean_relative_spread"))
        if eq_spread_z is None:
            eq_spread_z = _preferred_score(eq_metrics.get("mean_quoted_spread"))
        op_volume_z = _preferred_score(op_metrics.get("contract_volume"))
        op_dollar_z = _preferred_score(op_metrics.get("dollar_volume"))

        relevant_metric_rows = [
            eq_metrics.get("volume"),
            eq_metrics.get("turnover"),
            eq_metrics.get("mean_relative_spread") or eq_metrics.get("mean_quoted_spread"),
            op_metrics.get("contract_volume"),
            op_metrics.get("dollar_volume"),
        ]
        feature_status, full_fraction = _status([r for r in relevant_metric_rows if r])

        eq_volume_ratio = _baseline_ratio(eq_metrics.get("volume"))
        op_volume_ratio = _baseline_ratio(op_metrics.get("contract_volume"))

        call_put: float | None = None
        contracts_per_100_shares: float | None = None
        if op_min:
            denom = op_min["_call_volume"] + op_min["_put_volume"]
            if denom > 0:
                call_put = (op_min["_call_volume"] - op_min["_put_volume"]) / denom
        if op_min and eq_min and eq_min["_volume"] > 0:
            contracts_per_100_shares = op_min["_contract_volume"] * 100.0 / eq_min["_volume"]

        # Reset rolling sequences at local/date boundary. baseline rows already carry local date.
        local_date = ""
        local_minute = ""
        for m in list(eq_metrics.values()) + list(op_metrics.values()):
            if m:
                local_date = local_date or _clean(m.get("local_date"))
                local_minute = local_minute or _clean(m.get("local_minute"))
        if not local_date:
            local_date = now.date().isoformat()
            local_minute = now.strftime("%H:%M")

        q = sequence[symbol]
        while q and q[0]["date"] != local_date:
            q.popleft()

        # Price behavior is strictly backward-looking. Add current close only after calculating returns.
        price_q = prices[symbol]
        while price_q and price_q[0]["date"] != now.date():
            price_q.popleft()
        close = eq_min["_close"] if eq_min else None
        ret_1 = _lagged_return(price_q, now, close, 1) if close is not None else None
        ret_5 = _lagged_return(price_q, now, close, 5) if close is not None else None
        ret_15 = _lagged_return(price_q, now, close, 15) if close is not None else None
        ret_30 = _lagged_return(price_q, now, close, 30) if close is not None else None

        current_point = {
            "ts": now,
            "date": local_date,
            "eq_volume_z": eq_volume_z,
            "eq_turnover_z": eq_turnover_z,
            "eq_spread_z": eq_spread_z,
            "op_volume_z": op_volume_z,
            "op_dollar_z": op_dollar_z,
        }
        q.append(current_point)
        while q and (now - q[0]["ts"]).total_seconds() > 29 * 60:
            q.popleft()

        w5 = _window(q, now, 5)
        w15 = _window(q, now, 15)
        w30 = _window(q, now, 30)

        peak5 = _peak(p.get("eq_volume_z") for p in w5)
        peak15 = _peak(p.get("eq_volume_z") for p in w15)
        peak30 = _peak(p.get("eq_volume_z") for p in w30)
        count5 = _count_ge((p.get("eq_volume_z") for p in w5), 2.0)
        count15 = _count_ge((p.get("eq_volume_z") for p in w15), 2.0)
        count30 = _count_ge((p.get("eq_volume_z") for p in w30), 2.0)
        slope5 = _slope(w5, "eq_volume_z")
        slope15 = _slope(w15, "eq_volume_z")
        slope30 = _slope(w30, "eq_volume_z")

        prior5 = [p.get("eq_volume_z") for p in w5[:-1]] if w5 else []
        prior5_mean = _mean(prior5)
        accel5 = None if eq_volume_z is None or prior5_mean is None else eq_volume_z - prior5_mean

        spread_count5 = _count_ge((p.get("eq_spread_z") for p in w5), 1.5)
        option_count5 = _count_ge((p.get("op_volume_z") for p in w5), 2.0)

        multi = _positive_l2((eq_volume_z, eq_turnover_z, eq_spread_z, op_volume_z, op_dollar_z))
        multi_count = _count_ge((eq_volume_z, eq_turnover_z, eq_spread_z, op_volume_z, op_dollar_z), 2.0)
        prior_multi = []
        for p in w5[:-1]:
            prior_multi.append(_positive_l2((p.get("eq_volume_z"), p.get("eq_turnover_z"), p.get("eq_spread_z"), p.get("op_volume_z"), p.get("op_dollar_z"))))
        prior_multi_mean = _mean(prior_multi)
        multi_change = None if multi is None or prior_multi_mean is None else multi - prior_multi_mean

        if close is not None:
            price_q.append({"ts": now, "date": now.date(), "close": close})
            while price_q and (now - price_q[0]["ts"]).total_seconds() > 31 * 60:
                price_q.popleft()
        rv5 = _realized_vol(price_q, now, 5) if close is not None else None
        rv15 = _realized_vol(price_q, now, 15) if close is not None else None
        rv30 = _realized_vol(price_q, now, 30) if close is not None else None

        sources = set()
        for m in list(eq_metrics.values()) + list(op_metrics.values()):
            if m and _clean(m.get("source_name")):
                sources.add(_clean(m.get("source_name")))
        if eq_min:
            sources.add(eq_min["_source_name"])
        if op_min:
            sources.add(op_min["_source_name"])

        out.append(
            FeatureVector(
                minute_ts_utc=ts_key,
                symbol=symbol,
                local_date=local_date,
                local_minute=local_minute,
                feature_status=feature_status,
                full_history_fraction=_fmt(full_fraction),
                equity_volume_z=_fmt(eq_volume_z),
                equity_turnover_z=_fmt(eq_turnover_z),
                equity_spread_z=_fmt(eq_spread_z),
                option_volume_z=_fmt(op_volume_z),
                option_dollar_volume_z=_fmt(op_dollar_z),
                equity_volume_ratio=_fmt(eq_volume_ratio),
                option_volume_ratio=_fmt(op_volume_ratio),
                call_put_imbalance=_fmt(call_put),
                option_contracts_per_100_equity_shares=_fmt(contracts_per_100_shares),
                return_1m=_fmt(ret_1),
                return_5m=_fmt(ret_5),
                return_15m=_fmt(ret_15),
                return_30m=_fmt(ret_30),
                realized_vol_5m=_fmt(rv5),
                realized_vol_15m=_fmt(rv15),
                realized_vol_30m=_fmt(rv30),
                equity_volume_peak_z_5m=_fmt(peak5),
                equity_volume_peak_z_15m=_fmt(peak15),
                equity_volume_peak_z_30m=_fmt(peak30),
                equity_volume_anomaly_count_5m=count5,
                equity_volume_anomaly_count_15m=count15,
                equity_volume_anomaly_count_30m=count30,
                equity_volume_z_slope_5m=_fmt(slope5),
                equity_volume_z_slope_15m=_fmt(slope15),
                equity_volume_z_slope_30m=_fmt(slope30),
                equity_volume_acceleration_5m=_fmt(accel5),
                spread_widen_count_5m=spread_count5,
                option_volume_anomaly_count_5m=option_count5,
                multivariate_l2=_fmt(multi),
                multivariate_2sigma_count=multi_count,
                multivariate_change_5m=_fmt(multi_change),
                source_names=";".join(sorted(sources)),
            )
        )

    return out


def write_records(records: Iterable[FeatureVector], path: Path) -> None:
    records = list(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text("", encoding="utf-8")
        return
    names = [f.name for f in fields(records[0])]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=names)
        writer.writeheader()
        for row in records:
            writer.writerow(asdict(row))


def build(
    *,
    baseline_metrics: Path,
    output_dir: Path,
    equity_minutes: Path | None = None,
    option_minutes: Path | None = None,
) -> dict:
    baseline_index, baseline_rows = load_baselines(baseline_metrics)
    equity = _load_equity_minutes(equity_minutes)
    options = _load_option_minutes(option_minutes)
    features = build_features(baseline_index, equity, options)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_records(features, output_dir / "feature_vectors.csv")

    status_counts: dict[str, int] = defaultdict(int)
    for row in features:
        status_counts[row.feature_status] += 1

    inputs = [
        {"path": str(baseline_metrics), "kind": "baseline_metrics", "sha256": _sha256(baseline_metrics)}
    ]
    if equity_minutes is not None:
        inputs.append({"path": str(equity_minutes), "kind": "equity_minutes", "sha256": _sha256(equity_minutes)})
    if option_minutes is not None:
        inputs.append({"path": str(option_minutes), "kind": "option_minutes", "sha256": _sha256(option_minutes)})

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Backward-looking surveillance feature construction from lawful historical market data; not a trading signal.",
        "lookahead_policy": (
            "Every feature uses only the current minute and information timestamped at or before it. "
            "Lagged returns and rolling anomaly features are backward-looking; no future price, public-announcement outcome, "
            "enforcement outcome, or unreleased content is accepted as an input."
        ),
        "score_policy": "Robust z-scores are preferred when present; conventional z-scores are fallback only.",
        "sequence_windows_minutes": list(WINDOWS),
        "anomaly_thresholds": {
            "volume_sigma": 2.0,
            "spread_widen_sigma": 1.5,
            "multivariate_component_sigma": 2.0,
        },
        "inputs": inputs,
        "outputs": {
            "feature_vector_rows": len(features),
            "feature_status_counts": dict(sorted(status_counts.items())),
        },
        "prohibited_outputs": ["BUY", "SELL", "bullish", "bearish", "expected_return", "target_price", "position_size", "order"],
    }
    (output_dir / "feature_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build point-in-time market-surveillance feature vectors.")
    parser.add_argument("--baseline-metrics", type=Path, required=True)
    parser.add_argument("--equity-minutes", type=Path)
    parser.add_argument("--option-minutes", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build(
        baseline_metrics=args.baseline_metrics,
        equity_minutes=args.equity_minutes,
        option_minutes=args.option_minutes,
        output_dir=args.output_dir,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
