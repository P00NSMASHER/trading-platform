from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class IdentityIntervalRequest:
    request_id: str
    historical_symbol: str
    required_date_count: int
    first_required_date: str
    last_required_date: str
    required_dates: str
    source_statuses: str
    canonical_permno_hint: str
    samplefirms_permno_hint: str
    primary_lane: str = "LICENSED_STABLE_ID_MASTER"
    secondary_lane: str = "AUTHORIZED_MARKET_SECURITY_MASTER"
    status: str = "INTERVAL_EVIDENCE_REQUIRED"
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    return fields, rows


def _request_id(symbol: str, dates: list[str]) -> str:
    raw = f"{symbol}|{';'.join(dates)}".encode("utf-8")
    return "G5ID-" + hashlib.sha256(raw).hexdigest()[:16].upper()


def build(*, identity_queue_path: Path, output_dir: Path) -> dict:
    fields, rows = _read_csv(identity_queue_path)
    required = {
        "historical_symbol",
        "trade_date",
        "identity_status",
        "canonical_permno",
        "samplefirms_permno",
    }
    missing = required.difference(fields)
    if missing:
        raise ValueError(
            f"identity queue missing columns: {sorted(missing)}"
        )
    if not rows:
        raise ValueError("identity queue is empty")

    grouped: dict[str, dict] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        trade_date = row["trade_date"][:10]
        if not symbol or not trade_date:
            raise ValueError(
                f"identity row {row_no}: historical_symbol/trade_date required"
            )
        pair = (symbol, trade_date)
        if pair in seen_pairs:
            raise ValueError(
                f"duplicate identity requirement: {symbol}|{trade_date}"
            )
        seen_pairs.add(pair)

        bucket = grouped.setdefault(
            symbol,
            {
                "dates": set(),
                "statuses": set(),
                "canonical_permnos": set(),
                "sample_permnos": set(),
            },
        )
        bucket["dates"].add(trade_date)
        bucket["statuses"].add(row["identity_status"])
        if row["canonical_permno"]:
            bucket["canonical_permnos"].add(row["canonical_permno"])
        if row["samplefirms_permno"]:
            bucket["sample_permnos"].add(row["samplefirms_permno"])

    requests: list[IdentityIntervalRequest] = []
    for symbol in sorted(grouped):
        bucket = grouped[symbol]
        dates = sorted(bucket["dates"])
        canonical = sorted(bucket["canonical_permnos"])
        sample = sorted(bucket["sample_permnos"])
        if len(canonical) > 1:
            raise ValueError(
                f"conflicting canonical PERMNO hints for {symbol}: {canonical}"
            )
        if len(sample) > 1:
            raise ValueError(
                f"conflicting SampleFirms PERMNO hints for {symbol}: {sample}"
            )
        if canonical and sample and canonical[0] != sample[0]:
            raise ValueError(
                f"canonical/SampleFirms PERMNO hint conflict for {symbol}: "
                f"{canonical[0]} != {sample[0]}"
            )

        requests.append(
            IdentityIntervalRequest(
                request_id=_request_id(symbol, dates),
                historical_symbol=symbol,
                required_date_count=len(dates),
                first_required_date=dates[0],
                last_required_date=dates[-1],
                required_dates=";".join(dates),
                source_statuses=";".join(sorted(bucket["statuses"])),
                canonical_permno_hint=canonical[0] if canonical else "",
                samplefirms_permno_hint=sample[0] if sample else "",
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    request_path = output_dir / "g5_control_identity_interval_requests.csv"
    with request_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(IdentityIntervalRequest.__dataclass_fields__),
        )
        writer.writeheader()
        for row in requests:
            writer.writerow(asdict(row))

    total_required_dates = sum(row.required_date_count for row in requests)
    if total_required_dates != len(rows):
        raise ValueError("identity interval grouping lost or duplicated dates")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Compress date-level G5 control identity acquisition work into one "
            "request per historical symbol while preserving the exact required "
            "dates. A request asks an authorized stable-ID source for validity "
            "evidence covering those dates; the planner does not assume one "
            "continuous identity interval."
        ),
        "research_use_only": True,
        "date_level_identity_requirement_count": len(rows),
        "symbol_level_interval_request_count": len(requests),
        "request_compression_ratio": round(len(requests) / len(rows), 8),
        "required_date_count_reconciled": total_required_dates,
        "symbols_with_canonical_permno_hint": sum(
            bool(row.canonical_permno_hint) for row in requests
        ),
        "symbols_with_samplefirms_permno_hint": sum(
            bool(row.samplefirms_permno_hint) for row in requests
        ),
        "inputs": {
            "identity_queue_path": str(identity_queue_path),
            "identity_queue_sha256": _sha256(identity_queue_path),
        },
        "outputs": {
            "interval_requests": str(request_path),
        },
        "policy": {
            "one_request_per_symbol": True,
            "exact_required_dates_preserved": True,
            "continuous_validity_not_assumed": True,
            "authorized_stable_id_evidence_required": True,
            "request_rows_are_g5_evidence": False,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_control_identity_interval_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compress G5 date-level control identity gaps into symbol requests."
    )
    parser.add_argument("--identity-queue", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        identity_queue_path=args.identity_queue,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
