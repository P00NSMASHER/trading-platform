from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
MAX_MATCH_DAYS_DEFAULT = 7

OUTPUT_FIELDS = [
    "event_id",
    "historical_symbol",
    "event_date",
    "public_announcement_ts",
    "timestamp_kind",
    "source_grade",
    "source_reference",
]


class G1AdapterError(ValueError):
    pass


def _open_text(path: Path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise G1AdapterError(f"input does not exist: {path}")
    with _open_text(path) as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise G1AdapterError(f"missing CSV header: {path}")
        return [{k: (v or "").strip() for k, v in row.items()} for row in reader]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _parse_event_trade(value: str) -> datetime:
    raw = (value or "").strip()
    if not raw:
        raise G1AdapterError("event is missing first_documented_illicit_trade_ts")
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(UTC)


def _parse_ibes_date(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw or raw.lower() in {"nan", "nat", "none"}:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw[:10] if fmt == "%Y-%m-%d" else raw, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _parse_ibes_time(value: str) -> time | None:
    raw = (value or "").strip()
    if not raw or raw.lower() in {"nan", "nat", "none"}:
        return None
    if raw.endswith(".0"):
        raw = raw[:-2]
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            pass
    digits = "".join(ch for ch in raw if ch.isdigit())
    for width, fmt in ((6, "%H%M%S"), (4, "%H%M")):
        if len(digits) == width:
            try:
                return datetime.strptime(digits, fmt).time()
            except ValueError:
                pass
    return None


def _symbol_values(row: dict[str, str]) -> set[str]:
    out = set()
    for col in ("TICKER", "OFTIC"):
        val = (row.get(col) or "").strip().upper()
        if val:
            out.add(val)
    return out


def _candidate_timestamp(row: dict[str, str]) -> datetime | None:
    d = _parse_ibes_date(row.get("ANNDATS_ACT", ""))
    t = _parse_ibes_time(row.get("ANNTIMS_ACT", ""))
    if d is None or t is None:
        return None
    return datetime.combine(d, t, tzinfo=NY).astimezone(UTC)


def adapt_ibes(
    *,
    events_path: Path,
    ibes_detail_path: Path,
    output_path: Path,
    report_path: Path,
    entitlement_reference: str,
    source_id: str = "licensed-ibes-announcements",
    max_match_days: int = MAX_MATCH_DAYS_DEFAULT,
) -> dict:
    if not entitlement_reference.strip():
        raise G1AdapterError("entitlement_reference is required; do not label unlicensed data as authorized")
    if max_match_days < 0 or max_match_days > 31:
        raise G1AdapterError("max_match_days must be between 0 and 31")

    events = _read_csv(events_path)
    ibes = _read_csv(ibes_detail_path)
    required_event = {"event_id", "historical_symbol", "first_documented_illicit_trade_ts"}
    if not events or not required_event.issubset(events[0]):
        raise G1AdapterError(f"events must contain {sorted(required_event)}")
    if not ibes or not {"ANNDATS_ACT", "ANNTIMS_ACT"}.issubset(ibes[0]):
        raise G1AdapterError("I/B/E/S input must contain ANNDATS_ACT and ANNTIMS_ACT")
    if not ({"TICKER", "OFTIC"} & set(ibes[0])):
        raise G1AdapterError("I/B/E/S input must contain TICKER or OFTIC")

    by_symbol: dict[str, list[datetime]] = {}
    for row in ibes:
        ts = _candidate_timestamp(row)
        if ts is None:
            continue
        for symbol in _symbol_values(row):
            by_symbol.setdefault(symbol, []).append(ts)

    source_sha = _sha256(ibes_detail_path)
    rows: list[dict[str, str]] = []
    unresolved: list[dict[str, object]] = []

    for event in events:
        event_id = event["event_id"].strip()
        symbol = event["historical_symbol"].strip().upper()
        first = _parse_event_trade(event["first_documented_illicit_trade_ts"])
        end = first + timedelta(days=max_match_days)
        unique = sorted({ts for ts in by_symbol.get(symbol, []) if first < ts <= end})

        if len(unique) != 1:
            unresolved.append({
                "event_id": event_id,
                "historical_symbol": symbol,
                "first_documented_illicit_trade_ts": first.isoformat(),
                "candidate_count": len(unique),
                "candidate_timestamps_utc": [x.isoformat() for x in unique[:10]],
                "reason": "missing_candidate" if not unique else "ambiguous_multiple_announcement_times",
            })
            continue

        ts = unique[0]
        rows.append({
            "event_id": event_id,
            "historical_symbol": symbol,
            "event_date": ts.astimezone(NY).date().isoformat(),
            "public_announcement_ts": ts.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "timestamp_kind": "first_public_release",
            "source_grade": "A",
            "source_reference": f"ibes://{source_id}/{source_sha[:16]}/{event_id}/ANNDATS_ACT+ANNTIMS_ACT",
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    report = {
        "schema_version": "1",
        "purpose": "G1 exact earnings-announcement timestamp normalization only; no trading outputs.",
        "research_use_only": True,
        "events_path": str(events_path),
        "events_sha256": _sha256(events_path),
        "source_id": source_id,
        "source_sha256": source_sha,
        "source_raw_rows": len(ibes),
        "entitlement_reference": entitlement_reference.strip(),
        "max_match_days": max_match_days,
        "event_count": len(events),
        "resolved_exact_count": len(rows),
        "unresolved_count": len(unresolved),
        "g1_ready": len(rows) == len(events),
        "unresolved": unresolved,
        "raw_licensed_rows_embedded_in_output": False,
        "prohibited_outputs": [
            "BUY", "SELL", "expected_return", "target_price", "position_size", "order", "execution_instruction"
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Normalize an authorized I/B/E/S detail-history extract into the exact G1 announcement schema."
    )
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--ibes-detail", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--entitlement-reference", required=True)
    ap.add_argument("--source-id", default="licensed-ibes-announcements")
    ap.add_argument("--max-match-days", type=int, default=MAX_MATCH_DAYS_DEFAULT)
    ap.add_argument("--require-complete", action="store_true")
    args = ap.parse_args()

    result = adapt_ibes(
        events_path=args.events,
        ibes_detail_path=args.ibes_detail,
        output_path=args.output,
        report_path=args.report,
        entitlement_reference=args.entitlement_reference,
        source_id=args.source_id,
        max_match_days=args.max_match_days,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "unresolved"}, indent=2))
    if args.require_complete and not result["g1_ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
