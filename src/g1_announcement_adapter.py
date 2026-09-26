from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "1"
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_MAX_DAYS = 45


class G1AdapterError(ValueError):
    pass


@dataclass(frozen=True)
class Event:
    event_id: str
    permno: str
    historical_symbol: str
    first_trade: datetime


@dataclass(frozen=True)
class ExactAnnouncement:
    event_id: str
    historical_symbol: str
    event_date: str
    public_announcement_ts: str
    timestamp_kind: str
    source_grade: str
    source_reference: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _parse_date(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise G1AdapterError("announcement date is blank")
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%d%b%Y", "%d%b%y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except ValueError as exc:
        raise G1AdapterError(f"unsupported announcement date: {raw!r}") from exc


def _parse_time(value: str) -> tuple[int, int, int]:
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"nan", "nat", "none"}:
        raise G1AdapterError("announcement time is blank")
    if raw.endswith(".0") and raw[:-2].isdigit():
        raw = raw[:-2]
    if ":" in raw:
        parts = raw.split(":")
        if len(parts) not in {2, 3}:
            raise G1AdapterError(f"unsupported announcement time: {raw!r}")
        try:
            hh, mm = int(parts[0]), int(parts[1])
            ss = int(float(parts[2])) if len(parts) == 3 else 0
        except ValueError as exc:
            raise G1AdapterError(f"unsupported announcement time: {raw!r}") from exc
    else:
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) <= 4:
            digits = digits.zfill(4) + "00"
        elif len(digits) <= 6:
            digits = digits.zfill(6)
        else:
            raise G1AdapterError(f"unsupported announcement time: {raw!r}")
        hh, mm, ss = int(digits[:2]), int(digits[2:4]), int(digits[4:6])
    if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
        raise G1AdapterError(f"announcement time out of range: {raw!r}")
    return hh, mm, ss


def _parse_event_ts(value: str, timezone_name: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise G1AdapterError("first_documented_illicit_trade_ts is blank")
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(timezone_name))
    return dt


def load_events(path: Path, timezone_name: str = DEFAULT_TIMEZONE) -> list[Event]:
    rows = read_csv(path)
    required = {"event_id", "permno", "historical_symbol", "first_documented_illicit_trade_ts"}
    if not rows:
        raise G1AdapterError("historical events file is empty")
    missing = required - set(rows[0])
    if missing:
        raise G1AdapterError(f"historical events missing columns: {sorted(missing)}")
    out = []
    seen = set()
    for row in rows:
        event_id = str(row["event_id"]).strip()
        if not event_id or event_id in seen:
            raise G1AdapterError(f"duplicate or blank event_id: {event_id!r}")
        seen.add(event_id)
        out.append(
            Event(
                event_id=event_id,
                permno=str(row["permno"]).strip(),
                historical_symbol=str(row["historical_symbol"]).strip().upper(),
                first_trade=_parse_event_ts(row["first_documented_illicit_trade_ts"], timezone_name),
            )
        )
    return out


def _parse_link_date(value: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise G1AdapterError("IBES link date is blank")
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d%b%Y", "%d%b%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    raise G1AdapterError(f"unsupported IBES link date: {raw!r}")


def load_link(path: Path | None) -> list[dict[str, object]]:
    if path is None:
        return []
    rows = read_csv(path)
    if not rows:
        raise G1AdapterError("IBES link file is empty")
    required = {"TICKER", "PERMNO", "sdate", "edate"}
    missing = required - set(rows[0])
    if missing:
        raise G1AdapterError(f"IBES link file missing columns: {sorted(missing)}")
    out = []
    for row in rows:
        out.append(
            {
                "ticker": str(row["TICKER"]).strip().upper(),
                "permno": str(row["PERMNO"]).strip(),
                "start": _parse_link_date(row["sdate"]).date(),
                "end": _parse_link_date(row["edate"]).date(),
            }
        )
    return out


def _row_permno(row: dict[str, str], announcement_date: datetime, link_rows: list[dict[str, object]]) -> str:
    direct = str(row.get("PERMNO", "") or row.get("permno", "")).strip()
    if direct:
        return direct
    ticker = str(row.get("TICKER", "") or row.get("OFTIC", "") or row.get("ticker", "")).strip().upper()
    if not ticker:
        return ""
    matches = [
        x for x in link_rows
        if x["ticker"] == ticker and x["start"] <= announcement_date.date() <= x["end"]
    ]
    permnos = sorted({str(x["permno"]) for x in matches})
    return permnos[0] if len(permnos) == 1 else ""


def load_ibes_actuals(
    path: Path,
    *,
    link_path: Path | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> dict[str, list[datetime]]:
    rows = read_csv(path)
    if not rows:
        raise G1AdapterError("IBES export is empty")
    cols = set(rows[0])
    if "ANNDATS_ACT" not in cols or "ANNTIMS_ACT" not in cols:
        raise G1AdapterError("IBES export must contain ANNDATS_ACT and ANNTIMS_ACT")
    if not ({"PERMNO", "permno"} & cols) and not ({"TICKER", "OFTIC", "ticker"} & cols):
        raise G1AdapterError("IBES export needs PERMNO or a ticker column plus --ibes-link")
    links = load_link(link_path)
    zone = ZoneInfo(timezone_name)
    grouped: dict[str, set[datetime]] = {}
    invalid = 0
    for row in rows:
        try:
            d = _parse_date(row.get("ANNDATS_ACT", ""))
            hh, mm, ss = _parse_time(row.get("ANNTIMS_ACT", ""))
        except G1AdapterError:
            invalid += 1
            continue
        permno = _row_permno(row, d, links)
        if not permno:
            continue
        ts = d.replace(hour=hh, minute=mm, second=ss, microsecond=0, tzinfo=zone)
        grouped.setdefault(permno, set()).add(ts)
    if not grouped:
        detail = "all rows lacked usable exact actual timestamps"
        if invalid:
            detail += f" ({invalid} rows had blank/invalid ANNDATS_ACT or ANNTIMS_ACT)"
        raise G1AdapterError(detail)
    return {k: sorted(v) for k, v in grouped.items()}


def match_events(
    events: Iterable[Event],
    actuals: dict[str, list[datetime]],
    *,
    max_days: int = DEFAULT_MAX_DAYS,
) -> tuple[list[tuple[Event, datetime]], list[dict[str, str]], list[dict[str, str]]]:
    matched: list[tuple[Event, datetime]] = []
    unresolved: list[dict[str, str]] = []
    ambiguous: list[dict[str, str]] = []
    horizon = timedelta(days=max_days)
    for event in events:
        candidates = [
            ts for ts in actuals.get(event.permno, [])
            if event.first_trade < ts <= event.first_trade + horizon
        ]
        candidates.sort()
        if not candidates:
            unresolved.append(
                {
                    "event_id": event.event_id,
                    "permno": event.permno,
                    "historical_symbol": event.historical_symbol,
                    "first_documented_illicit_trade_ts": event.first_trade.isoformat(timespec="seconds"),
                    "reason": f"no exact IBES actual timestamp within {max_days} days after first trade",
                }
            )
            continue
        nearest_date = candidates[0].date()
        same_release_date = [x for x in candidates if x.date() == nearest_date]
        if len(same_release_date) != 1:
            ambiguous.append(
                {
                    "event_id": event.event_id,
                    "permno": event.permno,
                    "historical_symbol": event.historical_symbol,
                    "candidate_timestamps": ";".join(x.isoformat(timespec="seconds") for x in same_release_date),
                    "reason": "multiple distinct exact actual timestamps on nearest release date",
                }
            )
            continue
        matched.append((event, same_release_date[0]))
    return matched, unresolved, ambiguous


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def build(
    *,
    events_path: Path,
    ibes_path: Path,
    output_dir: Path,
    ibes_link_path: Path | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
    max_days: int = DEFAULT_MAX_DAYS,
    source_reference: str = "authorized I/B/E/S actual announcement date/time export",
    expected_ibes_sha256: str = "",
) -> dict:
    events_path = Path(events_path)
    ibes_path = Path(ibes_path)
    output_dir = Path(output_dir)
    if expected_ibes_sha256:
        expected = expected_ibes_sha256.strip().lower()
        actual = sha256_file(ibes_path)
        if expected != actual:
            raise G1AdapterError(f"IBES source SHA-256 mismatch: expected {expected}, got {actual}")

    events = load_events(events_path, timezone_name)
    actuals = load_ibes_actuals(ibes_path, link_path=ibes_link_path, timezone_name=timezone_name)
    matched, unresolved, ambiguous = match_events(events, actuals, max_days=max_days)

    canonical_rows = [
        asdict(
            ExactAnnouncement(
                event_id=event.event_id,
                historical_symbol=event.historical_symbol,
                event_date=event.first_trade.date().isoformat(),
                public_announcement_ts=ts.isoformat(timespec="seconds"),
                timestamp_kind="first_public_release",
                source_grade="A",
                source_reference=source_reference,
            )
        )
        for event, ts in matched
    ]
    canonical_rows.sort(key=lambda x: x["event_id"])
    unresolved.sort(key=lambda x: x["event_id"])
    ambiguous.sort(key=lambda x: x["event_id"])

    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_path = output_dir / "announcement_timestamps.csv"
    _write_csv(
        canonical_path,
        canonical_rows,
        [
            "event_id",
            "historical_symbol",
            "event_date",
            "public_announcement_ts",
            "timestamp_kind",
            "source_grade",
            "source_reference",
        ],
    )
    _write_csv(
        output_dir / "unresolved_events.csv",
        unresolved,
        ["event_id", "permno", "historical_symbol", "first_documented_illicit_trade_ts", "reason"],
    )
    _write_csv(
        output_dir / "ambiguous_events.csv",
        ambiguous,
        ["event_id", "permno", "historical_symbol", "candidate_timestamps", "reason"],
    )

    ready = len(matched) == len(events) and not unresolved and not ambiguous
    contract = {
        "schema_version": "1",
        "purpose": "G1 exact public earnings-announcement timestamps derived from an authorized I/B/E/S export.",
        "sources": [
            {
                "source_id": "g1-ibes-exact-announcements",
                "record_kind": "announcement_timestamp",
                "source_family": "ibes_announcement",
                "path": str(canonical_path),
                "enabled": True,
                "authorized": True,
                "data_classification": "authorized_reference_data",
                "license_reference": source_reference,
                "delimiter": ",",
                "encoding": "utf-8",
                "timezone": timezone_name,
                "column_map": {},
                "notes": "Generated only from rows with both ANNDATS_ACT and ANNTIMS_ACT; no date-only inference.",
            }
        ],
    }
    contract_path = output_dir / "metadata_source_contract.json"
    contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "research_use_only": True,
        "purpose": "Prepare exact public announcement timestamps for G1 without inferring missing times.",
        "events_sha256": sha256_file(events_path),
        "ibes_sha256": sha256_file(ibes_path),
        "ibes_link_sha256": sha256_file(ibes_link_path) if ibes_link_path else None,
        "event_count": len(events),
        "matched_exact_count": len(matched),
        "unresolved_count": len(unresolved),
        "ambiguous_count": len(ambiguous),
        "ready_for_g1": ready,
        "canonical_output": str(canonical_path),
        "canonical_output_sha256": sha256_file(canonical_path),
        "contract_output": str(contract_path),
        "contract_output_sha256": sha256_file(contract_path),
        "max_match_horizon_days": max_days,
        "timezone": timezone_name,
        "fail_closed_rules": [
            "ANNDATS_ACT and ANNTIMS_ACT are both required",
            "no date-only, before-market-open, after-market-close, or other inferred time is accepted",
            "multiple distinct timestamps on the nearest release date require review",
            "every historical event must resolve before ready_for_g1 can become true",
        ],
        "prohibited_outputs": [
            "BUY",
            "SELL",
            "expected_return",
            "target_price",
            "position_size",
            "order",
            "execution_instruction",
        ],
    }
    (output_dir / "g1_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description="Convert authorized I/B/E/S actual announcement timestamps into the exact G1 metadata contract")
    p.add_argument("--events", type=Path, default=Path("data/processed/historical_events.csv"))
    p.add_argument("--ibes", type=Path, required=True)
    p.add_argument("--ibes-link", type=Path)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    p.add_argument("--max-days", type=int, default=DEFAULT_MAX_DAYS)
    p.add_argument("--source-reference", default="authorized I/B/E/S actual announcement date/time export")
    p.add_argument("--expected-ibes-sha256", default="")
    args = p.parse_args()
    if args.max_days <= 0:
        p.error("--max-days must be positive")
    try:
        summary = build(
            events_path=args.events,
            ibes_path=args.ibes,
            ibes_link_path=args.ibes_link,
            output_dir=args.output_dir,
            timezone_name=args.timezone,
            max_days=args.max_days,
            source_reference=args.source_reference,
            expected_ibes_sha256=args.expected_ibes_sha256,
        )
    except G1AdapterError as exc:
        p.error(str(exc))
    print(json.dumps(summary, indent=2))
    return 0 if summary["ready_for_g1"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
