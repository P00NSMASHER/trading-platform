from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Version 2 writes fixed-width microseconds instead of truncating to milliseconds.
# Legacy v1 tapes/checkpoints must be regenerated from original inputs, not relabeled.
SCHEMA_VERSION = "2.0.0"
PROHIBITED_OUTPUTS = [
    "BUY", "SELL", "expected_return", "target_price", "position_size",
    "order", "execution_instruction", "trade_direction",
]
REQUIRED_FIELDS = {
    "event_id", "event_time_utc", "available_at_utc", "source_name",
    "source_sequence", "event_type", "payload_sha256", "research_use_only",
}


def _clean(v: str | None) -> str:
    return (v or "").strip()


def _parse_ts(v: str, field: str) -> datetime:
    value = _clean(v)
    if not value:
        raise ValueError(f"{field} is required")
    # datetime cannot represent sub-microsecond instants. Reject excess precision
    # before parsing, including comma fractions, rather than silently truncating it.
    if re.search(r"[.,][0-9]{7}", value):
        raise ValueError(f"{field} exceeds supported microsecond precision (maximum 6 fractional digits)")
    # Fractional offsets are outside this tape's contract; some ISO parsers erase
    # sub-second zero-hour offsets. Never silently change an instant at a cutoff.
    if re.search(r"[+-][0-9:]+[.,][0-9]+$", value):
        raise ValueError(f"{field}: fractional UTC offsets are unsupported")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return dt.astimezone(timezone.utc)


def _fmt_ts(dt: datetime) -> str:
    # Fixed-width UTC retains every supported digit and is chronologically sortable.
    # Zero padding is an encoding choice, not a claim about source clock accuracy.
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_event(row: dict[str, Any]) -> bytes:
    body = {
        "event_id": row["event_id"],
        "event_time_utc": row["event_time_utc"],
        "available_at_utc": row["available_at_utc"],
        "replay_time_utc": row["replay_time_utc"],
        "source_name": row["source_name"],
        "source_sequence": row["source_sequence"],
        "event_type": row["event_type"],
        "payload_sha256": row["payload_sha256"],
    }
    return (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _validate_payload_hash(v: str) -> str:
    value = _clean(v).lower()
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("payload_sha256 must be a 64-character lowercase/uppercase hex digest")
    return value


def load_events(paths: Iterable[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in paths:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            missing = REQUIRED_FIELDS.difference(reader.fieldnames or [])
            if missing:
                raise ValueError(f"event source {path} missing columns: {sorted(missing)}")
            for line_no, raw in enumerate(reader, 2):
                event_id = _clean(raw.get("event_id"))
                if not event_id or event_id in seen_ids:
                    raise ValueError(f"event source {path} row {line_no}: missing/duplicate event_id")
                source_name = _clean(raw.get("source_name"))
                event_type = _clean(raw.get("event_type"))
                if not source_name or not event_type:
                    raise ValueError(f"event source {path} row {line_no}: source_name/event_type required")
                try:
                    seq = int(_clean(raw.get("source_sequence")))
                except Exception as exc:
                    raise ValueError(f"event source {path} row {line_no}: invalid source_sequence") from exc
                if seq < 0:
                    raise ValueError(f"event source {path} row {line_no}: negative source_sequence")
                if _clean(raw.get("research_use_only")).lower() not in {"1", "true"}:
                    raise ValueError(f"event source {path} row {line_no}: research_use_only must be true")
                event_time = _parse_ts(raw.get("event_time_utc", ""), "event_time_utc")
                available_at = _parse_ts(raw.get("available_at_utc", ""), "available_at_utc")
                # A historical record cannot enter replay before both the event occurred and
                # the source says it was available. This is the point-in-time boundary.
                replay_time = max(event_time, available_at)
                rows.append({
                    "event_id": event_id,
                    "event_time_utc": _fmt_ts(event_time),
                    "available_at_utc": _fmt_ts(available_at),
                    "replay_time_utc": _fmt_ts(replay_time),
                    "source_name": source_name,
                    "source_sequence": seq,
                    "event_type": event_type,
                    "payload_sha256": _validate_payload_hash(raw.get("payload_sha256", "")),
                    "research_use_only": 1,
                })
                seen_ids.add(event_id)
        inputs.append({"path": str(path), "sha256": _sha256(path)})
    if not rows:
        raise ValueError("event replay requires at least one event")
    return rows, inputs


def build_event_tape(
    *,
    input_paths: Iterable[Path],
    output_dir: Path,
    as_of_utc: str | None = None,
    checkpoint_size: int = 1000,
) -> dict[str, Any]:
    if type(checkpoint_size) is not int or checkpoint_size < 1:
        raise ValueError("checkpoint_size must be a positive integer")
    rows, inputs = load_events(input_paths)
    as_of = _parse_ts(as_of_utc, "as_of_utc") if as_of_utc else None
    eligible: list[dict[str, Any]] = []
    deferred = 0
    for row in rows:
        replay_dt = _parse_ts(row["replay_time_utc"], "replay_time_utc")
        if as_of is not None and replay_dt > as_of:
            deferred += 1
        else:
            eligible.append(row)

    eligible.sort(key=lambda r: (
        r["replay_time_utc"], r["event_time_utc"], r["source_name"],
        r["source_sequence"], r["event_id"],
    ))

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tape_path = output_dir / "event_tape.csv"
    fields = [
        "ordinal", "event_id", "event_time_utc", "available_at_utc", "replay_time_utc",
        "source_name", "source_sequence", "event_type", "payload_sha256", "research_use_only",
    ]
    stream_hasher = hashlib.sha256()
    checkpoints: list[dict[str, Any]] = []
    with tape_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for ordinal, row in enumerate(eligible, 1):
            stream_hasher.update(_canonical_event(row))
            writer.writerow({"ordinal": ordinal, **row})
            if ordinal % checkpoint_size == 0 or ordinal == len(eligible):
                checkpoints.append({
                    "ordinal": ordinal,
                    "event_id": row["event_id"],
                    "replay_time_utc": row["replay_time_utc"],
                    "prefix_semantic_sha256": stream_hasher.hexdigest(),
                })

    checkpoint_path = output_dir / "event_tape_checkpoints.json"
    checkpoint_path.write_text(json.dumps(checkpoints, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sources = Counter(row["source_name"] for row in eligible)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "deterministic point-in-time historical surveillance event replay",
        "research_use_only": True,
        "event_ordering": [
            "replay_time_utc=max(event_time_utc,available_at_utc)",
            "event_time_utc", "source_name", "source_sequence", "event_id",
        ],
        "timestamp_encoding": {
            "timezone": "UTC",
            "fractional_second_digits": 6,
            "submicrosecond_input_policy": "reject",
            "fractional_utc_offset_policy": "reject",
            "precision_does_not_imply_accuracy": True,
        },
        "point_in_time_policy": {
            "event_not_visible_before_event_time": True,
            "event_not_visible_before_source_availability": True,
            "as_of_filter_applied": as_of is not None,
            "as_of_utc": None if as_of is None else _fmt_ts(as_of),
        },
        "counts": {
            "input_events": len(rows),
            "replayed_events": len(eligible),
            "deferred_due_as_of": deferred,
            "sources": dict(sorted(sources.items())),
        },
        "inputs": inputs,
        "outputs": {
            "event_tape": "event_tape.csv",
            "event_tape_sha256": _sha256(tape_path),
            "event_tape_checkpoints": "event_tape_checkpoints.json",
            "checkpoints_sha256": _sha256(checkpoint_path),
            "semantic_event_stream_sha256": stream_hasher.hexdigest(),
        },
        "architecture_origin": {
            "concepts": ["event-driven replay", "deterministic event ordering", "point-in-time availability"],
            "inspiration": ["QuantConnect Lean", "Zipline"],
            "third_party_source_copied_or_vendored": False,
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
        "warning": "This tape reconstructs historical surveillance state only and has no brokerage, execution, expected-return, or position-sizing semantics.",
    }
    (output_dir / "event_tape_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def _args():
    p = argparse.ArgumentParser(description="Build a deterministic point-in-time surveillance event tape")
    p.add_argument("--input", action="append", type=Path, required=True, dest="inputs")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--as-of-utc")
    p.add_argument("--checkpoint-size", type=int, default=1000)
    return p.parse_args()


if __name__ == "__main__":
    args = _args()
    print(json.dumps(build_event_tape(
        input_paths=args.inputs,
        output_dir=args.output_dir,
        as_of_utc=args.as_of_utc,
        checkpoint_size=args.checkpoint_size,
    ), indent=2))
