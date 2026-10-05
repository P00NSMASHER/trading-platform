from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "1"
NY = ZoneInfo("America/New_York")

OUTPUT_FIELDS = (
    "event_date",
    "symbol",
    "effective_ts_utc",
    "market_cap",
    "price",
    "trailing_21d_vol",
    "normal_minute_volume",
    "normal_minute_turnover",
    "normal_relative_spread",
    "option_liquidity",
    "pre_event_return",
    "source_name",
    "research_use_only",
)


class G5DerivedMetadataError(ValueError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _float(value: str | None, *, label: str) -> float | None:
    raw = _clean(value)
    if not raw:
        return None
    try:
        out = float(raw)
    except ValueError as exc:
        raise G5DerivedMetadataError(f"{label} must be numeric") from exc
    if not math.isfinite(out):
        raise G5DerivedMetadataError(f"{label} must be finite")
    return out


def _parse_ts(value: str, *, label: str) -> datetime:
    raw = _clean(value)
    if not raw:
        raise G5DerivedMetadataError(f"{label} is blank")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G5DerivedMetadataError(f"{label} is not a valid ISO timestamp") from exc
    if dt.tzinfo is None:
        raise G5DerivedMetadataError(f"{label} must include timezone")
    return dt.astimezone(timezone.utc)


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fmt(value: float | None, digits: int = 12) -> str:
    if value is None or not math.isfinite(value):
        return ""
    return (f"{value:.{digits}f}").rstrip("0").rstrip(".")


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    return fields, rows


def load_candidates(path: Path) -> dict[tuple[str, str], datetime]:
    fields, rows = _read_csv(path)
    required = {"event_date", "candidate_symbol", "latest_acceptable_effective_ts_utc"}
    missing = required.difference(fields)
    if missing:
        raise G5DerivedMetadataError(
            f"candidate file missing columns: {sorted(missing)}"
        )
    out: dict[tuple[str, str], datetime] = {}
    for row_no, row in enumerate(rows, 2):
        event_date = _clean(row["event_date"])[:10]
        symbol = _clean(row["candidate_symbol"]).upper()
        cutoff = _parse_ts(
            row["latest_acceptable_effective_ts_utc"],
            label=f"candidate row {row_no} cutoff",
        )
        if not event_date or not symbol:
            raise G5DerivedMetadataError(
                f"candidate row {row_no}: event_date and candidate_symbol are required"
            )
        key = (event_date, symbol)
        if key in out:
            raise G5DerivedMetadataError(
                f"duplicate candidate symbol-date: {event_date}|{symbol}"
            )
        out[key] = cutoff
    return out


def _load_equity_minutes(path: Path) -> dict[str, list[dict]]:
    fields, rows = _read_csv(path)
    required = {"minute_ts_utc", "symbol", "close", "volume"}
    missing = required.difference(fields)
    if missing:
        raise G5DerivedMetadataError(
            f"equity minutes missing columns: {sorted(missing)}"
        )
    out: dict[str, list[dict]] = defaultdict(list)
    for row_no, row in enumerate(rows, 2):
        symbol = _clean(row["symbol"]).upper()
        ts = _parse_ts(row["minute_ts_utc"], label=f"equity row {row_no} minute_ts_utc")
        close = _float(row["close"], label=f"equity row {row_no} close")
        volume = _float(row["volume"], label=f"equity row {row_no} volume")
        if not symbol or close is None or close <= 0 or volume is None or volume < 0:
            raise G5DerivedMetadataError(f"equity row {row_no}: invalid symbol/close/volume")
        out[symbol].append(
            {
                "ts": ts,
                "local_date": ts.astimezone(NY).date(),
                "close": close,
                "volume": volume,
                "source_name": _clean(row.get("source_name")) or "historical_market_data",
            }
        )
    for values in out.values():
        values.sort(key=lambda row: row["ts"])
    return dict(out)


def _load_baselines(path: Path) -> dict[tuple[str, str, str, str], dict]:
    fields, rows = _read_csv(path)
    required = {
        "asset_class",
        "symbol",
        "local_date",
        "local_minute",
        "metric",
        "history_n",
        "baseline_mean",
        "history_status",
    }
    missing = required.difference(fields)
    if missing:
        raise G5DerivedMetadataError(
            f"baseline metrics missing columns: {sorted(missing)}"
        )
    out: dict[tuple[str, str, str, str], dict] = {}
    for row_no, row in enumerate(rows, 2):
        asset = _clean(row["asset_class"]).lower()
        symbol = _clean(row["symbol"]).upper()
        local_date = _clean(row["local_date"])[:10]
        local_minute = _clean(row["local_minute"])
        metric = _clean(row["metric"])
        if asset not in {"equity", "option"} or not symbol or not local_date or not local_minute or not metric:
            raise G5DerivedMetadataError(f"baseline row {row_no}: invalid identity fields")
        key = (asset, symbol, local_date, local_minute, metric)
        if key in out:
            raise G5DerivedMetadataError(f"duplicate baseline metric row: {key}")
        out[key] = row
    return out


def _load_shares(path: Path) -> dict[tuple[str, str], dict]:
    fields, rows = _read_csv(path)
    required = {
        "historical_symbol",
        "trade_date",
        "shares_outstanding",
        "resolution_status",
        "available_at",
    }
    missing = required.difference(fields)
    if missing:
        raise G5DerivedMetadataError(
            f"shares resolutions missing columns: {sorted(missing)}"
        )
    out: dict[tuple[str, str], dict] = {}
    for row_no, row in enumerate(rows, 2):
        symbol = _clean(row["historical_symbol"]).upper()
        trade_date = _clean(row["trade_date"])[:10]
        key = (symbol, trade_date)
        if key in out:
            raise G5DerivedMetadataError(f"duplicate shares resolution row: {key}")
        out[key] = row
    return out


def _baseline_mean(
    baselines: dict[tuple[str, str, str, str], dict],
    *,
    asset: str,
    symbol: str,
    event_date: str,
    local_minute: str,
    metric: str,
) -> float | None:
    row = baselines.get((asset, symbol, event_date, local_minute, metric))
    if row is None:
        return None
    status = _clean(row.get("history_status")).lower()
    if status not in {"partial", "full"}:
        return None
    history_n = int(float(_clean(row.get("history_n")) or "0"))
    if history_n < 10:
        return None
    return _float(row.get("baseline_mean"), label=f"baseline {asset}:{metric}")


def _last_completed_minute(rows: list[dict], cutoff: datetime) -> dict | None:
    eligible = [
        row for row in rows
        if row["ts"] + timedelta(minutes=1) <= cutoff
    ]
    return eligible[-1] if eligible else None


def _daily_closes_before(rows: list[dict], event_date: date) -> list[tuple[date, float]]:
    latest: dict[date, tuple[datetime, float]] = {}
    for row in rows:
        local_date = row["local_date"]
        if local_date >= event_date:
            continue
        prev = latest.get(local_date)
        if prev is None or row["ts"] > prev[0]:
            latest[local_date] = (row["ts"], row["close"])
    return [
        (day, latest[day][1])
        for day in sorted(latest)
    ]


def _trailing_21d_vol(rows: list[dict], event_date: date) -> float | None:
    closes = _daily_closes_before(rows, event_date)
    if len(closes) < 22:
        return None
    closes = closes[-22:]
    returns = [
        closes[i][1] / closes[i - 1][1] - 1.0
        for i in range(1, len(closes))
    ]
    if len(returns) < 21:
        return None
    return statistics.stdev(returns)


def _previous_close(rows: list[dict], event_date: date) -> float | None:
    closes = _daily_closes_before(rows, event_date)
    return closes[-1][1] if closes else None


def build(
    *,
    candidate_path: Path,
    equity_minutes_path: Path,
    baseline_metrics_path: Path,
    shares_resolutions_path: Path,
    output_path: Path,
    summary_path: Path,
    source_name: str = "g5-derived-real-market-metadata",
) -> dict:
    source_name = source_name.strip()
    if not source_name:
        raise G5DerivedMetadataError("source_name must be nonblank")

    candidates = load_candidates(candidate_path)
    equity = _load_equity_minutes(equity_minutes_path)
    baselines = _load_baselines(baseline_metrics_path)
    shares = _load_shares(shares_resolutions_path)

    output_rows: list[dict[str, str]] = []
    missing_counts: dict[str, int] = defaultdict(int)
    complete_count = 0

    for (event_date, symbol), cutoff in sorted(candidates.items()):
        local_cutoff = cutoff.astimezone(NY)
        local_minute = local_cutoff.strftime("%H:%M")
        event_day = date.fromisoformat(event_date)
        eq_rows = equity.get(symbol, [])
        last_minute = _last_completed_minute(eq_rows, cutoff)

        price = last_minute["close"] if last_minute else None
        effective = last_minute["ts"] if last_minute else None
        if price is None:
            missing_counts["price"] += 1

        trailing_vol = _trailing_21d_vol(eq_rows, event_day)
        if trailing_vol is None:
            missing_counts["trailing_21d_vol"] += 1

        normal_volume = _baseline_mean(
            baselines,
            asset="equity",
            symbol=symbol,
            event_date=event_date,
            local_minute=local_minute,
            metric="volume",
        )
        if normal_volume is None:
            missing_counts["normal_minute_volume"] += 1

        normal_turnover = _baseline_mean(
            baselines,
            asset="equity",
            symbol=symbol,
            event_date=event_date,
            local_minute=local_minute,
            metric="turnover",
        )
        if normal_turnover is None:
            missing_counts["normal_minute_turnover"] += 1

        normal_spread = _baseline_mean(
            baselines,
            asset="equity",
            symbol=symbol,
            event_date=event_date,
            local_minute=local_minute,
            metric="mean_relative_spread",
        )
        if normal_spread is None:
            missing_counts["normal_relative_spread"] += 1

        option_liquidity = _baseline_mean(
            baselines,
            asset="option",
            symbol=symbol,
            event_date=event_date,
            local_minute=local_minute,
            metric="contract_volume",
        )
        if option_liquidity is None:
            missing_counts["option_liquidity"] += 1

        prev_close = _previous_close(eq_rows, event_day)
        pre_event_return = (
            price / prev_close - 1.0
            if price is not None and prev_close is not None and prev_close > 0
            else None
        )
        if pre_event_return is None:
            missing_counts["pre_event_return"] += 1

        market_cap = None
        share_row = shares.get((symbol, event_date))
        if share_row is not None and _clean(share_row.get("resolution_status")) == "resolved":
            share_count = _float(
                share_row.get("shares_outstanding"),
                label=f"shares {symbol}|{event_date}",
            )
            raw_available = _clean(share_row.get("available_at"))
            if share_count is not None and share_count > 0 and raw_available:
                available = _parse_ts(
                    raw_available,
                    label=f"shares {symbol}|{event_date} available_at",
                )
                if available <= cutoff and price is not None:
                    market_cap = price * share_count
                    if effective is None or available > effective:
                        effective = available
        if market_cap is None:
            missing_counts["market_cap"] += 1

        values = {
            "market_cap": market_cap,
            "price": price,
            "trailing_21d_vol": trailing_vol,
            "normal_minute_volume": normal_volume,
            "normal_minute_turnover": normal_turnover,
            "normal_relative_spread": normal_spread,
            "option_liquidity": option_liquidity,
            "pre_event_return": pre_event_return,
        }
        if all(value is not None for value in values.values()):
            complete_count += 1

        output_rows.append(
            {
                "event_date": event_date,
                "symbol": symbol,
                "effective_ts_utc": _fmt_ts(effective) if effective else "",
                **{name: _fmt(value) for name, value in values.items()},
                "source_name": source_name,
                "research_use_only": "1",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(OUTPUT_FIELDS))
        writer.writeheader()
        writer.writerows(output_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Derive the market/G4-backed G5 control covariates from strictly pre-cutoff "
            "market history and point-in-time shares. Output is metadata input only and "
            "does not itself close G5."
        ),
        "research_use_only": True,
        "candidate_symbol_date_count": len(candidates),
        "output_row_count": len(output_rows),
        "complete_derived_row_count": complete_count,
        "missing_field_counts": dict(sorted(missing_counts.items())),
        "definitions": {
            "price": "close of the latest fully completed equity minute before cutoff",
            "market_cap": "price * point-in-time shares outstanding available by cutoff",
            "trailing_21d_vol": "sample standard deviation of 21 prior daily close-to-close returns; current event date excluded",
            "normal_minute_volume": "same-local-minute prior-history baseline mean equity volume",
            "normal_minute_turnover": "same-local-minute prior-history baseline mean equity turnover",
            "normal_relative_spread": "same-local-minute prior-history baseline mean relative quoted spread",
            "option_liquidity": "same-local-minute prior-history baseline mean option contract volume",
            "pre_event_return": "latest fully completed pre-cutoff minute close / prior trading-day close - 1",
        },
        "lookahead_policy": {
            "event_minute_must_be_fully_completed_before_use": True,
            "current_event_date_excluded_from_trailing_volatility": True,
            "shares_available_at_must_not_exceed_cutoff": True,
            "baseline_history_status_must_be_partial_or_full": True,
            "baseline_history_n_minimum": 10,
        },
        "inputs": {
            "candidates": {"path": str(candidate_path), "sha256": _sha256(candidate_path)},
            "equity_minutes": {"path": str(equity_minutes_path), "sha256": _sha256(equity_minutes_path)},
            "baseline_metrics": {"path": str(baseline_metrics_path), "sha256": _sha256(baseline_metrics_path)},
            "shares_resolutions": {"path": str(shares_resolutions_path), "sha256": _sha256(shares_resolutions_path)},
        },
        "output": {"path": str(output_path), "sha256": _sha256(output_path)},
        "g5_dates_resolved_change": 0,
        "eligible_g5_evidence": False,
        "release_claimed": False,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive strictly pre-cutoff market/G4 covariates for G5 controls."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--equity-minutes", type=Path, required=True)
    parser.add_argument("--baseline-metrics", type=Path, required=True)
    parser.add_argument("--shares-resolutions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--source-name", default="g5-derived-real-market-metadata")
    args = parser.parse_args()
    result = build(
        candidate_path=args.candidates,
        equity_minutes_path=args.equity_minutes,
        baseline_metrics_path=args.baseline_metrics,
        shares_resolutions_path=args.shares_resolutions,
        output_path=args.output,
        summary_path=args.summary,
        source_name=args.source_name,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
