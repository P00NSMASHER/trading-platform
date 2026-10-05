from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path


DEFAULT_QUEUE = Path("data/processed/security_identity_real/security_identity_acquisition_queue.csv")
DEFAULT_EVENT_MAPPING = Path("data/processed/g2_vendor_requests/lseg_event_permno_ric_mapping.csv")

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

DIRECT_MAPPING_STATUS = "study_permno_linked_candidate"


class LsegIdentityBridgeError(ValueError):
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


def _split_rics(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(";") if item.strip()]


def _normalize_permno(value: str) -> str:
    raw = str(value or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw


def _evidence_id(request_id: str, ric: str, source_sha256: str) -> str:
    payload = f"{request_id}|{ric}|{source_sha256}".encode("utf-8")
    return "SID-LSEG-" + hashlib.sha256(payload).hexdigest()[:16].upper()


def build_direct_bridge_index(
    event_mapping: list[dict[str, str]],
) -> dict[tuple[str, str], str]:
    candidates: dict[tuple[str, str], set[str]] = {}
    for i, row in enumerate(event_mapping, 2):
        status = row.get("mapping_status", "")
        if status != DIRECT_MAPPING_STATUS:
            continue
        permno = _normalize_permno(row.get("PERMNO", ""))
        symbol = row.get("SYMBOL", "").upper()
        if not permno or not symbol:
            raise LsegIdentityBridgeError(
                f"event mapping row {i}: direct mapping requires PERMNO and SYMBOL"
            )
        for ric in _split_rics(row.get("candidate_rics", "")):
            candidates.setdefault((symbol, ric), set()).add(permno)

    out: dict[tuple[str, str], str] = {}
    for key, permnos in candidates.items():
        if len(permnos) != 1:
            raise LsegIdentityBridgeError(
                f"direct LSEG mapping {key[0]}/{key[1]} resolves to multiple PERMNOs: "
                f"{sorted(permnos)}"
            )
        out[key] = next(iter(permnos))
    return out


def build_evidence(
    validation_rows: list[dict[str, str]],
    queue_rows: list[dict[str, str]],
    event_mapping: list[dict[str, str]],
    *,
    source_sha256: str,
    authorization_reference: str,
) -> tuple[list[dict[str, str]], dict]:
    authorization_reference = authorization_reference.strip()
    if not authorization_reference:
        raise LsegIdentityBridgeError("authorization_reference must be nonblank")
    if len(source_sha256) != 64:
        raise LsegIdentityBridgeError("source_sha256 must be a 64-character SHA-256")

    bridge = build_direct_bridge_index(event_mapping)
    queue_by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    for i, row in enumerate(queue_rows, 2):
        permno = _normalize_permno(row.get("permno", ""))
        symbol = row.get("historical_symbol", "").upper()
        trade_date = row.get("trade_date", "")
        request_id = row.get("request_id", "")
        if not permno or not symbol or len(trade_date) != 10 or not request_id:
            raise LsegIdentityBridgeError(f"queue row {i}: required identity fields missing")
        key = (permno, symbol, trade_date)
        if key in queue_by_key:
            raise LsegIdentityBridgeError(f"duplicate queue identity request: {key}")
        queue_by_key[key] = row

    evidence_by_request: dict[str, dict[str, str]] = {}
    counts = {
        "validation_rows": len(validation_rows),
        "validated_single_candidate": 0,
        "direct_permno_bridge_eligible": 0,
        "not_direct_permno_bridged": 0,
        "not_in_identity_queue": 0,
        "nonclosing_validation_status": 0,
    }

    for i, row in enumerate(validation_rows, 2):
        status = row.get("validation_status", "")
        if status != "validated_single_candidate":
            counts["nonclosing_validation_status"] += 1
            continue
        counts["validated_single_candidate"] += 1

        trade_date = row.get("trade_date", "")
        symbol = row.get("historical_symbol", "").upper()
        ric = row.get("selected_ric", "")
        if len(trade_date) != 10 or not symbol or not ric:
            raise LsegIdentityBridgeError(
                f"validation row {i}: validated row lacks date, symbol, or selected_ric"
            )

        permno = bridge.get((symbol, ric))
        if permno is None:
            counts["not_direct_permno_bridged"] += 1
            continue

        queue_row = queue_by_key.get((permno, symbol, trade_date))
        if queue_row is None:
            counts["not_in_identity_queue"] += 1
            continue

        request_id = queue_row["request_id"]
        evidence = {
            "evidence_id": _evidence_id(request_id, ric, source_sha256),
            "permno": permno,
            "historical_symbol": symbol,
            "market_identifier": ric,
            "valid_from": trade_date,
            "valid_through": trade_date,
            "evidence_lane": "AUTHORIZED_MARKET_SECURITY_MASTER",
            "source_reference": f"lseg-tick-history-sha256:{source_sha256}",
            "authorization_reference": authorization_reference,
            "research_use_only": "1",
        }
        previous = evidence_by_request.get(request_id)
        if previous is not None and previous != evidence:
            raise LsegIdentityBridgeError(
                f"conflicting LSEG identity evidence for request {request_id}"
            )
        evidence_by_request[request_id] = evidence
        counts["direct_permno_bridge_eligible"] += 1

    evidence_rows = sorted(
        evidence_by_request.values(),
        key=lambda row: (row["permno"], row["valid_from"], row["market_identifier"]),
    )
    summary = {
        "schema_version": "1",
        "purpose": (
            "Convert date-specific authorized LSEG RIC validation into stable-ID evidence "
            "only when the companion study already provides a direct PERMNO-to-RIC bridge."
        ),
        "research_use_only": True,
        "source_sha256": source_sha256,
        "authorization_reference_present": True,
        "counts": {
            **counts,
            "evidence_rows_emitted": len(evidence_rows),
        },
        "policy": {
            "direct_mapping_status_required": DIRECT_MAPPING_STATUS,
            "date_specific_validation_required": "validated_single_candidate",
            "secondary_or_root_only_candidates_can_close": False,
            "symbol_only_join_can_close": False,
            "coverage_change": False,
        },
    }
    return evidence_rows, summary


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
            "Bridge authorized date-specific LSEG RIC validation to the stable-ID "
            "evidence schema without allowing symbol-only or undated promotion."
        )
    )
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--event-mapping", type=Path, default=DEFAULT_EVENT_MAPPING)
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    args = parser.parse_args()

    validation_path = args.validation.expanduser().resolve()
    rows, summary = build_evidence(
        read_csv(validation_path),
        read_csv(args.queue),
        read_csv(args.event_mapping),
        source_sha256=sha256_file(validation_path),
        authorization_reference=args.authorization_reference,
    )
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(render_evidence(rows), encoding="utf-8")
    args.summary_output.write_text(render_summary(summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
