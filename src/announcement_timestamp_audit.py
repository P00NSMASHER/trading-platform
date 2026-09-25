from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
EXACT_KINDS = {"first_public_release", "official_newswire_release"}
EXACT_GRADES = {"A", "B"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_aware(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def parse_trade(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(timezone.utc)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "event_id", "historical_symbol", "event_date", "status",
        "selected_public_announcement_ts", "selected_source_grade",
        "selected_source_reference", "eligible_candidate_count", "issues",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def audit(requirements_path: Path, events_path: Path, candidates_path: Path, outdir: Path) -> dict:
    requirements = read_csv(requirements_path)
    events = {r["event_id"]: r for r in read_csv(events_path)}
    candidates = read_csv(candidates_path)

    required = {}
    for r in requirements:
        event_id = r.get("event_id", "").strip()
        if not event_id:
            continue
        required[event_id] = {
            "event_id": event_id,
            "historical_symbol": r.get("historical_symbol", "").strip().upper(),
            "event_date": r.get("event_trade_date", "").strip(),
        }

    by_event: dict[str, list[dict]] = defaultdict(list)
    rejected_rows = 0

    for row in candidates:
        event_id = row.get("event_id", "").strip()
        req = required.get(event_id)
        ev = events.get(event_id)
        issues = []

        if not req or not ev:
            rejected_rows += 1
            continue

        symbol = row.get("historical_symbol", "").strip().upper()
        event_date = row.get("event_date", "").strip()
        if symbol != req["historical_symbol"]:
            issues.append("SYMBOL_MISMATCH")
        if event_date != req["event_date"]:
            issues.append("DATE_MISMATCH")

        kind = row.get("timestamp_kind", "").strip().lower()
        grade = row.get("source_grade", "").strip().upper()
        source_reference = row.get("source_reference", "").strip()
        if kind not in EXACT_KINDS:
            issues.append("NOT_EXACT_TIMESTAMP_KIND")
        if grade not in EXACT_GRADES:
            issues.append("SOURCE_GRADE_NOT_A_B")
        if not source_reference:
            issues.append("MISSING_SOURCE_REFERENCE")

        try:
            announcement = parse_aware(row.get("public_announcement_ts", ""))
        except Exception:
            announcement = None
            issues.append("INVALID_OR_NAIVE_TIMESTAMP")

        try:
            first_trade = parse_trade(ev.get("first_documented_illicit_trade_ts", ""))
        except Exception:
            first_trade = None
            issues.append("INVALID_FIRST_TRADE_TIMESTAMP")

        if announcement is not None and first_trade is not None and announcement <= first_trade:
            issues.append("ANNOUNCEMENT_NOT_AFTER_FIRST_TRADE")

        if issues:
            rejected_rows += 1
            by_event[event_id].append({"eligible": False, "issues": issues, "row": row})
        else:
            by_event[event_id].append({
                "eligible": True,
                "announcement": announcement,
                "grade": grade,
                "source_reference": source_reference,
                "row": row,
                "issues": [],
            })

    output_rows = []
    ready_events = 0
    missing_events = 0
    blocking_events = 0

    for event_id, req in required.items():
        rows = by_event.get(event_id, [])
        eligible = [x for x in rows if x.get("eligible")]
        issues = []

        selected = None
        if not eligible:
            missing_events += 1
            issues.append("NO_ELIGIBLE_EXACT_TIMESTAMP")
            status = "MISSING"
        else:
            ordered = sorted(eligible, key=lambda x: (x["announcement"], x["grade"], x["source_reference"]))
            times = [x["announcement"] for x in ordered]
            spread_seconds = int((max(times) - min(times)).total_seconds()) if len(times) > 1 else 0
            if spread_seconds > 60:
                blocking_events += 1
                issues.append("ANN_EXACT_CONFLICT_GT_60_SECONDS")
                status = "BLOCKED_CONFLICT"
            else:
                ready_events += 1
                status = "READY"
                selected = ordered[0]
                if spread_seconds:
                    issues.append("NONZERO_EXACT_DISAGREEMENT_LE_60_SECONDS")

        output_rows.append({
            "event_id": event_id,
            "historical_symbol": req["historical_symbol"],
            "event_date": req["event_date"],
            "status": status,
            "selected_public_announcement_ts": (
                selected["announcement"].isoformat().replace("+00:00", "Z") if selected else ""
            ),
            "selected_source_grade": selected["grade"] if selected else "",
            "selected_source_reference": selected["source_reference"] if selected else "",
            "eligible_candidate_count": len(eligible),
            "issues": ";".join(issues),
        })

    summary = {
        "schema_version": "1",
        "purpose": "Fail-fast Phase B exact announcement timestamp completeness audit; Step 17/19/20 remain authoritative.",
        "required_events": len(required),
        "candidate_rows": len(candidates),
        "rejected_candidate_rows": rejected_rows,
        "ready_events": ready_events,
        "missing_events": missing_events,
        "blocking_events": blocking_events,
        "g1_candidate_ready": (
            len(required) > 0
            and ready_events == len(required)
            and missing_events == 0
            and blocking_events == 0
        ),
        "accepted_timestamp_kinds": sorted(EXACT_KINDS),
        "accepted_source_grades": sorted(EXACT_GRADES),
        "research_use_only": True,
    }

    outdir.mkdir(parents=True, exist_ok=True)
    write_csv(outdir / "announcement_timestamp_audit.csv", output_rows)
    (outdir / "announcement_timestamp_audit_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit Phase B exact first-public announcement timestamp completeness")
    ap.add_argument("--requirements", type=Path, required=True)
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(audit(args.requirements, args.events, args.candidates, args.outdir), indent=2))


if __name__ == "__main__":
    main()
