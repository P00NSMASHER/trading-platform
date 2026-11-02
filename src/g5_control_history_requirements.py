from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

SCHEMA_VERSION = "1"
CALENDAR_NAME = "XNYS"
NY = ZoneInfo("America/New_York")
DEFAULT_NORMALIZATION_SESSIONS = 21
DEFAULT_DAILY_CLOSE_SESSIONS = 22
MARKET_KINDS = (
    "equity_trade",
    "equity_quote",
    "option_trade",
    "option_quote",
)


@dataclass(frozen=True)
class ControlHistoryRequirement:
    historical_symbol: str
    trade_date: str
    roles: str
    candidate_event_dates: str
    normal_minutes_local: str
    event_minutes_local: str
    close_minute_local: str
    require_equity_trade: int
    require_equity_quote: int
    require_option_trade: int
    require_option_quote: int
    require_shares_outstanding: int
    research_use_only: int = 1


@dataclass(frozen=True)
class SourceDateRequirement:
    record_kind: str
    trade_date: str
    unique_symbol_count: int
    historical_symbols: str
    symbol_date_pair_count: int
    frozen_g2_symbol_date_pair_count: int
    additional_g5_symbol_date_pair_count: int
    acquisition_scope: str = "authorized_historical_market_data"
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_ts(value: str, *, label: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{label} is blank")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid ISO timestamp") from exc
    if dt.tzinfo is None:
        raise ValueError(f"{label} must include timezone")
    return dt.astimezone(timezone.utc)


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    return fields, rows


def load_candidates(path: Path) -> list[dict]:
    fields, rows = _read_csv(path)
    required = {
        "event_date",
        "candidate_symbol",
        "latest_acceptable_effective_ts_utc",
    }
    missing = required.difference(fields)
    if missing:
        raise ValueError(f"candidate file missing columns: {sorted(missing)}")
    out = []
    seen = set()
    for row_no, row in enumerate(rows, 2):
        event_date = row["event_date"][:10]
        symbol = row["candidate_symbol"].upper()
        cutoff = _parse_ts(
            row["latest_acceptable_effective_ts_utc"],
            label=f"candidate row {row_no} cutoff",
        )
        key = (event_date, symbol)
        if not event_date or not symbol:
            raise ValueError(f"candidate row {row_no}: missing event_date/symbol")
        if key in seen:
            raise ValueError(f"duplicate candidate symbol-date: {event_date}|{symbol}")
        seen.add(key)
        out.append(
            {
                "event_date": event_date,
                "symbol": symbol,
                "cutoff": cutoff,
            }
        )
    if not out:
        raise ValueError("candidate file is empty")
    return out


def _calendar(start: date, end: date):
    cal = xcals.get_calendar(CALENDAR_NAME)
    sessions = list(
        cal.sessions_in_range(
            start - timedelta(days=140),
            end + timedelta(days=2),
        )
    )
    return cal, sessions


def _session_date(label) -> date:
    return label.date()


def _session_bounds(cal, label) -> tuple[datetime, datetime]:
    return (
        cal.session_open(label).to_pydatetime().astimezone(NY),
        cal.session_close(label).to_pydatetime().astimezone(NY),
    )


def _find_label(sessions, event_date: date):
    for label in sessions:
        if _session_date(label) == event_date:
            return label
    raise ValueError(f"{event_date} is not an {CALENDAR_NAME} session")


def _eligible_normalization_dates(
    cal,
    sessions,
    event_label,
    *,
    target_minute: datetime,
    count: int,
) -> tuple[list[date], int]:
    idx = sessions.index(event_label)
    selected: list[date] = []
    scanned = 0
    target_clock = target_minute.timetz().replace(tzinfo=None)
    target_end_clock = (
        target_minute + timedelta(minutes=1)
    ).timetz().replace(tzinfo=None)

    for label in reversed(sessions[:idx]):
        scanned += 1
        session_open, session_close = _session_bounds(cal, label)
        open_clock = session_open.timetz().replace(tzinfo=None)
        close_clock = session_close.timetz().replace(tzinfo=None)
        if open_clock <= target_clock and close_clock >= target_end_clock:
            selected.append(_session_date(label))
            if len(selected) == count:
                break
    if len(selected) != count:
        raise ValueError(
            f"unable to find {count} prior sessions containing {target_clock}"
        )
    selected.reverse()
    return selected, scanned


def _prior_session_dates(sessions, event_label, count: int) -> list[date]:
    idx = sessions.index(event_label)
    if idx < count:
        raise ValueError(f"unable to find {count} prior sessions")
    return [_session_date(label) for label in sessions[idx - count:idx]]


def _minute_text(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _load_frozen_pairs(path: Path | None) -> dict[str, set[tuple[str, str]]]:
    out = {kind: set() for kind in MARKET_KINDS}
    if path is None:
        return out
    fields, rows = _read_csv(path)
    required = {"record_kind", "trade_date", "historical_symbols"}
    missing = required.difference(fields)
    if missing:
        raise ValueError(
            f"frozen requirements missing columns: {sorted(missing)}"
        )
    for row in rows:
        kind = row["record_kind"]
        if kind not in out:
            continue
        trade_date = row["trade_date"][:10]
        for raw in row["historical_symbols"].split(";"):
            symbol = raw.strip().upper()
            if symbol:
                out[kind].add((symbol, trade_date))
    return out


def build(
    *,
    candidate_path: Path,
    output_dir: Path,
    frozen_requirements_path: Path | None = None,
    normalization_sessions: int = DEFAULT_NORMALIZATION_SESSIONS,
    daily_close_sessions: int = DEFAULT_DAILY_CLOSE_SESSIONS,
) -> dict:
    if normalization_sessions < 1:
        raise ValueError("normalization_sessions must be positive")
    if daily_close_sessions < normalization_sessions:
        raise ValueError(
            "daily_close_sessions must be >= normalization_sessions"
        )

    candidates = load_candidates(candidate_path)
    event_dates = [date.fromisoformat(row["event_date"]) for row in candidates]
    cal, sessions = _calendar(min(event_dates), max(event_dates))
    frozen_pairs = _load_frozen_pairs(frozen_requirements_path)

    bucket: dict[tuple[str, str], dict] = defaultdict(
        lambda: {
            "roles": set(),
            "candidate_event_dates": set(),
            "normal_minutes": set(),
            "event_minutes": set(),
        }
    )
    early_close_skips = 0

    for candidate in candidates:
        event_day = date.fromisoformat(candidate["event_date"])
        symbol = candidate["symbol"]
        cutoff_local = candidate["cutoff"].astimezone(NY)
        event_label = _find_label(sessions, event_day)
        session_open, session_close = _session_bounds(cal, event_label)
        if not (session_open <= cutoff_local <= session_close):
            raise ValueError(
                f"candidate cutoff outside regular session: {candidate['event_date']}|{symbol}"
            )

        target_minute = cutoff_local.replace(second=0, microsecond=0)
        previous_completed_minute = target_minute - timedelta(minutes=1)

        normalization_dates, scanned = _eligible_normalization_dates(
            cal,
            sessions,
            event_label,
            target_minute=target_minute,
            count=normalization_sessions,
        )
        early_close_skips += scanned - normalization_sessions
        close_dates = _prior_session_dates(
            sessions,
            event_label,
            daily_close_sessions,
        )

        event_key = (symbol, event_day.isoformat())
        bucket[event_key]["roles"].add("event_point")
        bucket[event_key]["candidate_event_dates"].add(event_day.isoformat())
        bucket[event_key]["event_minutes"].update(
            {
                _minute_text(previous_completed_minute),
                _minute_text(target_minute),
            }
        )

        for baseline_day in normalization_dates:
            key = (symbol, baseline_day.isoformat())
            bucket[key]["roles"].add("normalization_baseline")
            bucket[key]["candidate_event_dates"].add(event_day.isoformat())
            bucket[key]["normal_minutes"].add(_minute_text(target_minute))

        for close_day in close_dates:
            key = (symbol, close_day.isoformat())
            bucket[key]["roles"].add("daily_close_history")
            bucket[key]["candidate_event_dates"].add(event_day.isoformat())

    rows: list[ControlHistoryRequirement] = []
    source_pairs: dict[str, set[tuple[str, str]]] = {
        kind: set() for kind in MARKET_KINDS
    }
    shares_pairs: set[tuple[str, str]] = set()

    for (symbol, trade_date), state in sorted(
        bucket.items(),
        key=lambda item: (item[0][1], item[0][0]),
    ):
        label = cal.date_to_session(trade_date, direction="none")
        _session_open, session_close = _session_bounds(cal, label)
        close_minute = _minute_text(session_close - timedelta(minutes=1))
        roles = state["roles"]

        need_event_or_normal = bool(
            {"event_point", "normalization_baseline"}.intersection(roles)
        )
        require_equity_trade = 1
        require_equity_quote = int(need_event_or_normal)
        require_option_trade = int(need_event_or_normal)
        require_option_quote = int(need_event_or_normal)
        require_shares = int(need_event_or_normal)

        pair = (symbol, trade_date)
        source_pairs["equity_trade"].add(pair)
        if require_equity_quote:
            source_pairs["equity_quote"].add(pair)
        if require_option_trade:
            source_pairs["option_trade"].add(pair)
        if require_option_quote:
            source_pairs["option_quote"].add(pair)
        if require_shares:
            shares_pairs.add(pair)

        rows.append(
            ControlHistoryRequirement(
                historical_symbol=symbol,
                trade_date=trade_date,
                roles=";".join(sorted(roles)),
                candidate_event_dates=";".join(
                    sorted(state["candidate_event_dates"])
                ),
                normal_minutes_local=";".join(
                    sorted(state["normal_minutes"])
                ),
                event_minutes_local=";".join(
                    sorted(state["event_minutes"])
                ),
                close_minute_local=close_minute,
                require_equity_trade=require_equity_trade,
                require_equity_quote=require_equity_quote,
                require_option_trade=require_option_trade,
                require_option_quote=require_option_quote,
                require_shares_outstanding=require_shares,
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / "g5_control_history_symbol_date_requirements.csv"
    with detail_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(ControlHistoryRequirement.__dataclass_fields__),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    source_rows: list[SourceDateRequirement] = []
    for kind in MARKET_KINDS:
        by_date: dict[str, set[str]] = defaultdict(set)
        for symbol, trade_date in source_pairs[kind]:
            by_date[trade_date].add(symbol)
        for trade_date, symbols in sorted(by_date.items()):
            frozen_count = sum(
                (symbol, trade_date) in frozen_pairs[kind]
                for symbol in symbols
            )
            source_rows.append(
                SourceDateRequirement(
                    record_kind=kind,
                    trade_date=trade_date,
                    unique_symbol_count=len(symbols),
                    historical_symbols=";".join(sorted(symbols)),
                    symbol_date_pair_count=len(symbols),
                    frozen_g2_symbol_date_pair_count=frozen_count,
                    additional_g5_symbol_date_pair_count=(
                        len(symbols) - frozen_count
                    ),
                )
            )

    source_path = output_dir / "g5_control_history_source_date_requirements.csv"
    with source_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(SourceDateRequirement.__dataclass_fields__),
        )
        writer.writeheader()
        for row in source_rows:
            writer.writerow(asdict(row))

    shares_path = output_dir / "g5_control_history_shares_requirements.csv"
    with shares_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "historical_symbol",
                "trade_date",
                "requirement",
                "research_use_only",
            ],
        )
        writer.writeheader()
        for symbol, trade_date in sorted(
            shares_pairs,
            key=lambda pair: (pair[1], pair[0]),
        ):
            writer.writerow(
                {
                    "historical_symbol": symbol,
                    "trade_date": trade_date,
                    "requirement": "point_in_time_shares_for_g5_turnover_or_market_cap",
                    "research_use_only": 1,
                }
            )

    role_counts = defaultdict(int)
    for row in rows:
        for role in row.roles.split(";"):
            role_counts[role] += 1

    pair_counts = {
        kind: len(pairs)
        for kind, pairs in source_pairs.items()
    }
    frozen_pair_counts = {
        kind: sum(pair in frozen_pairs[kind] for pair in source_pairs[kind])
        for kind in MARKET_KINDS
    }
    additional_pair_counts = {
        kind: pair_counts[kind] - frozen_pair_counts[kind]
        for kind in MARKET_KINDS
    }

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Plan the additional market-history and point-in-time shares footprint "
            "needed to derive G5 matching covariates for primary control candidates. "
            "This closes a planning gap: event-date control slices alone are not "
            "sufficient for 21-session normalization or trailing volatility."
        ),
        "research_use_only": True,
        "calendar": CALENDAR_NAME,
        "calendar_library_version": xcals.__version__,
        "primary_candidate_symbol_date_count": len(candidates),
        "normalization_sessions": normalization_sessions,
        "daily_close_sessions": daily_close_sessions,
        "unique_control_history_symbol_date_pairs": len(rows),
        "role_symbol_date_counts": dict(sorted(role_counts.items())),
        "market_symbol_date_pair_counts": pair_counts,
        "frozen_g2_overlap_pair_counts": frozen_pair_counts,
        "additional_g5_market_pair_counts": additional_pair_counts,
        "shares_symbol_date_pair_count": len(shares_pairs),
        "early_close_or_short_session_skips": early_close_skips,
        "inputs": {
            "candidate_path": str(candidate_path),
            "candidate_sha256": _sha256(candidate_path),
            "frozen_requirements_path": (
                str(frozen_requirements_path)
                if frozen_requirements_path is not None
                else None
            ),
            "frozen_requirements_sha256": (
                _sha256(frozen_requirements_path)
                if frozen_requirements_path is not None
                else None
            ),
        },
        "outputs": {
            "symbol_date_requirements": str(detail_path),
            "source_date_requirements": str(source_path),
            "shares_requirements": str(shares_path),
        },
        "policy": {
            "event_date_four_kind_market_data_required": True,
            "normalization_baselines_require_four_kind_market_data": True,
            "daily_close_only_dates_require_equity_trade_data": True,
            "shares_required_for_event_and_normalization_dates": True,
            "requirements_are_g5_evidence": False,
            "no_data_fetch_or_purchase_performed": True,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_control_history_requirement_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan G5 control-candidate historical market/shares coverage."
    )
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--frozen-requirements", type=Path)
    parser.add_argument(
        "--normalization-sessions",
        type=int,
        default=DEFAULT_NORMALIZATION_SESSIONS,
    )
    parser.add_argument(
        "--daily-close-sessions",
        type=int,
        default=DEFAULT_DAILY_CLOSE_SESSIONS,
    )
    args = parser.parse_args()
    result = build(
        candidate_path=args.candidates,
        output_dir=args.output_dir,
        frozen_requirements_path=args.frozen_requirements,
        normalization_sessions=args.normalization_sessions,
        daily_close_sessions=args.daily_close_sessions,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
