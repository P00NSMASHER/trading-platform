from __future__ import annotations

import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_derived_market_metadata_adapter as adapter


def _write_candidates(tmp_path: Path) -> Path:
    p = tmp_path / "candidates.csv"
    p.write_text(
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc\n"
        "2015-02-17,C1,2015-02-17T19:19:00Z\n",
        encoding="utf-8",
    )
    return p


def _write_equity(tmp_path: Path, *, include_history: bool = True) -> Path:
    p = tmp_path / "equity.csv"
    rows = [
        "minute_ts_utc,symbol,volume,close,source_name",
    ]
    if include_history:
        start = date(2015, 1, 26)
        for i in range(22):
            d = start + timedelta(days=i)
            close = 88 + i
            rows.append(
                f"{d.isoformat()}T21:00:00Z,C1,1000,{close},test-market"
            )
    rows.extend(
        [
            "2015-02-17T19:18:00Z,C1,2000,110,test-market",
            "2015-02-17T19:19:00Z,C1,9999,999,test-market",
        ]
    )
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return p


def _write_baselines(tmp_path: Path, *, status: str = "full") -> Path:
    p = tmp_path / "baselines.csv"
    p.write_text(
        "asset_class,minute_ts_utc,symbol,local_date,local_minute,metric,value,history_n,baseline_mean,history_status,source_name\n"
        f"equity,2015-02-17T19:19:00Z,C1,2015-02-17,14:19,volume,2000,21,1000,{status},test-baseline\n"
        f"equity,2015-02-17T19:19:00Z,C1,2015-02-17,14:19,turnover,0.00002,21,0.00001,{status},test-baseline\n"
        f"equity,2015-02-17T19:19:00Z,C1,2015-02-17,14:19,mean_relative_spread,0.002,21,0.001,{status},test-baseline\n"
        f"option,2015-02-17T19:19:00Z,C1,2015-02-17,14:19,contract_volume,700,21,500,{status},test-baseline\n",
        encoding="utf-8",
    )
    return p


def _write_shares(tmp_path: Path, *, available_at: str = "2015-02-10T00:00:00Z") -> Path:
    p = tmp_path / "shares.csv"
    p.write_text(
        "historical_symbol,trade_date,shares_outstanding,resolution_status,available_at\n"
        f"C1,2015-02-17,100000000,resolved,{available_at}\n",
        encoding="utf-8",
    )
    return p


def _build(
    tmp_path: Path,
    *,
    include_history: bool = True,
    baseline_status: str = "full",
    shares_available_at: str = "2015-02-10T00:00:00Z",
):
    output = tmp_path / "derived.csv"
    summary = tmp_path / "summary.json"
    result = adapter.build(
        candidate_path=_write_candidates(tmp_path),
        equity_minutes_path=_write_equity(tmp_path, include_history=include_history),
        baseline_metrics_path=_write_baselines(tmp_path, status=baseline_status),
        shares_resolutions_path=_write_shares(tmp_path, available_at=shares_available_at),
        output_path=output,
        summary_path=summary,
        source_name="test-derived",
    )
    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    saved = json.loads(summary.read_text(encoding="utf-8"))
    return result, rows, saved


def test_build_derives_complete_pre_cutoff_row(tmp_path: Path):
    result, rows, saved = _build(tmp_path)

    assert len(rows) == 1
    row = rows[0]
    assert row["event_date"] == "2015-02-17"
    assert row["symbol"] == "C1"
    assert row["effective_ts_utc"] == "2015-02-17T19:18:00Z"
    assert row["price"] == "110"
    assert row["market_cap"] == "11000000000"
    assert row["normal_minute_volume"] == "1000"
    assert row["normal_minute_turnover"] == "0.00001"
    assert row["normal_relative_spread"] == "0.001"
    assert row["option_liquidity"] == "500"
    assert row["trailing_21d_vol"] != ""
    assert row["pre_event_return"] != ""
    assert row["source_name"] == "test-derived"
    assert row["research_use_only"] == "1"

    assert result["complete_derived_row_count"] == 1
    assert result["missing_field_counts"] == {}
    assert saved["definitions"]["option_liquidity"].startswith("same-local-minute")
    assert saved["g5_dates_resolved_change"] == 0
    assert saved["eligible_g5_evidence"] is False
    assert saved["release_claimed"] is False


def test_current_event_minute_is_not_used_before_cutoff(tmp_path: Path):
    _result, rows, _saved = _build(tmp_path)

    assert rows[0]["price"] == "110"
    assert rows[0]["effective_ts_utc"] == "2015-02-17T19:18:00Z"


def test_future_shares_are_not_used_for_market_cap(tmp_path: Path):
    result, rows, _saved = _build(
        tmp_path,
        shares_available_at="2015-02-17T20:00:00Z",
    )

    assert rows[0]["market_cap"] == ""
    assert result["complete_derived_row_count"] == 0
    assert result["missing_field_counts"]["market_cap"] == 1


def test_insufficient_baseline_history_leaves_normal_fields_blank(tmp_path: Path):
    result, rows, _saved = _build(
        tmp_path,
        baseline_status="insufficient",
    )

    row = rows[0]
    assert row["normal_minute_volume"] == ""
    assert row["normal_minute_turnover"] == ""
    assert row["normal_relative_spread"] == ""
    assert row["option_liquidity"] == ""
    assert result["missing_field_counts"]["normal_minute_volume"] == 1
    assert result["missing_field_counts"]["normal_minute_turnover"] == 1
    assert result["missing_field_counts"]["normal_relative_spread"] == 1
    assert result["missing_field_counts"]["option_liquidity"] == 1


def test_less_than_22_prior_closes_does_not_invent_trailing_volatility(tmp_path: Path):
    result, rows, _saved = _build(
        tmp_path,
        include_history=False,
    )

    assert rows[0]["trailing_21d_vol"] == ""
    assert rows[0]["pre_event_return"] == ""
    assert result["missing_field_counts"]["trailing_21d_vol"] == 1
    assert result["missing_field_counts"]["pre_event_return"] == 1
