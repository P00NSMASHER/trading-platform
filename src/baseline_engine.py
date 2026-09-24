from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "0.3.0"
DEFAULT_LOOKBACK_DAYS = 21
DEFAULT_MIN_HISTORY = 10

EQUITY_METRICS = (
    "trade_count",
    "volume",
    "dollar_volume",
    "mean_quoted_spread",
    "mean_relative_spread",
    "turnover",
)
OPTION_METRICS = (
    "trade_count",
    "contract_volume",
    "dollar_volume",
    "call_volume",
    "put_volume",
    "unique_contracts_traded",
    "mean_quoted_spread",
)


@dataclass(frozen=True)
class BaselineMetric:
    asset_class: str
    minute_ts_utc: str
    symbol: str
    local_date: str
    local_minute: str
    metric: str
    value: str
    history_n: int
    baseline_mean: str
    baseline_std: str
    baseline_median: str
    baseline_mad: str
    zscore: str
    robust_zscore: str
    baseline_ratio: str
    history_status: str
    source_name: str
    research_use_only: int = 1


@dataclass(frozen=True)
class SharesRecord:
    symbol: str
    effective_date: date
    shares_outstanding: float


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


def _parse_timestamp(value: str) -> datetime:
    value = _clean(value)
    if not value:
        raise ValueError("blank minute timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid minute timestamp {value!r}") from exc
    if dt.tzinfo is None:
        raise ValueError(f"minute timestamp must include timezone: {value!r}")
    return dt.astimezone(timezone.utc)


def _fmt(value: float | None, digits: int = 10) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return (f"{value:.{digits}f}").rstrip("0").rstrip(".")


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _sample_std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    return statistics.stdev(values)


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _mad(values: list[float], median: float | None = None) -> float | None:
    if not values:
        return None
    median = statistics.median(values) if median is None else median
    return statistics.median(abs(x - median) for x in values)


def _status(history_n: int, *, min_history: int, lookback_days: int) -> str:
    if history_n < min_history:
        return "insufficient"
    if history_n < lookback_days:
        return "partial"
    return "full"


def _stats(value: float, history: list[float], *, min_history: int, lookback_days: int) -> dict[str, str | int]:
    n = len(history)
    status = _status(n, min_history=min_history, lookback_days=lookback_days)
    mean = _mean(history)
    std = _sample_std(history)
    median = _median(history)
    mad = _mad(history, median)

    z: float | None = None
    robust_z: float | None = None
    ratio: float | None = None
    if n >= min_history:
        if std is not None and std > 0:
            z = (value - mean) / std  # type: ignore[operator]
        if mad is not None and mad > 0:
            # Standard consistency factor for a normal distribution.
            robust_z = 0.6744897501960817 * (value - median) / mad  # type: ignore[operator]
        if mean not in (None, 0):
            ratio = value / mean

    return {
        "history_n": n,
        "baseline_mean": _fmt(mean),
        "baseline_std": _fmt(std),
        "baseline_median": _fmt(median),
        "baseline_mad": _fmt(mad),
        "zscore": _fmt(z),
        "robust_zscore": _fmt(robust_z),
        "baseline_ratio": _fmt(ratio),
        "history_status": status,
    }


def load_shares(path: Path | None) -> dict[str, list[SharesRecord]]:
    if path is None:
        return {}
    out: dict[str, list[SharesRecord]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"symbol", "effective_date", "shares_outstanding"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"shares file missing required columns: {sorted(missing)}")
        for row_number, row in enumerate(reader, start=2):
            symbol = _clean(row.get("symbol")).upper()
            if not symbol:
                raise ValueError(f"shares row {row_number}: blank symbol")
            try:
                effective = date.fromisoformat(_clean(row.get("effective_date")))
            except Exception as exc:
                raise ValueError(f"shares row {row_number}: invalid effective_date") from exc
            shares = _parse_float(row.get("shares_outstanding"))
            if shares is None or shares <= 0:
                raise ValueError(f"shares row {row_number}: shares_outstanding must be > 0")
            out[symbol].append(SharesRecord(symbol, effective, shares))
    for rows in out.values():
        rows.sort(key=lambda x: x.effective_date)
    return dict(out)


def shares_as_of(shares: dict[str, list[SharesRecord]], symbol: str, local_date: date) -> float | None:
    rows = shares.get(symbol.upper(), [])
    answer: float | None = None
    for row in rows:
        if row.effective_date > local_date:
            break
        answer = row.shares_outstanding
    return answer


def _source_name(row: dict[str, str]) -> str:
    return _clean(row.get("source_name")) or "historical_market_data"


def _load_minutes(path: Path, *, asset_class: str, exchange_tz: str, shares: dict[str, list[SharesRecord]]) -> list[dict]:
    zone = ZoneInfo(exchange_tz)
    out: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if asset_class == "equity":
            required = {"minute_ts_utc", "symbol"}
        elif asset_class == "option":
            required = {"minute_ts_utc", "underlying_symbol"}
        else:
            raise ValueError("asset_class must be equity or option")
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{asset_class} minutes missing required columns: {sorted(missing)}")

        for row_number, row in enumerate(reader, start=2):
            ts_utc = _parse_timestamp(row.get("minute_ts_utc", ""))
            local = ts_utc.astimezone(zone)
            symbol = _clean(row.get("symbol") if asset_class == "equity" else row.get("underlying_symbol")).upper()
            if not symbol:
                raise ValueError(f"{asset_class} row {row_number}: blank symbol")
            values: dict[str, float] = {}
            metrics = EQUITY_METRICS if asset_class == "equity" else OPTION_METRICS
            for metric in metrics:
                if metric == "turnover":
                    continue
                value = _parse_float(row.get(metric))
                if value is not None:
                    if value < 0:
                        raise ValueError(f"{asset_class} row {row_number}: {metric} cannot be negative")
                    values[metric] = value

            if asset_class == "equity" and "volume" in values:
                shares_count = shares_as_of(shares, symbol, local.date())
                if shares_count is not None:
                    values["turnover"] = values["volume"] / shares_count

            out.append(
                {
                    "asset_class": asset_class,
                    "minute_ts_utc": ts_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                    "symbol": symbol,
                    "local_date": local.date(),
                    "local_minute": local.strftime("%H:%M"),
                    "values": values,
                    "source_name": _source_name(row),
                    "row_number": row_number,
                }
            )
    out.sort(key=lambda r: (r["minute_ts_utc"], r["symbol"]))
    return out


def build_baselines(
    rows: Iterable[dict],
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    min_history: int = DEFAULT_MIN_HISTORY,
) -> list[BaselineMetric]:
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    if min_history < 1 or min_history > lookback_days:
        raise ValueError("min_history must be in [1, lookback_days]")

    # Keep exactly one value per prior local trading date per symbol/minute/metric.
    history: dict[tuple[str, str, str, str], deque[tuple[date, float]]] = defaultdict(deque)
    out: list[BaselineMetric] = []

    for row in sorted(rows, key=lambda r: (r["minute_ts_utc"], r["asset_class"], r["symbol"])):
        asset_class = row["asset_class"]
        symbol = row["symbol"]
        local_date: date = row["local_date"]
        local_minute: str = row["local_minute"]
        source_name = row["source_name"]

        for metric, value in sorted(row["values"].items()):
            key = (asset_class, symbol, local_minute, metric)
            q = history[key]
            prior = [x for d, x in q if d < local_date]
            stats = _stats(value, prior, min_history=min_history, lookback_days=lookback_days)
            out.append(
                BaselineMetric(
                    asset_class=asset_class,
                    minute_ts_utc=row["minute_ts_utc"],
                    symbol=symbol,
                    local_date=local_date.isoformat(),
                    local_minute=local_minute,
                    metric=metric,
                    value=_fmt(value),
                    history_n=int(stats["history_n"]),
                    baseline_mean=str(stats["baseline_mean"]),
                    baseline_std=str(stats["baseline_std"]),
                    baseline_median=str(stats["baseline_median"]),
                    baseline_mad=str(stats["baseline_mad"]),
                    zscore=str(stats["zscore"]),
                    robust_zscore=str(stats["robust_zscore"]),
                    baseline_ratio=str(stats["baseline_ratio"]),
                    history_status=str(stats["history_status"]),
                    source_name=source_name,
                )
            )

            # Update only after scoring, so the current observation can never leak into its baseline.
            if q and q[-1][0] == local_date:
                q[-1] = (local_date, value)
            else:
                q.append((local_date, value))
            while len(q) > lookback_days:
                q.popleft()

    return out


def write_records(records: Iterable[BaselineMetric], path: Path) -> None:
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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build(
    *,
    equity_minutes: Path | None,
    option_minutes: Path | None,
    output_dir: Path,
    shares_file: Path | None = None,
    exchange_tz: str = "America/New_York",
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    min_history: int = DEFAULT_MIN_HISTORY,
) -> dict:
    if equity_minutes is None and option_minutes is None:
        raise ValueError("at least one minute file is required")

    shares = load_shares(shares_file)
    rows: list[dict] = []
    inputs: list[dict] = []
    if equity_minutes is not None:
        rows.extend(_load_minutes(equity_minutes, asset_class="equity", exchange_tz=exchange_tz, shares=shares))
        inputs.append({"path": str(equity_minutes), "kind": "equity_minutes", "sha256": _sha256(equity_minutes)})
    if option_minutes is not None:
        rows.extend(_load_minutes(option_minutes, asset_class="option", exchange_tz=exchange_tz, shares=shares))
        inputs.append({"path": str(option_minutes), "kind": "option_minutes", "sha256": _sha256(option_minutes)})
    if shares_file is not None:
        inputs.append({"path": str(shares_file), "kind": "shares_outstanding", "sha256": _sha256(shares_file)})

    baseline_rows = build_baselines(rows, lookback_days=lookback_days, min_history=min_history)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_records(baseline_rows, output_dir / "baseline_metrics.csv")

    counts = defaultdict(int)
    statuses = defaultdict(int)
    for row in baseline_rows:
        counts[f"{row.asset_class}:{row.metric}"] += 1
        statuses[row.history_status] += 1

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Point-in-time historical normalization for market-surveillance research; never a trading signal.",
        "lookback_trading_days": lookback_days,
        "minimum_history_observations": min_history,
        "exchange_timezone": exchange_tz,
        "lookahead_policy": (
            "Each observation is scored only against same-symbol, same-local-minute values from strictly earlier local dates. "
            "The current observation is appended only after scoring. Future shares-outstanding records are never used."
        ),
        "robust_score_policy": "robust_zscore = 0.6744897502 * (x - median) / MAD when MAD > 0.",
        "turnover_policy": (
            "Minute turnover is computed as minute share volume / latest shares_outstanding effective on or before the local date. "
            "Turnover is omitted when no point-in-time shares record exists."
        ),
        "inputs": inputs,
        "outputs": {
            "baseline_metric_rows": len(baseline_rows),
            "metric_row_counts": dict(sorted(counts.items())),
            "history_status_counts": dict(sorted(statuses.items())),
        },
        "prohibited_outputs": ["BUY", "SELL", "expected_return", "target_price", "position_size", "order"],
    }
    (output_dir / "baseline_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build point-in-time same-minute historical baselines.")
    parser.add_argument("--equity-minutes", type=Path)
    parser.add_argument("--option-minutes", type=Path)
    parser.add_argument("--shares-file", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--exchange-tz", default="America/New_York")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--min-history", type=int, default=DEFAULT_MIN_HISTORY)
    args = parser.parse_args()
    manifest = build(
        equity_minutes=args.equity_minutes,
        option_minutes=args.option_minutes,
        shares_file=args.shares_file,
        output_dir=args.output_dir,
        exchange_tz=args.exchange_tz,
        lookback_days=args.lookback_days,
        min_history=args.min_history,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
