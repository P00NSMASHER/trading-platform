from __future__ import annotations

import argparse
import csv
import hashlib
import io
from pathlib import Path


QUEUE_FIELDS = {
    "request_id",
    "permno",
    "gvkey",
    "historical_symbol",
    "trade_date",
    "event_ids",
}
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


class StableIdEvidenceError(ValueError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
        ]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_columns(rows: list[dict[str, str]], required: set[str], *, label: str) -> None:
    if not rows:
        raise StableIdEvidenceError(f"{label} is empty")
    missing = required - set(rows[0])
    if missing:
        raise StableIdEvidenceError(f"{label} missing columns: {sorted(missing)}")


def build_evidence(
    queue_rows: list[dict[str, str]],
    stockname_rows: list[dict[str, str]],
    *,
    source_reference: str,
    authorization_reference: str,
    evidence_lane: str = "LICENSED_STABLE_ID_MASTER",
) -> tuple[list[dict[str, str]], dict]:
    _require_columns(queue_rows, QUEUE_FIELDS, label="acquisition queue")
    _require_columns(
        stockname_rows,
        {"permno", "ticker", "namedt", "nameendt"},
        label="stock-name history",
    )
    if evidence_lane not in {"LICENSED_STABLE_ID_MASTER", "AUTHORIZED_MARKET_SECURITY_MASTER"}:
        raise StableIdEvidenceError("evidence_lane is not closing-authorized")
    if not source_reference.strip():
        raise StableIdEvidenceError("source_reference must be nonblank")
    if not authorization_reference.strip():
        raise StableIdEvidenceError("authorization_reference must be nonblank")

    by_permno: dict[str, list[dict[str, str]]] = {}
    for index, row in enumerate(stockname_rows, 2):
        permno = row["permno"].strip()
        ticker = row["ticker"].strip().upper()
        namedt = row["namedt"].strip()
        nameendt = row["nameendt"].strip()
        if not permno or not ticker or len(namedt) != 10:
            continue
        if nameendt and len(nameendt) != 10:
            raise StableIdEvidenceError(f"stock-name row {index}: invalid nameendt")
        by_permno.setdefault(permno, []).append({
            **row,
            "ticker": ticker,
            "namedt": namedt,
            "nameendt": nameendt,
            "__row": str(index),
        })

    selected: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    uncovered: list[dict[str, str]] = []
    ambiguous: list[dict[str, str]] = []

    for request in queue_rows:
        permno = request["permno"].strip()
        symbol = request["historical_symbol"].strip().upper()
        trade_date = request["trade_date"].strip()
        if not permno or not symbol or len(trade_date) != 10:
            raise StableIdEvidenceError(
                f"queue request {request.get('request_id', '')}: incomplete identity"
            )

        candidates = [
            row
            for row in by_permno.get(permno, [])
            if row["ticker"] == symbol
            and row["namedt"] <= trade_date
            and (not row["nameendt"] or trade_date <= row["nameendt"])
        ]
        if len(candidates) == 0:
            uncovered.append({
                "request_id": request["request_id"],
                "permno": permno,
                "historical_symbol": symbol,
                "trade_date": trade_date,
            })
            continue
        if len(candidates) > 1:
            distinct = {
                (row["namedt"], row["nameendt"], row["ticker"])
                for row in candidates
            }
            if len(distinct) > 1:
                ambiguous.append({
                    "request_id": request["request_id"],
                    "permno": permno,
                    "historical_symbol": symbol,
                    "trade_date": trade_date,
                    "candidate_rows": ";".join(sorted(row["__row"] for row in candidates)),
                })
                continue
        row = sorted(
            candidates,
            key=lambda item: (item["namedt"], item["nameendt"], item["__row"]),
        )[0]
        valid_through = row["nameendt"] or "9999-12-31"
        key = (permno, symbol, row["ticker"], row["namedt"], valid_through)
        selected[key] = {
            "permno": permno,
            "historical_symbol": symbol,
            "market_identifier": row["ticker"],
            "valid_from": row["namedt"],
            "valid_through": valid_through,
            "source_row": row["__row"],
        }

    if uncovered or ambiguous:
        raise StableIdEvidenceError(
            f"stock-name history does not close queue: uncovered={len(uncovered)} "
            f"ambiguous={len(ambiguous)}"
        )

    evidence: list[dict[str, str]] = []
    for key in sorted(selected):
        row = selected[key]
        identity = "|".join([
            row["permno"],
            row["historical_symbol"],
            row["market_identifier"],
            row["valid_from"],
            row["valid_through"],
            source_reference,
        ])
        evidence.append({
            "evidence_id": "SID-EVID-" + _sha256_text(identity)[:20].upper(),
            "permno": row["permno"],
            "historical_symbol": row["historical_symbol"],
            "market_identifier": row["market_identifier"],
            "valid_from": row["valid_from"],
            "valid_through": row["valid_through"],
            "evidence_lane": evidence_lane,
            "source_reference": f"{source_reference}#row={row['source_row']}",
            "authorization_reference": authorization_reference,
            "research_use_only": "1",
        })

    summary = {
        "queue_request_count": len(queue_rows),
        "evidence_interval_count": len(evidence),
        "unique_permno_count": len({row["permno"] for row in evidence}),
        "uncovered_request_count": 0,
        "ambiguous_request_count": 0,
        "evidence_lane": evidence_lane,
        "source_reference": source_reference,
        "authorization_reference": authorization_reference,
        "ready_for_identity_gate_ingest": True,
    }
    return evidence, summary


def render_evidence(rows: list[dict[str, str]]) -> str:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=EVIDENCE_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build minimal dated stable-ID evidence from an authorized stock-name history extract."
    )
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--stocknames", type=Path, required=True)
    parser.add_argument("--source-reference", required=True)
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument(
        "--evidence-lane",
        choices=["LICENSED_STABLE_ID_MASTER", "AUTHORIZED_MARKET_SECURITY_MASTER"],
        default="LICENSED_STABLE_ID_MASTER",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    evidence, summary = build_evidence(
        _read_csv(args.queue),
        _read_csv(args.stocknames),
        source_reference=args.source_reference,
        authorization_reference=args.authorization_reference,
        evidence_lane=args.evidence_lane,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_evidence(evidence), encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
