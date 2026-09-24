from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matched_control_generator import (
    DEFAULT_NUMERIC_COVARIATES,
    balance_diagnostics,
    build,
    generate_matches,
    latest_metadata,
    load_events,
    load_features,
    load_metadata,
    validate_covariates,
)


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _event(event_id="E1", symbol="TRT", ts="2026-01-05 14:30:00"):
    return {
        "event_id": event_id,
        "permno": "1",
        "gvkey": "1",
        "historical_symbol": symbol,
        "first_documented_illicit_trade_ts": ts,
        "public_announcement_ts": "",
        "research_use_only": "1",
    }


def _feature(symbol: str, *, date="2026-01-05", minute="14:30", status="full"):
    return {
        "minute_ts_utc": f"{date}T19:{minute.split(':')[1]}:00.000Z",
        "symbol": symbol,
        "local_date": date,
        "local_minute": minute,
        "feature_status": status,
        "research_use_only": "1",
    }


def _meta(symbol: str, market_cap: float, *, effective="2026-01-05T18:00:00Z", sector="TECH", scheduled="1", price=100.0):
    return {
        "symbol": symbol,
        "effective_ts_utc": effective,
        "sector": sector,
        "index_bucket": "LARGE",
        "scheduled_event_flag": scheduled,
        "market_cap": str(market_cap),
        "price": str(price),
        "trailing_21d_vol": "0.02",
        "normal_minute_volume": "10000",
        "normal_minute_turnover": "0.001",
        "normal_relative_spread": "0.0008",
        "option_liquidity": "500",
        "institutional_ownership": "0.7",
        "analyst_coverage": "20",
        "borrow_cost": "0.01",
        "pre_event_return": "0.002",
        "source_name": "fixture_meta",
    }


def _paths(tmp_path: Path, events: list[dict], features: list[dict], metadata: list[dict]):
    ep = tmp_path / "events.csv"
    fp = tmp_path / "features.csv"
    mp = tmp_path / "metadata.csv"
    _write_csv(ep, list(events[0].keys()), events)
    _write_csv(fp, list(features[0].keys()), features)
    _write_csv(mp, list(metadata[0].keys()), metadata)
    return ep, fp, mp


def _load_all(ep: Path, fp: Path, mp: Path):
    cov = validate_covariates(DEFAULT_NUMERIC_COVARIATES)
    events = load_events(ep)
    exact, by_local = load_features(fp, min_status="partial")
    meta = load_metadata(mp, cov)
    return cov, events, exact, by_local, meta


def test_same_date_minute_and_nearest_controls_selected(tmp_path: Path):
    events = [_event()]
    features = [_feature(s) for s in ["TRT", "A", "B", "C", "D"]]
    metadata = [
        _meta("TRT", 1_000_000_000),
        _meta("A", 1_010_000_000),
        _meta("B", 990_000_000),
        _meta("C", 1_030_000_000),
        _meta("D", 3_000_000_000),
    ]
    ep, fp, mp = _paths(tmp_path, events, features, metadata)
    cov, ev, exact, by_local, meta = _load_all(ep, fp, mp)
    matches, summaries, _ = generate_matches(
        events=ev, features_by_local=by_local, features_exact=exact, metadata=meta,
        covariates=cov, controls_per_event=3, min_controls=3, max_component_z=5.0,
    )
    assert summaries[0].event_status == "matched"
    assert [m.control_symbol for m in matches] == ["A", "B", "C"]
    assert all(m.local_minute == "14:30" for m in matches)


def test_latest_metadata_is_strictly_point_in_time(tmp_path: Path):
    rows = [_meta("X", 100, effective="2026-01-05T18:00:00Z"), _meta("X", 999, effective="2026-01-05T20:00:00Z")]
    p = tmp_path / "m.csv"
    _write_csv(p, list(rows[0].keys()), rows)
    meta = load_metadata(p, validate_covariates(DEFAULT_NUMERIC_COVARIATES))
    asof = __import__("datetime").datetime.fromisoformat("2026-01-05T19:30:00+00:00")
    got = latest_metadata(meta, "X", asof)
    assert got is not None
    assert got["_values"]["market_cap"] == pytest.approx(100.0)


def test_future_only_metadata_makes_event_unmatchable(tmp_path: Path):
    events = [_event()]
    features = [_feature(s) for s in ["TRT", "A", "B", "C"]]
    metadata = [_meta("TRT", 1000, effective="2026-01-05T20:00:00Z")] + [_meta(s, 1000) for s in ["A", "B", "C"]]
    ep, fp, mp = _paths(tmp_path, events, features, metadata)
    cov, ev, exact, by_local, meta = _load_all(ep, fp, mp)
    matches, summaries, _ = generate_matches(events=ev, features_by_local=by_local, features_exact=exact, metadata=meta, covariates=cov)
    assert not matches
    assert summaries[0].event_status == "missing_treated_metadata"


def test_known_positive_on_same_date_is_excluded_as_control(tmp_path: Path):
    events = [_event("E1", "TRT"), _event("E2", "A", "2026-01-05 15:00:00")]
    features = [_feature(s) for s in ["TRT", "A", "B", "C", "D"]] + [_feature("A", minute="15:00")]
    metadata = [_meta(s, 1_000_000_000) for s in ["TRT", "A", "B", "C", "D"]]
    ep, fp, mp = _paths(tmp_path, events, features, metadata)
    cov, ev, exact, by_local, meta = _load_all(ep, fp, mp)
    matches, _, _ = generate_matches(events=ev, features_by_local=by_local, features_exact=exact, metadata=meta, covariates=cov, max_component_z=5.0)
    e1 = [m.control_symbol for m in matches if m.event_id == "E1"]
    assert "A" not in e1


def test_same_sector_and_scheduled_event_filters(tmp_path: Path):
    events = [_event()]
    features = [_feature(s) for s in ["TRT", "A", "B", "C", "OTHER", "UNSCHED"]]
    metadata = [_meta("TRT", 1000)] + [_meta(s, 1000) for s in ["A", "B", "C"]]
    metadata += [_meta("OTHER", 1000, sector="HEALTH"), _meta("UNSCHED", 1000, scheduled="0")]
    ep, fp, mp = _paths(tmp_path, events, features, metadata)
    cov, ev, exact, by_local, meta = _load_all(ep, fp, mp)
    matches, _, _ = generate_matches(events=ev, features_by_local=by_local, features_exact=exact, metadata=meta, covariates=cov, max_component_z=5.0)
    symbols = {m.control_symbol for m in matches}
    assert symbols == {"A", "B", "C"}


def test_insufficient_pool_does_not_emit_partial_fake_match(tmp_path: Path):
    events = [_event()]
    features = [_feature(s) for s in ["TRT", "A", "B"]]
    metadata = [_meta(s, 1000) for s in ["TRT", "A", "B"]]
    ep, fp, mp = _paths(tmp_path, events, features, metadata)
    cov, ev, exact, by_local, meta = _load_all(ep, fp, mp)
    matches, summaries, _ = generate_matches(events=ev, features_by_local=by_local, features_exact=exact, metadata=meta, covariates=cov, controls_per_event=3, min_controls=3, max_component_z=5.0)
    assert matches == []
    assert summaries[0].event_status == "insufficient_controls"


def test_forbidden_future_covariates_are_rejected():
    with pytest.raises(ValueError):
        validate_covariates(("earnings_surprise",))
    with pytest.raises(ValueError):
        validate_covariates(("expected_return",))


def test_step4_anomaly_values_are_not_needed_for_matching(tmp_path: Path):
    events = [_event()]
    features = [_feature(s) for s in ["TRT", "A", "B", "C"]]
    # Deliberately only required feature columns: matching must not inspect anomaly values.
    metadata = [_meta(s, 1000) for s in ["TRT", "A", "B", "C"]]
    ep, fp, mp = _paths(tmp_path, events, features, metadata)
    manifest = build(events_path=ep, feature_vectors=fp, metadata_path=mp, output_dir=tmp_path / "out", max_component_z=5.0)
    assert manifest["outputs"]["matched_control_rows"] == 3
    assert "never used in the match distance" in manifest["lookahead_policy"]


def test_exclusion_window_removes_candidate(tmp_path: Path):
    events = [_event()]
    features = [_feature(s) for s in ["TRT", "A", "B", "C", "D"]]
    metadata = [_meta(s, 1000) for s in ["TRT", "A", "B", "C", "D"]]
    ep, fp, mp = _paths(tmp_path, events, features, metadata)
    xp = tmp_path / "exclude.csv"
    _write_csv(xp, ["symbol", "start_ts_utc", "end_ts_utc", "reason"], [{
        "symbol": "A", "start_ts_utc": "2026-01-05T19:00:00Z", "end_ts_utc": "2026-01-05T20:00:00Z", "reason": "unlabeled-risk-window"
    }])
    manifest = build(events_path=ep, feature_vectors=fp, metadata_path=mp, output_dir=tmp_path / "out", exclusions_path=xp, max_component_z=5.0)
    rows = list(csv.DictReader((tmp_path / "out/matched_controls.csv").open()))
    assert "A" not in {r["control_symbol"] for r in rows}
    assert manifest["outputs"]["matched_control_rows"] == 3


def test_balance_diagnostics_are_emitted(tmp_path: Path):
    events = [_event()]
    features = [_feature(s) for s in ["TRT", "A", "B", "C", "D", "E"]]
    metadata = [
        _meta("TRT", 1_000_000),
        _meta("A", 1_010_000), _meta("B", 990_000), _meta("C", 1_020_000),
        _meta("D", 5_000_000), _meta("E", 8_000_000),
    ]
    ep, fp, mp = _paths(tmp_path, events, features, metadata)
    build(events_path=ep, feature_vectors=fp, metadata_path=mp, output_dir=tmp_path / "out", max_component_z=10.0)
    rows = list(csv.DictReader((tmp_path / "out/match_balance.csv").open()))
    mcap = next(r for r in rows if r["covariate"] == "market_cap")
    assert mcap["smd_before"] != ""
    assert mcap["smd_after"] != ""
    assert abs(float(mcap["smd_after"])) <= abs(float(mcap["smd_before"]))


def test_manifest_and_output_are_surveillance_only(tmp_path: Path):
    events = [_event()]
    features = [_feature(s) for s in ["TRT", "A", "B", "C"]]
    metadata = [_meta(s, 1000) for s in ["TRT", "A", "B", "C"]]
    ep, fp, mp = _paths(tmp_path, events, features, metadata)
    manifest = build(events_path=ep, feature_vectors=fp, metadata_path=mp, output_dir=tmp_path / "out", max_component_z=5.0)
    saved = json.loads((tmp_path / "out/match_manifest.json").read_text())
    assert "BUY" in saved["prohibited_outputs"]
    header = (tmp_path / "out/matched_controls.csv").read_text().splitlines()[0]
    for prohibited in ["expected_return", "target_price", "position_size", "order"]:
        assert prohibited not in header
    assert manifest["matching_policy"]["known_positive_event_controls_excluded"] is True
