from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path


DEFAULT_QUEUE = Path("data/processed/security_identity_real/security_identity_acquisition_queue.csv")

EVIDENCE_FIELDS = [
    "evidence_id",
    "permno",
    "historical_symbol",
    "market_identifier",
    "valid_from",
    "valid_through",
    "evidence_lane",
    "source_reference",
    "authorization_reference",
    "research_use_only",
]


class StocknamesIdentityAdapterError(ValueError):
    pass


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(handle)
        ]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_permno(value: str) -> str:
    raw = str(value or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw


def _field(row: dict[str, str], *names: str) -> str:
    lowered = {str(key).lower(): str(value or "").strip() for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower(), "")
        if value:
            return value
    return ""


def _parse_date(value: str, *, label: str, allow_open_end: bool = False) -> str:
    raw = str(value or "").strip()
    if not raw and allow_open_end:
        return "9999-12-31"
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError as exc:
        raise StocknamesIdentityAdapterError(
            f"{label} must be a valid YYYY-MM-DD date"
        ) from exc


def normalize_stocknames(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for i, row in enumerate(rows, 2):
        permno = _normalize_permno(_field(row, "permno"))
        ticker = _field(row, "ticker", "tsymbol").upper()
        namedt_raw = _field(row, "namedt")
        nameend_raw = _field(row, "nameenddt", "nameendt")
        if not permno:
            raise StocknamesIdentityAdapterError(
                f"stocknames row {i}: PERMNO is required"
            )
        if not namedt_raw:
            raise StocknamesIdentityAdapterError(
                f"stocknames row {i}: NAMEDT is required"
            )
        namedt = _parse_date(namedt_raw, label=f"stocknames row {i} NAMEDT")
        nameend = _parse_date(
            nameend_raw,
            label=f"stocknames row {i} NAMEENDDT",
            allow_open_end=True,
        )
        if nameend < namedt:
            raise StocknamesIdentityAdapterError(
                f"stocknames row {i}: NAMEENDDT precedes NAMEDT"
            )
        normalized.append(
            {
                "permno": permno,
                "ticker": ticker,
                "namedt": namedt,
                "nameenddt": nameend,
            }
        )
    return normalized


def _evidence_id(request_id: str, source_sha256: str) -> str:
    payload = f"{request_id}|{source_sha256}".encode("utf-8")
    return "SID-STOCKNAMES-" + hashlib.sha256(payload).hexdigest()[:16].upper()


def build_evidence(
    queue_rows: list[dict[str, str]],
    stocknames_rows: list[dict[str, str]],
    *,
    source_sha256: str,
    authorization_reference: str,
) -> tuple[list[dict[str, str]], dict]:
    authorization_reference = authorization_reference.strip()
    if not authorization_reference:
        raise StocknamesIdentityAdapterError(
            "authorization_reference must be nonblank"
        )
    if len(source_sha256) != 64 or any(
        char not in "0123456789abcdefABCDEF" for char in source_sha256
    ):
        raise StocknamesIdentityAdapterError(
            "source_sha256 must be a 64-character hexadecimal SHA-256"
        )

    names = normalize_stocknames(stocknames_rows)
    by_permno: dict[str, list[dict[str, str]]] = {}
    for row in names:
        by_permno.setdefault(row["permno"], []).append(row)

    evidence: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    seen_requests: set[str] = set()
    counts = {
        "queue_requests": len(queue_rows),
        "evidence_rows_emitted": 0,
        "no_permno_history": 0,
        "no_active_history": 0,
        "historical_symbol_mismatch": 0,
        "ambiguous_active_identifiers": 0,
    }

    for i, raw in enumerate(queue_rows, 2):
        request_id = raw.get("request_id", "").strip()
        permno = _normalize_permno(raw.get("permno", ""))
        symbol = raw.get("historical_symbol", "").strip().upper()
        trade_date = raw.get("trade_date", "").strip()
        if not request_id or request_id in seen_requests:
            raise StocknamesIdentityAdapterError(
                f"queue row {i}: request_id must be unique and nonblank"
            )
        seen_requests.add(request_id)
        if not permno or not symbol:
            raise StocknamesIdentityAdapterError(
                f"queue row {i}: PERMNO and historical_symbol are required"
            )
        trade_date = _parse_date(
            trade_date,
            label=f"queue row {i} trade_date",
        )
        if raw.get("research_use_only", "").strip() != "1":
            raise StocknamesIdentityAdapterError(
                f"queue row {i}: research_use_only must equal 1"
            )

        history = by_permno.get(permno, [])
        if not history:
            counts["no_permno_history"] += 1
            unresolved.append(
                {
                    "request_id": request_id,
                    "permno": permno,
                    "historical_symbol": symbol,
                    "trade_date": trade_date,
                    "reason": "NO_PERMNO_HISTORY",
                }
            )
            continue

        active = [
            row
            for row in history
            if row["namedt"] <= trade_date <= row["nameenddt"]
        ]
        if not active:
            counts["no_active_history"] += 1
            unresolved.append(
                {
                    "request_id": request_id,
                    "permno": permno,
                    "historical_symbol": symbol,
                    "trade_date": trade_date,
                    "reason": "NO_ACTIVE_HISTORY",
                }
            )
            continue

        active_identifiers = {row["ticker"] for row in active if row["ticker"]}
        if len(active_identifiers) > 1:
            counts["ambiguous_active_identifiers"] += 1
            unresolved.append(
                {
                    "request_id": request_id,
                    "permno": permno,
                    "historical_symbol": symbol,
                    "trade_date": trade_date,
                    "reason": "AMBIGUOUS_ACTIVE_IDENTIFIERS",
                }
            )
            continue

        matching = [row for row in active if row["ticker"] == symbol]
        if not matching:
            counts["historical_symbol_mismatch"] += 1
            unresolved.append(
                {
                    "request_id": request_id,
                    "permno": permno,
                    "historical_symbol": symbol,
                    "trade_date": trade_date,
                    "reason": "HISTORICAL_SYMBOL_MISMATCH",
                }
            )
            continue

        evidence.append(
            {
                "evidence_id": _evidence_id(request_id, source_sha256.lower()),
                "permno": permno,
                "historical_symbol": symbol,
                "market_identifier": symbol,
                "valid_from": trade_date,
                "valid_through": trade_date,
                "evidence_lane": "LICENSED_STABLE_ID_MASTER",
                "source_reference": f"stocknames-sha256:{source_sha256.lower()}",
                "authorization_reference": authorization_reference,
                "research_use_only": "1",
            }
        )

    evidence.sort(key=lambda row: (row["permno"], row["valid_from"], row["evidence_id"]))
    unresolved.sort(
        key=lambda row: (row["permno"], row["trade_date"], row["request_id"])
    )
    counts["evidence_rows_emitted"] = len(evidence)
    summary = {
        "schema_version": "1",
        "purpose": (
            "Convert an explicitly authorized dated PERMNO/ticker name-history extract "
            "into the canonical stable-ID evidence schema without backward ticker inference."
        ),
        "research_use_only": True,
        "source_sha256": source_sha256.lower(),
        "authorization_reference_present": True,
        "counts": counts,
        "all_queue_requests_evidence_ready": len(evidence) == len(queue_rows),
        "policy": {
            "required_source_fields": [
                "permno",
                "ticker",
                "namedt",
                "nameenddt_or_nameendt",
            ],
            "exact_permno_required": True,
            "exact_historical_symbol_required": True,
            "requested_date_must_be_inside_name_interval": True,
            "ambiguous_active_identifiers_fail_closed": True,
            "undated_or_current_ticker_substitution_allowed": False,
            "coverage_change": False,
        },
        "unresolved": unresolved,
    }
    return evidence, summary


def render_evidence(rows: list[dict[str, str]]) -> str:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=EVIDENCE_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def render_summary(summary: dict) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert an authorized CRSP-style stocknames history into dated stable-ID "
            "evidence for the canonical identity queue."
        )
    )
    parser.add_argument("--stocknames", type=Path, required=True)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args()

    stocknames_path = args.stocknames.expanduser().resolve()
    evidence, summary = build_evidence(
        read_csv(args.queue),
        read_csv(stocknames_path),
        source_sha256=sha256_file(stocknames_path),
        authorization_reference=args.authorization_reference,
    )
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(render_evidence(evidence), encoding="utf-8")
    args.summary_output.write_text(render_summary(summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
