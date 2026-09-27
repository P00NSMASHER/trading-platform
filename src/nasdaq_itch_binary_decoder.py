from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator

SCHEMA_VERSION = "1.0.0"
SUPPORTED_VERSIONS = {"4.1", "5.0"}
SUPPORTED_ORDER_FLOW_TYPES = {"A", "F", "E", "C", "X", "D", "U", "B"}

# Exact payload lengths from the Nasdaq TotalView-ITCH specifications.
EXPECTED_LENGTHS = {
    "4.1": {"T": 5, "A": 30, "F": 34, "E": 25, "C": 30, "X": 17, "D": 13, "U": 29, "B": 13},
    "5.0": {"A": 36, "F": 40, "E": 31, "C": 36, "X": 23, "D": 19, "U": 35, "B": 19},
}

OUTPUT_FIELDS = [
    "timestamp",
    "timestamp_ns_since_midnight",
    "message_type",
    "symbol",
    "order_reference",
    "side",
    "shares",
    "price",
    "executed_shares",
    "execution_price",
    "match_number",
    "printable",
    "cancelled_shares",
    "new_order_reference",
    "source_binary_offset",
    "source_message_index",
]

SPEC_REFERENCES = {
    "binaryfile": "https://nasdaqtrader.com/content/technicalSupport/specifications/dataproducts/binaryfile.pdf",
    "4.1": "https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTV-ITCH-V4_1.pdf",
    "5.0": "https://nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _open_binary(path: Path) -> BinaryIO:
    return gzip.open(path, "rb") if path.suffix.lower() == ".gz" else path.open("rb")


def _u(payload: bytes, offset: int, length: int) -> int:
    end = offset + length
    if offset < 0 or end > len(payload):
        raise ValueError(f"field outside payload: offset={offset} length={length} payload={len(payload)}")
    return int.from_bytes(payload[offset:end], "big", signed=False)


def _alpha(payload: bytes, offset: int, length: int = 1) -> str:
    end = offset + length
    if offset < 0 or end > len(payload):
        raise ValueError(f"alpha field outside payload: offset={offset} length={length}")
    try:
        return payload[offset:end].decode("ascii").rstrip(" ")
    except UnicodeDecodeError as exc:
        raise ValueError("non-ASCII alpha field") from exc


def _price4(raw: int) -> str:
    return (f"{raw / 10000:.4f}").rstrip("0").rstrip(".")


def _timestamp_string(trade_date: date, ns_since_midnight: int) -> str:
    if ns_since_midnight < 0 or ns_since_midnight >= 86_400_000_000_000:
        raise ValueError(f"timestamp outside trading day: {ns_since_midnight}")
    sec, ns = divmod(ns_since_midnight, 1_000_000_000)
    hour, sec = divmod(sec, 3600)
    minute, sec = divmod(sec, 60)
    # Existing pipeline is microsecond based. The exact nanoseconds remain in the
    # timestamp_ns_since_midnight provenance column and file ordering is retained.
    micro = ns // 1000
    return f"{trade_date.isoformat()} {hour:02d}:{minute:02d}:{sec:02d}.{micro:06d}"


def iter_binaryfile_messages(path: Path) -> Iterator[tuple[int, int, bytes]]:
    """Yield (message_index, binary_offset, payload) from a Nasdaq BinaryFILE.

    BinaryFILE uses a two-byte big-endian payload length. A zero-length frame is
    the required end-of-session marker. Missing/truncated framing fails closed.
    """
    with _open_binary(path) as f:
        offset = 0
        index = 0
        terminator_seen = False
        while True:
            header = f.read(2)
            if header == b"":
                break
            if len(header) != 2:
                raise ValueError(f"truncated BinaryFILE length prefix at offset {offset}")
            length = int.from_bytes(header, "big")
            frame_offset = offset
            offset += 2
            if length == 0:
                terminator_seen = True
                trailing = f.read(1)
                if trailing:
                    raise ValueError("BinaryFILE contains bytes after zero-length terminator")
                break
            payload = f.read(length)
            if len(payload) != length:
                raise ValueError(
                    f"truncated BinaryFILE payload at offset {frame_offset}: "
                    f"expected={length} actual={len(payload)}"
                )
            offset += length
            index += 1
            yield index, frame_offset, payload
        if not terminator_seen:
            raise ValueError("BinaryFILE missing required zero-length end-of-session message")


def _blank_row(*, index: int, offset: int, message_type: str, timestamp: str, timestamp_ns: int) -> dict[str, str]:
    row = {name: "" for name in OUTPUT_FIELDS}
    row.update({
        "timestamp": timestamp,
        "timestamp_ns_since_midnight": str(timestamp_ns),
        "message_type": message_type,
        "source_binary_offset": str(offset),
        "source_message_index": str(index),
    })
    return row


def _require_length(version: str, message_type: str, payload: bytes) -> None:
    expected = EXPECTED_LENGTHS[version].get(message_type)
    if expected is not None and len(payload) != expected:
        raise ValueError(
            f"ITCH {version} {message_type} length mismatch: expected={expected} actual={len(payload)}"
        )


def _decode_v50(
    payload: bytes,
    *,
    trade_date: date,
    index: int,
    offset: int,
) -> dict[str, str] | None:
    message_type = _alpha(payload, 0)
    if message_type not in SUPPORTED_ORDER_FLOW_TYPES:
        return None
    _require_length("5.0", message_type, payload)
    timestamp_ns = _u(payload, 5, 6)
    row = _blank_row(
        index=index,
        offset=offset,
        message_type=message_type,
        timestamp=_timestamp_string(trade_date, timestamp_ns),
        timestamp_ns=timestamp_ns,
    )
    if message_type in {"A", "F"}:
        row.update({
            "order_reference": str(_u(payload, 11, 8)),
            "side": _alpha(payload, 19),
            "shares": str(_u(payload, 20, 4)),
            "symbol": _alpha(payload, 24, 8),
            "price": _price4(_u(payload, 32, 4)),
        })
    elif message_type == "E":
        row.update({
            "order_reference": str(_u(payload, 11, 8)),
            "executed_shares": str(_u(payload, 19, 4)),
            "match_number": str(_u(payload, 23, 8)),
            "printable": "Y",
        })
    elif message_type == "C":
        row.update({
            "order_reference": str(_u(payload, 11, 8)),
            "executed_shares": str(_u(payload, 19, 4)),
            "match_number": str(_u(payload, 23, 8)),
            "printable": _alpha(payload, 31),
            "execution_price": _price4(_u(payload, 32, 4)),
        })
    elif message_type == "X":
        row.update({
            "order_reference": str(_u(payload, 11, 8)),
            "cancelled_shares": str(_u(payload, 19, 4)),
        })
    elif message_type == "D":
        row["order_reference"] = str(_u(payload, 11, 8))
    elif message_type == "U":
        row.update({
            "order_reference": str(_u(payload, 11, 8)),
            "new_order_reference": str(_u(payload, 19, 8)),
            "shares": str(_u(payload, 27, 4)),
            "price": _price4(_u(payload, 31, 4)),
        })
    elif message_type == "B":
        row["match_number"] = str(_u(payload, 11, 8))
    return row


def _decode_v41(
    payload: bytes,
    *,
    trade_date: date,
    current_seconds: int | None,
    index: int,
    offset: int,
) -> tuple[dict[str, str] | None, int | None]:
    message_type = _alpha(payload, 0)
    if message_type == "T":
        _require_length("4.1", message_type, payload)
        seconds = _u(payload, 1, 4)
        if seconds >= 86_400:
            raise ValueError(f"ITCH 4.1 Timestamp-Seconds outside day: {seconds}")
        return None, seconds

    if message_type not in SUPPORTED_ORDER_FLOW_TYPES:
        return None, current_seconds
    _require_length("4.1", message_type, payload)
    if current_seconds is None:
        raise ValueError(
            f"ITCH 4.1 {message_type} encountered before Timestamp-Seconds message"
        )
    nanos = _u(payload, 1, 4)
    if nanos >= 1_000_000_000:
        raise ValueError(f"ITCH 4.1 nanoseconds portion invalid: {nanos}")
    timestamp_ns = current_seconds * 1_000_000_000 + nanos
    row = _blank_row(
        index=index,
        offset=offset,
        message_type=message_type,
        timestamp=_timestamp_string(trade_date, timestamp_ns),
        timestamp_ns=timestamp_ns,
    )
    if message_type in {"A", "F"}:
        row.update({
            "order_reference": str(_u(payload, 5, 8)),
            "side": _alpha(payload, 13),
            "shares": str(_u(payload, 14, 4)),
            "symbol": _alpha(payload, 18, 8),
            "price": _price4(_u(payload, 26, 4)),
        })
    elif message_type == "E":
        row.update({
            "order_reference": str(_u(payload, 5, 8)),
            "executed_shares": str(_u(payload, 13, 4)),
            "match_number": str(_u(payload, 17, 8)),
            "printable": "Y",
        })
    elif message_type == "C":
        row.update({
            "order_reference": str(_u(payload, 5, 8)),
            "executed_shares": str(_u(payload, 13, 4)),
            "match_number": str(_u(payload, 17, 8)),
            "printable": _alpha(payload, 25),
            "execution_price": _price4(_u(payload, 26, 4)),
        })
    elif message_type == "X":
        row.update({
            "order_reference": str(_u(payload, 5, 8)),
            "cancelled_shares": str(_u(payload, 13, 4)),
        })
    elif message_type == "D":
        row["order_reference"] = str(_u(payload, 5, 8))
    elif message_type == "U":
        row.update({
            "order_reference": str(_u(payload, 5, 8)),
            "new_order_reference": str(_u(payload, 13, 8)),
            "shares": str(_u(payload, 21, 4)),
            "price": _price4(_u(payload, 25, 4)),
        })
    elif message_type == "B":
        row["match_number"] = str(_u(payload, 5, 8))
    return row, current_seconds


def decode_binaryfile(
    input_path: Path,
    *,
    version: str,
    trade_date: date,
    output_csv: Path,
    manifest_path: Path | None = None,
) -> dict:
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported ITCH version {version!r}; expected 4.1 or 5.0")
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    rows: list[dict[str, str]] = []
    all_types: Counter[str] = Counter()
    decoded_types: Counter[str] = Counter()
    current_seconds: int | None = None
    message_count = 0

    for index, offset, payload in iter_binaryfile_messages(input_path):
        if not payload:
            raise ValueError("empty non-terminator BinaryFILE payload")
        message_type = _alpha(payload, 0)
        all_types[message_type] += 1
        message_count += 1
        if version == "5.0":
            row = _decode_v50(payload, trade_date=trade_date, index=index, offset=offset)
        else:
            row, current_seconds = _decode_v41(
                payload,
                trade_date=trade_date,
                current_seconds=current_seconds,
                index=index,
                offset=offset,
            )
        if row is not None:
            rows.append(row)
            decoded_types[message_type] += 1

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Spec-bound translation of licensed Nasdaq Historical TotalView-ITCH "
            "BinaryFILE order-flow messages into the canonical research CSV schema."
        ),
        "research_use_only": True,
        "itch_version": version,
        "trade_date": trade_date.isoformat(),
        "input_path": str(input_path),
        "input_sha256": _sha256(input_path),
        "input_size_bytes": input_path.stat().st_size,
        "output_path": str(output_csv),
        "output_sha256": _sha256(output_csv),
        "binaryfile_terminator_required": True,
        "message_count": message_count,
        "decoded_row_count": len(rows),
        "skipped_message_count": message_count - sum(decoded_types.values()) - (
            all_types.get("T", 0) if version == "4.1" else 0
        ),
        "all_message_type_counts": dict(sorted(all_types.items())),
        "decoded_message_type_counts": dict(sorted(decoded_types.items())),
        "supported_order_flow_types": sorted(SUPPORTED_ORDER_FLOW_TYPES),
        "spec_references": {
            "binaryfile": SPEC_REFERENCES["binaryfile"],
            "itch": SPEC_REFERENCES[version],
        },
        "timestamp_policy": (
            "Exact nanoseconds since midnight are preserved in timestamp_ns_since_midnight. "
            "timestamp is emitted at microsecond precision for the existing timezone-aware pipeline."
        ),
        "unsupported_message_policy": (
            "Unsupported ITCH message types are counted and skipped; known supported message "
            "types with unexpected lengths fail closed."
        ),
        "prohibited_outputs": [
            "BUY", "SELL", "expected_return", "target_price",
            "position_size", "order", "execution_instruction",
        ],
    }
    if manifest_path is not None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(
        description="Decode Nasdaq Historical TotalView-ITCH 4.1/5.0 BinaryFILE order-flow messages."
    )
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--version", choices=sorted(SUPPORTED_VERSIONS), required=True)
    p.add_argument("--trade-date", type=date.fromisoformat, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--manifest", type=Path)
    args = p.parse_args()
    result = decode_binaryfile(
        args.input,
        version=args.version,
        trade_date=args.trade_date,
        output_csv=args.output,
        manifest_path=args.manifest,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
