from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "1"


class G5ControlSharesAnchorReuseError(ValueError):
    pass


@dataclass(frozen=True)
class CrossDateSharesReuse:
    historical_symbol: str
    trade_date: str
    latest_acceptable_available_at_utc: str
    canonical_anchor_trade_date: str
    shares_outstanding: str
    fact_date: str
    available_at: str
    source_id: str
    source_family: str
    source_reference: str
    target_staleness_days: int
    original_gap_reason: str
    resolution_status: str = "REUSE_CANONICAL_G4_POINT_IN_TIME_ANCHOR"
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    return fields, rows


def _parse_date(value: str, *, label: str) -> date:
    raw = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise G5ControlSharesAnchorReuseError(
            f"{label} must be a valid YYYY-MM-DD date"
        ) from exc


def _parse_ts(value: str, *, label: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise G5ControlSharesAnchorReuseError(f"{label} is blank")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G5ControlSharesAnchorReuseError(
            f"{label} must be a valid ISO timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise G5ControlSharesAnchorReuseError(
            f"{label} must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _fmt_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _load_gap_rows(path: Path) -> tuple[list[str], list[dict[str, object]]]:
    fields, rows = _read_csv(path)
    required = {
        "historical_symbol",
        "trade_date",
        "latest_acceptable_available_at_utc",
        "gap_reason",
        "max_fact_staleness_days",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5ControlSharesAnchorReuseError(
            f"G5 shares gap queue missing columns: {sorted(missing)}"
        )
    if not rows:
        return fields, []

    out: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        target = _parse_date(
            row["trade_date"],
            label=f"G5 shares gap row {row_no} trade_date",
        )
        cutoff = _parse_ts(
            row["latest_acceptable_available_at_utc"],
            label=f"G5 shares gap row {row_no} cutoff",
        )
        if not symbol:
            raise G5ControlSharesAnchorReuseError(
                f"G5 shares gap row {row_no}: historical_symbol required"
            )
        if row["research_use_only"] != "1":
            raise G5ControlSharesAnchorReuseError(
                f"G5 shares gap row {row_no}: research_use_only must equal 1"
            )
        try:
            max_staleness = int(row["max_fact_staleness_days"])
        except ValueError as exc:
            raise G5ControlSharesAnchorReuseError(
                f"G5 shares gap row {row_no}: max_fact_staleness_days must be an integer"
            ) from exc
        if max_staleness < 0:
            raise G5ControlSharesAnchorReuseError(
                f"G5 shares gap row {row_no}: max_fact_staleness_days must be nonnegative"
            )
        key = (symbol, target.isoformat())
        if key in seen:
            raise G5ControlSharesAnchorReuseError(
                f"duplicate G5 shares gap: {symbol}|{target.isoformat()}"
            )
        seen.add(key)
        out.append(
            {
                "raw": dict(row),
                "historical_symbol": symbol,
                "trade_date": target,
                "cutoff": cutoff,
                "max_staleness_days": max_staleness,
            }
        )
    return fields, out


def _load_g4_anchors(path: Path) -> dict[str, list[dict[str, object]]]:
    fields, rows = _read_csv(path)
    required = {
        "historical_symbol",
        "trade_date",
        "shares_outstanding",
        "resolution_status",
        "source_reference",
        "fact_date",
        "available_at",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5ControlSharesAnchorReuseError(
            f"canonical G4 shares resolutions missing columns: {sorted(missing)}"
        )

    by_symbol: dict[str, list[dict[str, object]]] = {}
    seen: set[tuple[str, str]] = set()
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        anchor_date = _parse_date(
            row["trade_date"],
            label=f"G4 shares row {row_no} trade_date",
        )
        if not symbol:
            raise G5ControlSharesAnchorReuseError(
                f"G4 shares row {row_no}: historical_symbol required"
            )
        key = (symbol, anchor_date.isoformat())
        if key in seen:
            raise G5ControlSharesAnchorReuseError(
                f"duplicate canonical G4 shares resolution: {symbol}|{anchor_date.isoformat()}"
            )
        seen.add(key)
        if row["research_use_only"] != "1":
            raise G5ControlSharesAnchorReuseError(
                f"G4 shares row {row_no}: research_use_only must equal 1"
            )
        if row["resolution_status"] != "resolved":
            continue

        try:
            shares = int(row["shares_outstanding"])
        except ValueError as exc:
            raise G5ControlSharesAnchorReuseError(
                f"G4 shares row {row_no}: resolved shares_outstanding must be positive integer"
            ) from exc
        if shares <= 0:
            raise G5ControlSharesAnchorReuseError(
                f"G4 shares row {row_no}: resolved shares_outstanding must be positive integer"
            )
        fact_date = _parse_date(
            row["fact_date"],
            label=f"G4 shares row {row_no} fact_date",
        )
        available_at = _parse_ts(
            row["available_at"],
            label=f"G4 shares row {row_no} available_at",
        )
        if fact_date > anchor_date:
            raise G5ControlSharesAnchorReuseError(
                f"G4 shares row {row_no}: fact_date exceeds canonical trade_date"
            )
        if not row["source_reference"]:
            raise G5ControlSharesAnchorReuseError(
                f"G4 shares row {row_no}: resolved source_reference required"
            )

        by_symbol.setdefault(symbol, []).append(
            {
                "historical_symbol": symbol,
                "anchor_trade_date": anchor_date,
                "shares_outstanding": str(shares),
                "fact_date": fact_date,
                "available_at": available_at,
                "source_id": row.get("source_id", ""),
                "source_family": row.get("source_family", ""),
                "source_reference": row["source_reference"],
            }
        )

    for anchors in by_symbol.values():
        anchors.sort(
            key=lambda item: (
                item["fact_date"],
                item["anchor_trade_date"],
                item["available_at"],
                item["source_reference"],
            )
        )
    return by_symbol


def _select_anchor(
    *,
    item: dict[str, object],
    anchors: list[dict[str, object]],
) -> dict[str, object] | None:
    target = item["trade_date"]
    cutoff = item["cutoff"]
    max_staleness = item["max_staleness_days"]
    assert isinstance(target, date)
    assert isinstance(cutoff, datetime)
    assert isinstance(max_staleness, int)

    admissible: list[dict[str, object]] = []
    for anchor in anchors:
        anchor_trade_date = anchor["anchor_trade_date"]
        fact_date = anchor["fact_date"]
        available_at = anchor["available_at"]
        assert isinstance(anchor_trade_date, date)
        assert isinstance(fact_date, date)
        assert isinstance(available_at, datetime)

        if anchor_trade_date >= target:
            continue
        if fact_date > target:
            continue
        staleness = (target - fact_date).days
        if staleness < 0 or staleness > max_staleness:
            continue
        if available_at > cutoff:
            continue
        admissible.append({**anchor, "target_staleness_days": staleness})

    if not admissible:
        return None

    latest_fact_date = max(anchor["fact_date"] for anchor in admissible)
    latest = [
        anchor
        for anchor in admissible
        if anchor["fact_date"] == latest_fact_date
    ]
    values = {anchor["shares_outstanding"] for anchor in latest}
    if len(values) != 1:
        raise G5ControlSharesAnchorReuseError(
            "conflicting canonical G4 shares values for latest admissible fact "
            f"{item['historical_symbol']}|{target.isoformat()}|{latest_fact_date.isoformat()}"
        )

    latest.sort(
        key=lambda anchor: (
            anchor["anchor_trade_date"],
            anchor["available_at"],
            anchor["source_reference"],
        ),
        reverse=True,
    )
    return latest[0]


def build(
    *,
    shares_gap_queue_path: Path,
    canonical_g4_shares_path: Path,
    output_dir: Path,
) -> dict:
    gap_fields, gaps = _load_gap_rows(shares_gap_queue_path)
    anchors_by_symbol = _load_g4_anchors(canonical_g4_shares_path)

    reused: list[CrossDateSharesReuse] = []
    remaining: list[dict[str, str]] = []
    reuse_by_gap_reason: Counter[str] = Counter()

    for item in sorted(
        gaps,
        key=lambda row: (
            row["trade_date"],
            row["historical_symbol"],
        ),
    ):
        symbol = str(item["historical_symbol"])
        target = item["trade_date"]
        cutoff = item["cutoff"]
        assert isinstance(target, date)
        assert isinstance(cutoff, datetime)

        anchor = _select_anchor(
            item=item,
            anchors=anchors_by_symbol.get(symbol, []),
        )
        if anchor is None:
            remaining.append(dict(item["raw"]))
            continue

        reuse_by_gap_reason[str(item["raw"]["gap_reason"])] += 1
        reused.append(
            CrossDateSharesReuse(
                historical_symbol=symbol,
                trade_date=target.isoformat(),
                latest_acceptable_available_at_utc=_fmt_ts(cutoff),
                canonical_anchor_trade_date=anchor["anchor_trade_date"].isoformat(),
                shares_outstanding=str(anchor["shares_outstanding"]),
                fact_date=anchor["fact_date"].isoformat(),
                available_at=_fmt_ts(anchor["available_at"]),
                source_id=str(anchor["source_id"]),
                source_family=str(anchor["source_family"]),
                source_reference=str(anchor["source_reference"]),
                target_staleness_days=int(anchor["target_staleness_days"]),
                original_gap_reason=str(item["raw"]["gap_reason"]),
            )
        )

    if len(reused) + len(remaining) != len(gaps):
        raise G5ControlSharesAnchorReuseError(
            "cross-date G4 shares reuse does not reconcile to the input gap queue"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    reuse_path = output_dir / "g5_control_shares_cross_date_g4_reuse.csv"
    remaining_path = output_dir / "g5_control_shares_remaining_acquisition_queue.csv"
    summary_path = output_dir / "g5_control_shares_anchor_reuse_summary.json"

    with reuse_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(CrossDateSharesReuse.__dataclass_fields__),
        )
        writer.writeheader()
        for row in reused:
            writer.writerow(asdict(row))

    with remaining_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=gap_fields)
        writer.writeheader()
        writer.writerows(remaining)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Reduce G5 incremental point-in-time shares acquisition by reusing earlier "
            "canonical G4 resolved shares facts only when the underlying fact date is "
            "not after the G5 target, the fact is within the target's explicit staleness "
            "limit, the source was public before the conservative G5 cutoff, and the "
            "canonical anchor target date itself is earlier than the G5 target."
        ),
        "research_use_only": True,
        "input_gap_count": len(gaps),
        "cross_date_g4_anchor_reuse_count": len(reused),
        "remaining_incremental_acquisition_count": len(remaining),
        "reuse_count_by_original_gap_reason": dict(
            sorted(reuse_by_gap_reason.items())
        ),
        "distinct_reused_historical_symbol_count": len(
            {row.historical_symbol for row in reused}
        ),
        "distinct_remaining_historical_symbol_count": len(
            {row["historical_symbol"] for row in remaining}
        ),
        "inputs": {
            "shares_gap_queue": {
                "path": str(shares_gap_queue_path),
                "sha256": _sha256(shares_gap_queue_path),
            },
            "canonical_g4_shares": {
                "path": str(canonical_g4_shares_path),
                "sha256": _sha256(canonical_g4_shares_path),
            },
        },
        "outputs": {
            "cross_date_g4_reuse": str(reuse_path),
            "remaining_acquisition_queue": str(remaining_path),
            "summary": str(summary_path),
        },
        "policy": {
            "canonical_anchor_trade_date_must_precede_target": True,
            "fact_date_must_not_exceed_target": True,
            "target_max_staleness_enforced": True,
            "available_at_must_not_exceed_g5_cutoff": True,
            "latest_admissible_fact_date_selected": True,
            "conflicting_latest_fact_values_fail_closed": True,
            "canonical_g4_coverage_unchanged": True,
            "canonical_g5_readiness_unchanged": True,
            "reuse_rows_are_g5_evidence": False,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reuse admissible earlier canonical G4 point-in-time shares facts for "
            "G5 control-history shares gaps without modifying canonical G4/G5 state."
        )
    )
    parser.add_argument("--shares-gap-queue", type=Path, required=True)
    parser.add_argument("--canonical-g4-shares", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        shares_gap_queue_path=args.shares_gap_queue,
        canonical_g4_shares_path=args.canonical_g4_shares,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
