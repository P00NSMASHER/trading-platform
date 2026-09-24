from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

SOURCE_REPO = "vgreg/hacked_earnings_jfe"
SOURCE_PATH = "Data/TimeOfFirstTrade.csv"
SOURCE_DESCRIPTION = (
    "Historical first-trade timestamps documented in SEC complaint materials, "
    "as packaged by the hacked_earnings_jfe replication repository."
)


@dataclass(frozen=True)
class CorpusEvent:
    event_id: str
    permno: int
    gvkey: int
    historical_symbol: str
    first_documented_illicit_trade_ts: str
    public_announcement_ts: str
    information_asymmetry_seconds: str
    hacked_flag: int
    sec_documented_trade_flag: int
    first_trade_timestamp_source: str
    announcement_timestamp_source: str
    timestamp_confidence: str
    research_use_only: int


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")


def _event_id(permno: int, gvkey: int, symbol: str, ts: str) -> str:
    raw = f"{permno}|{gvkey}|{symbol}|{ts}".encode("utf-8")
    return "HEJFE-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def load_first_trades(path: Path) -> list[CorpusEvent]:
    events: list[CorpusEvent] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"PERMNO", "SYMBOL", "GVKEY", "TimeOfFirstTrade"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required columns: {sorted(missing)}")

        for row_number, row in enumerate(reader, start=2):
            try:
                permno = int(row["PERMNO"])
                gvkey = int(row["GVKEY"])
                symbol = row["SYMBOL"].strip().upper()
                dt = _parse_timestamp(row["TimeOfFirstTrade"])
            except Exception as exc:  # explicit row location for auditability
                raise ValueError(f"Invalid source row {row_number}: {exc}") from exc

            ts = dt.strftime("%Y-%m-%d %H:%M:%S")
            events.append(
                CorpusEvent(
                    event_id=_event_id(permno, gvkey, symbol, ts),
                    permno=permno,
                    gvkey=gvkey,
                    historical_symbol=symbol,
                    first_documented_illicit_trade_ts=ts,
                    public_announcement_ts="",
                    information_asymmetry_seconds="",
                    hacked_flag=1,
                    sec_documented_trade_flag=1,
                    first_trade_timestamp_source=(
                        f"{SOURCE_REPO}/{SOURCE_PATH}; SEC complaint-derived historical label"
                    ),
                    announcement_timestamp_source="PENDING_AUTHORIZED_POINT_IN_TIME_JOIN",
                    timestamp_confidence="B-PENDING-ANNOUNCEMENT-TIME",
                    research_use_only=1,
                )
            )
    return events


def validate(events: Iterable[CorpusEvent]) -> dict:
    events = list(events)
    ids = [e.event_id for e in events]
    duplicate_ids = [k for k, v in Counter(ids).items() if v > 1]
    symbols = Counter(e.historical_symbol for e in events)
    years = Counter(e.first_documented_illicit_trade_ts[:4] for e in events)
    hours = Counter(e.first_documented_illicit_trade_ts[11:13] for e in events)

    issues: list[str] = []
    if duplicate_ids:
        issues.append(f"duplicate event IDs: {duplicate_ids}")
    if any(not e.historical_symbol for e in events):
        issues.append("blank symbols detected")
    if any(e.sec_documented_trade_flag != 1 for e in events):
        issues.append("unexpected non-positive ground-truth row")
    if any(e.public_announcement_ts for e in events):
        issues.append("announcement times unexpectedly pre-populated")

    return {
        "row_count": len(events),
        "unique_event_ids": len(set(ids)),
        "unique_symbols": len(symbols),
        "year_distribution": dict(sorted(years.items())),
        "first_trade_hour_distribution": dict(sorted(hours.items())),
        "issues": issues,
        "valid": not issues,
    }


def write_csv(events: Iterable[CorpusEvent], output_path: Path) -> None:
    events = list(events)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(events[0]).keys()) if events else [f.name for f in CorpusEvent.__dataclass_fields__.values()]
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for event in events:
            writer.writerow(asdict(event))


def write_manifest(events: list[CorpusEvent], report: dict, output_path: Path) -> None:
    source_hash = hashlib.sha256(
        "\n".join(
            f"{e.permno}|{e.gvkey}|{e.historical_symbol}|{e.first_documented_illicit_trade_ts}"
            for e in events
        ).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema_version": "0.1.0",
        "purpose": "Historical market-surveillance research corpus; not a trading signal dataset.",
        "source_repository": SOURCE_REPO,
        "source_path": SOURCE_PATH,
        "source_description": SOURCE_DESCRIPTION,
        "source_record_hash_sha256": source_hash,
        "ground_truth_definition": (
            "Positive historical event = first trade by hackers according to SEC complaint documentation, "
            "as represented in the source replication package."
        ),
        "announcement_time_status": (
            "Exact public release timestamps are intentionally blank until joined from an authorized "
            "point-in-time source such as licensed I/B/E/S or an independently verified public-release timestamp."
        ),
        "validation": report,
    }
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build(input_path: Path, output_dir: Path) -> dict:
    events = load_first_trades(input_path)
    report = validate(events)
    if not report["valid"]:
        raise RuntimeError(f"Corpus validation failed: {report['issues']}")

    write_csv(events, output_dir / "historical_events.csv")
    write_manifest(events, report, output_dir / "manifest.json")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build private historical surveillance corpus.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    report = build(args.input, args.output_dir)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
