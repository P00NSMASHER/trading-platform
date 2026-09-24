from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

SCHEMA_VERSION = "0.16.0"
NY = ZoneInfo("America/New_York")
UTC = timezone.utc
CALENDAR_NAME = "XNYS"
DEFAULT_LOOKBACK_SESSIONS = 21
DEFAULT_PRE_MINUTES = 30
DEFAULT_POST_MINUTES = 30
DEFAULT_POSTHOC_EXTENSION_MINUTES = 5

PROHIBITED_OUTPUTS = [
    "BUY",
    "SELL",
    "expected_return",
    "target_price",
    "position_size",
    "order",
    "execution_instruction",
]


@dataclass(frozen=True)
class EventCoveragePlan:
    event_id: str
    permno: str
    gvkey: str
    historical_symbol: str
    first_trade_ts_local: str
    first_trade_ts_utc: str
    event_trade_date: str
    event_session_open_local: str
    event_session_close_local: str
    event_window_start_local: str
    event_window_end_local: str
    event_window_minute_count: int
    posthoc_quote_end_local: str
    posthoc_5m_incomplete_panel_minutes: int
    baseline_required_sessions: int
    baseline_scan_sessions: int
    baseline_first_date: str
    baseline_last_date: str
    baseline_dates: str
    announcement_timestamp_status: str
    itch_requirement: str
    options_requirement: str
    shares_outstanding_requirement: str
    matched_control_status: str
    research_use_only: int = 1


@dataclass(frozen=True)
class SymbolDateRequirement:
    historical_symbol: str
    trade_date: str
    roles: str
    event_ids: str
    interval_count: int
    window_intervals_local: str
    requested_regular_session_minutes: int
    quote_extension_intervals_local: str
    requested_quote_minutes: int
    require_equity_trades: int
    require_equity_quotes: int
    require_option_trades_full_replication: int
    require_option_quotes_full_replication: int
    itch_requirement: str
    shares_outstanding_required: int
    research_use_only: int = 1


@dataclass(frozen=True)
class SourceDateRequirement:
    source_family: str
    record_kind: str
    trade_date: str
    requirement: str
    unique_symbol_count: int
    historical_symbols: str
    symbol_date_pair_count: int
    acquisition_scope: str
    blocking_metadata: str
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fmt_local(dt: datetime) -> str:
    return dt.astimezone(NY).isoformat(timespec="seconds")


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_first_trade(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(NY)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: Iterable[object]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    first = rows[0]
    dict_rows = [asdict(r) if hasattr(r, "__dataclass_fields__") else dict(r) for r in rows]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(dict_rows[0].keys()))
        w.writeheader()
        w.writerows(dict_rows)


def _calendar(start: date, end: date):
    cal = xcals.get_calendar(CALENDAR_NAME)
    # Load extra history so the earliest event always has enough eligible baselines.
    sessions = cal.sessions_in_range(start - timedelta(days=90), end + timedelta(days=2))
    return cal, list(sessions)


def _session_date(label) -> date:
    return label.date()


def _session_bounds(cal, session_label) -> tuple[datetime, datetime]:
    open_ts = cal.session_open(session_label).to_pydatetime().astimezone(NY)
    close_ts = cal.session_close(session_label).to_pydatetime().astimezone(NY)
    return open_ts, close_ts


def _clip_window(anchor: datetime, session_open: datetime, session_close: datetime,
                 pre_minutes: int, post_minutes: int) -> tuple[datetime, datetime]:
    start = max(session_open, anchor - timedelta(minutes=pre_minutes))
    end = min(session_close, anchor + timedelta(minutes=post_minutes))
    start = start.replace(second=0, microsecond=0)
    # Keep the anchor minute even when the exact trade occurs seconds into it.
    end = end.replace(second=0, microsecond=0)
    if end < start:
        raise ValueError("event window collapsed after session clipping")
    return start, end


def _inclusive_minutes(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60) + 1


def _eligible_baselines(cal, sessions, event_label, window_start: datetime, window_end: datetime,
                        n: int) -> tuple[list[date], int]:
    idx = sessions.index(event_label)
    selected: list[date] = []
    scanned = 0
    target_start_clock = window_start.timetz().replace(tzinfo=None)
    target_end_clock = window_end.timetz().replace(tzinfo=None)
    for label in reversed(sessions[:idx]):
        scanned += 1
        o, c = _session_bounds(cal, label)
        if o.timetz().replace(tzinfo=None) <= target_start_clock and c.timetz().replace(tzinfo=None) >= target_end_clock:
            selected.append(_session_date(label))
            if len(selected) == n:
                break
    if len(selected) != n:
        raise ValueError(f"unable to locate {n} eligible prior sessions for {_session_date(event_label)}")
    selected.reverse()
    return selected, scanned


def _find_session_label(sessions, d: date):
    for label in sessions:
        if _session_date(label) == d:
            return label
    raise ValueError(f"event date {d} is not an {CALENDAR_NAME} session")


def _minutes_lacking_posthoc(start: datetime, end: datetime, session_close: datetime, extension: int) -> int:
    count = 0
    cur = start
    while cur <= end:
        if cur + timedelta(minutes=extension) > session_close:
            count += 1
        cur += timedelta(minutes=1)
    return count


def build_event_plans(events_path: Path, *, lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
                      pre_minutes: int = DEFAULT_PRE_MINUTES, post_minutes: int = DEFAULT_POST_MINUTES,
                      posthoc_extension_minutes: int = DEFAULT_POSTHOC_EXTENSION_MINUTES) -> tuple[list[EventCoveragePlan], dict]:
    rows = _read_csv(events_path)
    if not rows:
        raise ValueError("events file is empty")
    if lookback_sessions < 1 or pre_minutes < 0 or post_minutes < 0 or posthoc_extension_minutes < 0:
        raise ValueError("invalid planner window settings")
    anchors = [_parse_first_trade(r["first_documented_illicit_trade_ts"]) for r in rows]
    cal, sessions = _calendar(min(x.date() for x in anchors), max(x.date() for x in anchors))
    plans: list[EventCoveragePlan] = []
    early_close_skips = 0
    for r, anchor in zip(rows, anchors):
        if str(r.get("research_use_only", "1")) != "1":
            raise ValueError(f"event {r.get('event_id')} is not research_use_only")
        label = _find_session_label(sessions, anchor.date())
        session_open, session_close = _session_bounds(cal, label)
        if not (session_open <= anchor <= session_close):
            raise ValueError(f"event {r['event_id']} first trade is outside regular session")
        wstart, wend = _clip_window(anchor, session_open, session_close, pre_minutes, post_minutes)
        baseline_dates, scanned = _eligible_baselines(cal, sessions, label, wstart, wend, lookback_sessions)
        early_close_skips += scanned - lookback_sessions
        quote_end = min(session_close, wend + timedelta(minutes=posthoc_extension_minutes))
        plans.append(EventCoveragePlan(
            event_id=r["event_id"], permno=r.get("permno", ""), gvkey=r.get("gvkey", ""),
            historical_symbol=r["historical_symbol"], first_trade_ts_local=_fmt_local(anchor),
            first_trade_ts_utc=_fmt_utc(anchor), event_trade_date=anchor.date().isoformat(),
            event_session_open_local=_fmt_local(session_open), event_session_close_local=_fmt_local(session_close),
            event_window_start_local=_fmt_local(wstart), event_window_end_local=_fmt_local(wend),
            event_window_minute_count=_inclusive_minutes(wstart, wend),
            posthoc_quote_end_local=_fmt_local(quote_end),
            posthoc_5m_incomplete_panel_minutes=_minutes_lacking_posthoc(wstart, wend, session_close, posthoc_extension_minutes),
            baseline_required_sessions=lookback_sessions, baseline_scan_sessions=scanned,
            baseline_first_date=baseline_dates[0].isoformat(), baseline_last_date=baseline_dates[-1].isoformat(),
            baseline_dates=";".join(d.isoformat() for d in baseline_dates),
            announcement_timestamp_status=("available" if r.get("public_announcement_ts", "").strip() else "missing_authorized_exact_timestamp"),
            itch_requirement="conditional_on_point_in_time_nasdaq_listing",
            options_requirement="required_for_full_replication_optional_for_equity_only_core",
            shares_outstanding_requirement="point_in_time_series_required_for_turnover",
            matched_control_status="pending_real_same_day_candidate_universe",
        ))
    meta = {
        "calendar": CALENDAR_NAME,
        "calendar_library": "exchange_calendars",
        "calendar_library_version": xcals.__version__,
        "early_close_or_short_session_skips": early_close_skips,
    }
    return plans, meta


def _parse_local_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(NY)


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    intervals = sorted(intervals)
    out = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= out[-1][1] + timedelta(minutes=1):
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _interval_text(intervals: list[tuple[datetime, datetime]]) -> str:
    return ";".join(f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}" for s, e in intervals)


def _interval_minutes(intervals: list[tuple[datetime, datetime]]) -> int:
    return sum(_inclusive_minutes(s, e) for s, e in intervals)


def build_symbol_date_requirements(plans: list[EventCoveragePlan], *, posthoc_extension_minutes: int = DEFAULT_POSTHOC_EXTENSION_MINUTES) -> list[SymbolDateRequirement]:
    bucket: dict[tuple[str, str], dict] = defaultdict(lambda: {"roles": set(), "event_ids": set(), "intervals": [], "quote_intervals": []})
    cal = xcals.get_calendar(CALENDAR_NAME)
    for p in plans:
        wstart = _parse_local_iso(p.event_window_start_local)
        wend = _parse_local_iso(p.event_window_end_local)
        key = (p.historical_symbol, p.event_trade_date)
        bucket[key]["roles"].add("event")
        bucket[key]["event_ids"].add(p.event_id)
        bucket[key]["intervals"].append((wstart, wend))
        bucket[key]["quote_intervals"].append((wstart, _parse_local_iso(p.posthoc_quote_end_local)))
        for dstr in p.baseline_dates.split(";"):
            d = date.fromisoformat(dstr)
            label = cal.date_to_session(dstr, direction="none")
            o, c = _session_bounds(cal, label)
            bs = datetime.combine(d, wstart.timetz().replace(tzinfo=None), NY)
            be = datetime.combine(d, wend.timetz().replace(tzinfo=None), NY)
            # eligibility selection guarantees be <= close for the core panel.
            bqe = min(c, be + timedelta(minutes=posthoc_extension_minutes))
            k = (p.historical_symbol, dstr)
            bucket[k]["roles"].add("baseline")
            bucket[k]["event_ids"].add(p.event_id)
            bucket[k]["intervals"].append((bs, be))
            bucket[k]["quote_intervals"].append((bs, bqe))
    out: list[SymbolDateRequirement] = []
    for (symbol, dstr), v in sorted(bucket.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        intervals = _merge_intervals(v["intervals"])
        qintervals = _merge_intervals(v["quote_intervals"])
        out.append(SymbolDateRequirement(
            historical_symbol=symbol, trade_date=dstr, roles=";".join(sorted(v["roles"])),
            event_ids=";".join(sorted(v["event_ids"])), interval_count=len(intervals),
            window_intervals_local=_interval_text(intervals), requested_regular_session_minutes=_interval_minutes(intervals),
            quote_extension_intervals_local=_interval_text(qintervals), requested_quote_minutes=_interval_minutes(qintervals),
            require_equity_trades=1, require_equity_quotes=1,
            require_option_trades_full_replication=1, require_option_quotes_full_replication=1,
            itch_requirement="conditional_on_point_in_time_nasdaq_listing",
            shares_outstanding_required=1,
        ))
    return out


def build_source_date_requirements(symbol_dates: list[SymbolDateRequirement]) -> list[SourceDateRequirement]:
    by_date: dict[str, list[SymbolDateRequirement]] = defaultdict(list)
    for r in symbol_dates:
        by_date[r.trade_date].append(r)
    out: list[SourceDateRequirement] = []
    fixed = [
        ("nyse_daily_taq", "equity_trade", "required_core", "date_file_or_symbol_filtered_export", ""),
        ("nyse_daily_taq", "equity_quote", "required_core", "date_file_or_symbol_filtered_export", ""),
        ("cboe_option_trades", "option_trade", "required_full_replication", "date_file_or_underlying_filtered_export", ""),
        ("cboe_option_quotes", "option_quote", "required_full_replication", "date_file_or_underlying_filtered_export", ""),
        ("nasdaq_itch_5_0_decoded", "itch_decoded", "conditional", "decoded_date_file_filtered_to_required_symbols", "point_in_time_primary_listing_exchange"),
    ]
    for dstr, rows in sorted(by_date.items()):
        symbols = sorted({r.historical_symbol for r in rows})
        for family, kind, req, scope, blocking in fixed:
            out.append(SourceDateRequirement(
                source_family=family, record_kind=kind, trade_date=dstr, requirement=req,
                unique_symbol_count=len(symbols), historical_symbols=";".join(symbols),
                symbol_date_pair_count=len(rows), acquisition_scope=scope, blocking_metadata=blocking,
            ))
    return out


def build_announcement_requirements(events_path: Path) -> list[dict[str, str]]:
    rows = _read_csv(events_path)
    out = []
    for r in rows:
        out.append({
            "event_id": r["event_id"], "historical_symbol": r["historical_symbol"],
            "event_trade_date": r["first_documented_illicit_trade_ts"][:10],
            "current_public_announcement_ts": r.get("public_announcement_ts", ""),
            "requirement": "exact_point_in_time_public_release_timestamp",
            "acceptable_source": "licensed_IBES_or_independently_verified_SEC_newswire_timestamp",
            "status": "ready" if r.get("public_announcement_ts", "").strip() else "missing",
            "research_use_only": "1",
        })
    return out


def audit_contract(contract_path: Path | None, source_dates: list[SourceDateRequirement]) -> dict:
    required = {(r.source_family, r.record_kind, r.trade_date) for r in source_dates if r.requirement != "conditional"}
    conditional = {(r.source_family, r.record_kind, r.trade_date) for r in source_dates if r.requirement == "conditional"}
    covered_real: set[tuple[str, str, str]] = set()
    covered_synthetic: set[tuple[str, str, str]] = set()
    contract_sha = ""
    contract_source_count = 0
    issues: list[str] = []
    if contract_path is not None:
        contract_sha = _sha256(contract_path)
        obj = json.loads(contract_path.read_text(encoding="utf-8"))
        for s in obj.get("sources", []):
            contract_source_count += 1
            key = (str(s.get("source_family", "")), str(s.get("record_kind", "")), str(s.get("trade_date", "")))
            cls = str(s.get("data_classification", ""))
            path = Path(str(s.get("path", "")))
            if not path.is_absolute():
                path = (contract_path.parent / path).resolve()
            if not path.exists():
                issues.append(f"missing_path:{s.get('source_id','')}:{path}")
                continue
            if bool(s.get("authorized")) and cls == "authorized_historical_market_data":
                covered_real.add(key)
            elif cls == "synthetic_fixture":
                covered_synthetic.add(key)
    missing_required = sorted(required - covered_real)
    return {
        "contract_path": str(contract_path) if contract_path else "",
        "contract_sha256": contract_sha,
        "contract_source_count": contract_source_count,
        "required_source_date_rows": len(required),
        "conditional_source_date_rows": len(conditional),
        "real_authorized_required_rows_covered": len(required & covered_real),
        "synthetic_rows_matching_required_keys": len(required & covered_synthetic),
        "missing_real_authorized_required_rows": len(missing_required),
        "missing_required_preview": ["|".join(x) for x in missing_required[:25]],
        "issues": issues,
        "ready_for_real_backfill": len(missing_required) == 0 and not issues,
    }


def build_unresolved_gates(plans: list[EventCoveragePlan], symbol_dates: list[SymbolDateRequirement],
                           source_dates: list[SourceDateRequirement], contract_audit: dict) -> list[dict[str, str]]:
    unique_event_dates = sorted({p.event_trade_date for p in plans})
    return [
        {
            "gate_id": "G1_ANNOUNCEMENT_TIMES", "status": "BLOCKING",
            "required_rows": str(sum(p.announcement_timestamp_status != "available" for p in plans)),
            "requirement": "Exact public announcement timestamp for each adjudicated event",
            "resolution": "Join licensed I/B/E/S or independently verified SEC/newswire publication timestamp",
        },
        {
            "gate_id": "G2_REAL_MARKET_DATA", "status": "BLOCKING" if not contract_audit["ready_for_real_backfill"] else "READY",
            "required_rows": str(contract_audit["missing_real_authorized_required_rows"]),
            "requirement": "Authorized non-synthetic TAQ equity trades/quotes plus full-replication options source-date coverage",
            "resolution": "Populate Step-15 source contract with authorized paths and license references",
        },
        {
            "gate_id": "G3_PRIMARY_LISTING_HISTORY", "status": "BLOCKING_FOR_ITCH",
            "required_rows": str(len(plans)),
            "requirement": "Point-in-time primary listing exchange as of each event date",
            "resolution": "Resolve historical exchange to decide which symbol-dates require Nasdaq ITCH",
        },
        {
            "gate_id": "G4_SHARES_OUTSTANDING", "status": "BLOCKING_FOR_TURNOVER",
            "required_rows": str(len(symbol_dates)),
            "requirement": "Point-in-time shares outstanding covering every required symbol-date",
            "resolution": "Provide effective-dated authorized/public shares-outstanding series",
        },
        {
            "gate_id": "G5_MATCHED_CONTROL_UNIVERSE", "status": "BLOCKING_FOR_MODEL_EVAL",
            "required_rows": str(len(unique_event_dates)),
            "requirement": "Same-day candidate universe and pre-event metadata on every distinct event date",
            "resolution": "Provide point-in-time earnings/event universe and matching covariates; run Step-5 matcher",
        },
    ]


def build(events_path: Path, output_dir: Path, *, contract_path: Path | None = None,
          lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS, pre_minutes: int = DEFAULT_PRE_MINUTES,
          post_minutes: int = DEFAULT_POST_MINUTES, posthoc_extension_minutes: int = DEFAULT_POSTHOC_EXTENSION_MINUTES) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    plans, cal_meta = build_event_plans(events_path, lookback_sessions=lookback_sessions,
                                        pre_minutes=pre_minutes, post_minutes=post_minutes,
                                        posthoc_extension_minutes=posthoc_extension_minutes)
    symbol_dates = build_symbol_date_requirements(plans, posthoc_extension_minutes=posthoc_extension_minutes)
    source_dates = build_source_date_requirements(symbol_dates)
    announcement = build_announcement_requirements(events_path)
    audit = audit_contract(contract_path, source_dates)
    gates = build_unresolved_gates(plans, symbol_dates, source_dates, audit)

    _write_csv(output_dir / "event_coverage_plan.csv", plans)
    _write_csv(output_dir / "symbol_date_requirements.csv", symbol_dates)
    _write_csv(output_dir / "source_date_requirements.csv", source_dates)
    _write_csv(output_dir / "announcement_timestamp_requirements.csv", announcement)
    _write_csv(output_dir / "unresolved_gates.csv", gates)

    unique_event_dates = sorted({p.event_trade_date for p in plans})
    unique_market_dates = sorted({r.trade_date for r in symbol_dates})
    unique_symbols = sorted({p.historical_symbol for p in plans})
    missing_ann = sum(x["status"] == "missing" for x in announcement)
    core_source_rows = sum(r.requirement == "required_core" for r in source_dates)
    full_source_rows = sum(r.requirement == "required_full_replication" for r in source_dates)
    conditional_rows = sum(r.requirement == "conditional" for r in source_dates)
    total_requested_minutes = sum(r.requested_regular_session_minutes for r in symbol_dates)
    total_quote_minutes = sum(r.requested_quote_minutes for r in symbol_dates)
    ready = all(g["status"] in {"READY"} for g in gates)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Coverage planning for authorized historical market-surveillance backfill; no data acquisition or trading outputs.",
        "events_path": str(events_path),
        "events_sha256": _sha256(events_path),
        "event_count": len(plans),
        "unique_symbols": len(unique_symbols),
        "unique_event_dates": len(unique_event_dates),
        "unique_market_dates_event_plus_baseline": len(unique_market_dates),
        "unique_symbol_date_pairs": len(symbol_dates),
        "event_date_min": min(unique_event_dates),
        "event_date_max": max(unique_event_dates),
        "market_date_min": min(unique_market_dates),
        "market_date_max": max(unique_market_dates),
        "baseline_lookback_sessions": lookback_sessions,
        "event_window": {"pre_minutes": pre_minutes, "post_minutes": post_minutes, "posthoc_extension_minutes": posthoc_extension_minutes},
        "calendar": cal_meta,
        "missing_exact_announcement_timestamps": missing_ann,
        "required_core_source_date_rows": core_source_rows,
        "required_full_replication_source_date_rows": full_source_rows,
        "conditional_itch_source_date_rows": conditional_rows,
        "total_requested_symbol_minutes_core": total_requested_minutes,
        "total_requested_symbol_quote_minutes_including_posthoc_extension": total_quote_minutes,
        "contract_audit": audit,
        "blocking_gates": [g["gate_id"] for g in gates if g["status"].startswith("BLOCKING")],
        "ready_for_non_synthetic_champion_challenger_comparison": ready,
        "prohibited_outputs": PROHIBITED_OUTPUTS,
        "research_use_only": True,
    }
    (output_dir / "coverage_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    acquisition_plan = {
        "schema_version": "1",
        "policy": {
            "do_not_fetch_or_purchase_automatically": True,
            "credentials_in_plan": False,
            "authorization_required": True,
            "license_reference_required_for_non_synthetic_sources": True,
        },
        "profiles": {
            "core_equity_surveillance": ["nyse_daily_taq/equity_trade", "nyse_daily_taq/equity_quote"],
            "full_research_replication": ["nyse_daily_taq/equity_trade", "nyse_daily_taq/equity_quote", "cboe_option_trades/option_trade", "cboe_option_quotes/option_quote"],
            "order_flow_extension": ["nasdaq_itch_5_0_decoded/itch_decoded when point-in-time Nasdaq listing is confirmed"],
        },
        "date_count": len(unique_market_dates),
        "symbol_date_pair_count": len(symbol_dates),
        "event_count": len(plans),
        "announcement_timestamp_rows": len(announcement),
        "matched_control_candidate_dates": len(unique_event_dates),
        "next_action": "Supply authorized source paths/license references and point-in-time metadata, then rerun Step-15 importer and this readiness audit.",
    }
    (output_dir / "acquisition_import_plan.json").write_text(json.dumps(acquisition_plan, indent=2, sort_keys=True), encoding="utf-8")
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description="Plan exact authorized historical market-data coverage for the adjudicated event corpus.")
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--contract", type=Path)
    p.add_argument("--lookback-sessions", type=int, default=DEFAULT_LOOKBACK_SESSIONS)
    p.add_argument("--pre-minutes", type=int, default=DEFAULT_PRE_MINUTES)
    p.add_argument("--post-minutes", type=int, default=DEFAULT_POST_MINUTES)
    p.add_argument("--posthoc-extension-minutes", type=int, default=DEFAULT_POSTHOC_EXTENSION_MINUTES)
    args = p.parse_args()
    report = build(args.events, args.output_dir, contract_path=args.contract,
                   lookback_sessions=args.lookback_sessions, pre_minutes=args.pre_minutes,
                   post_minutes=args.post_minutes, posthoc_extension_minutes=args.posthoc_extension_minutes)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
