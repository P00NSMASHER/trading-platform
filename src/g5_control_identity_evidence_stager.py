from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path

import security_identity_stocknames_adapter as stocknames

SCHEMA_VERSION = "1"

STAGED_FIELDS = [
    "historical_symbol",
    "trade_date",
    "permno",
    "market_identifier",
    "evidence_ids",
    "source_references",
    "authorization_references",
    "research_use_only",
]


class G5ControlIdentityEvidenceStagingError(ValueError):
    pass


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


def _parse_date(value: str, *, label: str) -> str:
    raw = str(value or "").strip()
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError as exc:
        raise G5ControlIdentityEvidenceStagingError(
            f"{label} must be a valid YYYY-MM-DD date"
        ) from exc


def _render_csv(rows: list[dict[str, str]], fields: list[str]) -> str:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def build(
    *,
    identity_queue_path: Path,
    evidence_path: Path,
    output_dir: Path,
) -> dict:
    queue_fields, queue_rows = _read_csv(identity_queue_path)
    required_queue = {
        "historical_symbol",
        "trade_date",
        "canonical_g2_overlap",
        "canonical_permno",
        "samplefirms_permno",
        "research_use_only",
    }
    missing_queue = required_queue.difference(queue_fields)
    if missing_queue:
        raise G5ControlIdentityEvidenceStagingError(
            f"identity queue missing columns: {sorted(missing_queue)}"
        )
    if not queue_rows:
        raise G5ControlIdentityEvidenceStagingError("identity queue is empty")

    evidence_fields, evidence_rows = _read_csv(evidence_path)
    missing_evidence = set(stocknames.EVIDENCE_FIELDS).difference(evidence_fields)
    if missing_evidence:
        raise G5ControlIdentityEvidenceStagingError(
            f"identity evidence missing columns: {sorted(missing_evidence)}"
        )
    if not evidence_rows:
        raise G5ControlIdentityEvidenceStagingError("identity evidence is empty")

    requirement_by_key: dict[tuple[str, str], dict[str, str]] = {}
    g2_overlap_keys: set[tuple[str, str]] = set()
    g5_only_keys: set[tuple[str, str]] = set()

    for row_no, row in enumerate(queue_rows, 2):
        symbol = row["historical_symbol"].upper()
        trade_date = _parse_date(
            row["trade_date"], label=f"identity queue row {row_no} trade_date"
        )
        if not symbol:
            raise G5ControlIdentityEvidenceStagingError(
                f"identity queue row {row_no}: historical_symbol is required"
            )
        if row["research_use_only"] != "1":
            raise G5ControlIdentityEvidenceStagingError(
                f"identity queue row {row_no}: research_use_only must equal 1"
            )
        key = (symbol, trade_date)
        if key in requirement_by_key:
            raise G5ControlIdentityEvidenceStagingError(
                f"duplicate G5 identity requirement: {symbol}|{trade_date}"
            )

        overlap = row["canonical_g2_overlap"]
        if overlap == "CANONICAL_G2_UNVERIFIED":
            g2_overlap_keys.add(key)
        elif overlap == "NONE":
            g5_only_keys.add(key)
        else:
            raise G5ControlIdentityEvidenceStagingError(
                f"identity queue row {row_no}: unexpected canonical_g2_overlap {overlap!r}"
            )
        normalized = dict(row)
        normalized["historical_symbol"] = symbol
        normalized["trade_date"] = trade_date
        requirement_by_key[key] = normalized

    matched_by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
    g2_forward_ids: set[str] = set()
    evidence_by_id: dict[str, dict[str, str]] = {}

    for row_no, raw in enumerate(evidence_rows, 2):
        row = {str(key): str(value or "").strip() for key, value in raw.items()}
        evidence_id = row["evidence_id"]
        if not evidence_id or evidence_id in evidence_by_id:
            raise G5ControlIdentityEvidenceStagingError(
                f"identity evidence row {row_no}: evidence_id must be unique and nonblank"
            )
        if row["research_use_only"] != "1":
            raise G5ControlIdentityEvidenceStagingError(
                f"identity evidence row {row_no}: research_use_only must equal 1"
            )
        if row["evidence_lane"] not in {
            "LICENSED_STABLE_ID_MASTER",
            "AUTHORIZED_MARKET_SECURITY_MASTER",
        }:
            raise G5ControlIdentityEvidenceStagingError(
                f"identity evidence row {row_no}: evidence_lane is not closing-authorized"
            )
        if not row["authorization_reference"]:
            raise G5ControlIdentityEvidenceStagingError(
                f"identity evidence row {row_no}: authorization_reference is required"
            )
        if not row["source_reference"]:
            raise G5ControlIdentityEvidenceStagingError(
                f"identity evidence row {row_no}: source_reference is required"
            )

        permno = row["permno"]
        symbol = row["historical_symbol"].upper()
        market_identifier = row["market_identifier"]
        if not permno or not symbol or not market_identifier:
            raise G5ControlIdentityEvidenceStagingError(
                f"identity evidence row {row_no}: permno, historical_symbol, and market_identifier are required"
            )
        valid_from = _parse_date(
            row["valid_from"], label=f"identity evidence row {row_no} valid_from"
        )
        valid_through = _parse_date(
            row["valid_through"], label=f"identity evidence row {row_no} valid_through"
        )
        if valid_through < valid_from:
            raise G5ControlIdentityEvidenceStagingError(
                f"identity evidence row {row_no}: valid_through precedes valid_from"
            )

        normalized = dict(row)
        normalized["historical_symbol"] = symbol
        normalized["valid_from"] = valid_from
        normalized["valid_through"] = valid_through
        evidence_by_id[evidence_id] = normalized

        matched_keys = [
            key
            for key in requirement_by_key
            if key[0] == symbol and valid_from <= key[1] <= valid_through
        ]
        if not matched_keys:
            raise G5ControlIdentityEvidenceStagingError(
                f"identity evidence row {row_no}: evidence does not match any unresolved G5 identity requirement"
            )

        for key in matched_keys:
            requirement = requirement_by_key[key]
            canonical_hint = requirement["canonical_permno"]
            sample_hint = requirement["samplefirms_permno"]
            expected_hint = canonical_hint or sample_hint
            if canonical_hint and sample_hint and canonical_hint != sample_hint:
                raise G5ControlIdentityEvidenceStagingError(
                    f"G5 identity requirement {key[0]}|{key[1]} has conflicting PERMNO hints"
                )
            if expected_hint and expected_hint != permno:
                raise G5ControlIdentityEvidenceStagingError(
                    f"identity evidence PERMNO {permno} conflicts with expected hint "
                    f"{expected_hint} for {key[0]}|{key[1]}"
                )
            matched_by_key.setdefault(key, []).append(normalized)
            if key in g2_overlap_keys:
                g2_forward_ids.add(evidence_id)

    staged_rows: list[dict[str, str]] = []
    remaining_g5_rows: list[dict[str, str]] = []

    for key in sorted(g5_only_keys, key=lambda item: (item[1], item[0])):
        matches = matched_by_key.get(key, [])
        if not matches:
            remaining_g5_rows.append(requirement_by_key[key])
            continue
        permnos = {row["permno"] for row in matches}
        identifiers = {row["market_identifier"] for row in matches}
        if len(permnos) != 1:
            raise G5ControlIdentityEvidenceStagingError(
                f"conflicting authorized PERMNO evidence for {key[0]}|{key[1]}: {sorted(permnos)}"
            )
        if len(identifiers) != 1:
            raise G5ControlIdentityEvidenceStagingError(
                f"conflicting authorized market identifiers for {key[0]}|{key[1]}: "
                f"{sorted(identifiers)}"
            )
        staged_rows.append(
            {
                "historical_symbol": key[0],
                "trade_date": key[1],
                "permno": next(iter(permnos)),
                "market_identifier": next(iter(identifiers)),
                "evidence_ids": ";".join(sorted({row["evidence_id"] for row in matches})),
                "source_references": ";".join(
                    sorted({row["source_reference"] for row in matches})
                ),
                "authorization_references": ";".join(
                    sorted({row["authorization_reference"] for row in matches})
                ),
                "research_use_only": "1",
            }
        )

    forwarded_rows = [
        evidence_by_id[evidence_id]
        for evidence_id in sorted(g2_forward_ids)
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    staged_path = output_dir / "g5_control_identity_staged_verified.csv"
    remaining_path = output_dir / "g5_control_identity_g5_only_remaining.csv"
    forward_path = output_dir / "g5_control_identity_g2_forward_evidence.csv"
    receipt_path = output_dir / "g5_control_identity_evidence_staging_receipt.json"

    staged_path.write_text(
        _render_csv(staged_rows, STAGED_FIELDS),
        encoding="utf-8",
    )
    remaining_path.write_text(
        _render_csv(remaining_g5_rows, queue_fields),
        encoding="utf-8",
    )
    forward_path.write_text(
        _render_csv(forwarded_rows, stocknames.EVIDENCE_FIELDS),
        encoding="utf-8",
    )

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Stage authorized dated stable-ID evidence only for G5-only control identity "
            "requirements while routing canonical G2-overlap evidence back to the existing "
            "G2 identity pipeline. This staging step never mutates either canonical gate."
        ),
        "research_use_only": True,
        "canonical_g2_write_performed": False,
        "canonical_g5_write_performed": False,
        "coverage_promoted": False,
        "inputs": {
            "identity_queue_path": str(identity_queue_path),
            "identity_queue_sha256": _sha256(identity_queue_path),
            "evidence_path": str(evidence_path),
            "evidence_sha256": _sha256(evidence_path),
        },
        "counts": {
            "identity_queue_count": len(queue_rows),
            "canonical_g2_overlap_requirement_count": len(g2_overlap_keys),
            "g5_only_requirement_count": len(g5_only_keys),
            "g5_only_staged_verified_count": len(staged_rows),
            "g5_only_remaining_count": len(remaining_g5_rows),
            "g2_forward_evidence_row_count": len(forwarded_rows),
            "input_evidence_row_count": len(evidence_rows),
        },
        "g5_only_identity_staging_complete": len(remaining_g5_rows) == 0,
        "overall_g5_identity_ready_claimed": False,
        "policy": {
            "canonical_g2_overlap_must_use_existing_g2_admission_pipeline": True,
            "g5_only_evidence_may_establish_permno_without_a_prior_hint": True,
            "known_permno_hints_must_match_authorized_evidence": True,
            "historical_symbol_and_requested_date_must_match_authorized_evidence": True,
            "conflicting_authorized_identifiers_fail_closed": True,
            "evidence_outside_the_g5_identity_queue_fails_closed": True,
            "staged_rows_are_not_canonical_g5_readiness": True,
        },
        "outputs": {
            "g5_only_staged_verified": str(staged_path),
            "g5_only_remaining": str(remaining_path),
            "canonical_g2_forward_evidence": str(forward_path),
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stage authorized stable-ID evidence for G5-only control identity requirements "
            "without broadening the canonical G2 identity universe."
        )
    )
    parser.add_argument("--identity-queue", type=Path, required=True)
    parser.add_argument("--identity-evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        identity_queue_path=args.identity_queue,
        evidence_path=args.identity_evidence,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
