from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = "1"


class G5ControlIdentityGateError(ValueError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    return fields, rows


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise G5ControlIdentityGateError(f"invalid JSON: {path}") from exc
    if not isinstance(obj, dict):
        raise G5ControlIdentityGateError(f"JSON root must be an object: {path}")
    return obj


def _requirements(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    fields, rows = _read_csv(path)
    required = {
        "historical_symbol",
        "trade_date",
        "canonical_g2_overlap",
        "canonical_permno",
        "samplefirms_permno",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5ControlIdentityGateError(
            f"G5 identity requirements missing columns: {sorted(missing)}"
        )
    if not rows:
        raise G5ControlIdentityGateError("G5 identity requirements are empty")

    out: dict[tuple[str, str], dict[str, str]] = {}
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        trade_date = row["trade_date"][:10]
        if not symbol or len(trade_date) != 10:
            raise G5ControlIdentityGateError(
                f"G5 identity requirement row {row_no}: symbol/date required"
            )
        if row["research_use_only"] != "1":
            raise G5ControlIdentityGateError(
                f"G5 identity requirement row {row_no}: research_use_only must equal 1"
            )
        key = (symbol, trade_date)
        if key in out:
            raise G5ControlIdentityGateError(
                f"duplicate G5 identity requirement: {symbol}|{trade_date}"
            )
        normalized = dict(row)
        normalized["historical_symbol"] = symbol
        normalized["trade_date"] = trade_date
        out[key] = normalized
    return out


def _g2_verified(path: Path) -> dict[tuple[str, str], str]:
    events = _read_json(path).get("events")
    if not isinstance(events, list):
        raise G5ControlIdentityGateError("canonical G2 identity manifest missing events")

    out: dict[tuple[str, str], str] = {}
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            raise G5ControlIdentityGateError(
                f"canonical G2 identity event {index} is not an object"
            )
        symbol = str(event.get("historical_symbol") or "").strip().upper()
        permno = str(event.get("permno") or "").strip()
        if not symbol or not permno:
            raise G5ControlIdentityGateError(
                f"canonical G2 identity event {index}: symbol/PERMNO required"
            )
        for raw_date in event.get("verified_required_dates") or []:
            key = (symbol, str(raw_date)[:10])
            prior = out.get(key)
            if prior is not None and prior != permno:
                raise G5ControlIdentityGateError(
                    f"canonical G2 verified identity collision for {key[0]}|{key[1]}"
                )
            out[key] = permno
    return out


def _g5_staged(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    fields, rows = _read_csv(path)
    required = {
        "historical_symbol",
        "trade_date",
        "permno",
        "market_identifier",
        "evidence_ids",
        "source_references",
        "authorization_references",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5ControlIdentityGateError(
            f"staged G5 identity evidence missing columns: {sorted(missing)}"
        )

    out: dict[tuple[str, str], dict[str, str]] = {}
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        trade_date = row["trade_date"][:10]
        if (
            not symbol
            or len(trade_date) != 10
            or not row["permno"]
            or not row["market_identifier"]
            or not row["evidence_ids"]
            or not row["source_references"]
            or not row["authorization_references"]
        ):
            raise G5ControlIdentityGateError(
                f"staged G5 identity row {row_no}: required evidence fields are blank"
            )
        if row["research_use_only"] != "1":
            raise G5ControlIdentityGateError(
                f"staged G5 identity row {row_no}: research_use_only must equal 1"
            )
        key = (symbol, trade_date)
        if key in out:
            raise G5ControlIdentityGateError(
                f"duplicate staged G5 identity: {symbol}|{trade_date}"
            )
        normalized = dict(row)
        normalized["historical_symbol"] = symbol
        normalized["trade_date"] = trade_date
        out[key] = normalized
    return out


def build(
    *,
    identity_requirements_path: Path,
    canonical_g2_identity_manifest_path: Path,
    g5_only_staged_verified_path: Path,
    g5_staging_receipt_path: Path,
    output_path: Path,
) -> dict:
    requirements = _requirements(identity_requirements_path)
    g2_verified = _g2_verified(canonical_g2_identity_manifest_path)
    g5_staged = _g5_staged(g5_only_staged_verified_path)
    staging_receipt = _read_json(g5_staging_receipt_path)

    if not bool(staging_receipt.get("research_use_only")):
        raise G5ControlIdentityGateError("G5 staging receipt is not research-use-only")
    if bool(staging_receipt.get("canonical_g2_write_performed")):
        raise G5ControlIdentityGateError("G5 staging receipt unexpectedly mutated canonical G2")
    if bool(staging_receipt.get("canonical_g5_write_performed")):
        raise G5ControlIdentityGateError("G5 staging receipt unexpectedly claims canonical G5 write")
    if bool(staging_receipt.get("coverage_promoted")):
        raise G5ControlIdentityGateError(
            "G5 staging receipt unexpectedly claims coverage promotion"
        )
    if bool(staging_receipt.get("overall_g5_identity_ready_claimed")):
        raise G5ControlIdentityGateError(
            "G5 staging receipt unexpectedly claims overall G5 identity readiness"
        )

    hashes = staging_receipt.get("output_sha256") or {}
    expected_staged_sha = str(hashes.get("g5_only_staged_verified") or "")
    actual_staged_sha = _sha256(g5_only_staged_verified_path)
    if not expected_staged_sha or expected_staged_sha != actual_staged_sha:
        raise G5ControlIdentityGateError(
            "G5 staged identity CSV is not hash-bound to its staging receipt"
        )

    counts = staging_receipt.get("counts") or {}
    try:
        receipt_staged_count = int(counts.get("g5_only_staged_verified_count", -1))
    except (TypeError, ValueError) as exc:
        raise G5ControlIdentityGateError("invalid G5 staging receipt counts") from exc
    if receipt_staged_count != len(g5_staged):
        raise G5ControlIdentityGateError(
            "G5 staging receipt count disagrees with staged verified CSV"
        )

    canonical_reuse_required = 0
    canonical_reuse_verified = 0
    g2_overlap_required = 0
    g2_overlap_verified = 0
    g5_only_required = 0
    g5_only_verified = 0
    g5_only_keys: set[tuple[str, str]] = set()
    unresolved: list[str] = []

    for key, row in sorted(requirements.items(), key=lambda item: (item[0][1], item[0][0])):
        symbol, trade_date = key
        overlap = row["canonical_g2_overlap"]
        canonical_hint = row["canonical_permno"]
        sample_hint = row["samplefirms_permno"]
        if canonical_hint and sample_hint and canonical_hint != sample_hint:
            raise G5ControlIdentityGateError(
                f"G5 identity requirement has conflicting PERMNO hints: {symbol}|{trade_date}"
            )
        expected_hint = canonical_hint or sample_hint

        if overlap in {"CANONICAL_G2_VERIFIED", "CANONICAL_G2_UNVERIFIED"}:
            actual = g2_verified.get(key)
            if overlap == "CANONICAL_G2_VERIFIED":
                canonical_reuse_required += 1
            else:
                g2_overlap_required += 1
            verified = bool(actual and (not expected_hint or actual == expected_hint))
            if verified and overlap == "CANONICAL_G2_VERIFIED":
                canonical_reuse_verified += 1
            elif verified:
                g2_overlap_verified += 1
            else:
                unresolved.append(f"{symbol}|{trade_date}")
            continue

        if overlap != "NONE":
            raise G5ControlIdentityGateError(
                f"unexpected canonical_g2_overlap {overlap!r} for {symbol}|{trade_date}"
            )

        g5_only_required += 1
        g5_only_keys.add(key)
        staged = g5_staged.get(key)
        if staged is None:
            unresolved.append(f"{symbol}|{trade_date}")
            continue
        if expected_hint and staged["permno"] != expected_hint:
            raise G5ControlIdentityGateError(
                f"staged G5 PERMNO conflicts with acquisition hint for {symbol}|{trade_date}"
            )
        g5_only_verified += 1

    extra = sorted(set(g5_staged) - g5_only_keys)
    if extra:
        rendered = ", ".join(f"{symbol}|{trade_date}" for symbol, trade_date in extra[:10])
        raise G5ControlIdentityGateError(
            "staged G5 identity contains rows outside G5-only requirements: " + rendered
        )

    required_count = len(requirements)
    verified_count = (
        canonical_reuse_verified + g2_overlap_verified + g5_only_verified
    )
    unresolved_count = len(unresolved)
    if verified_count + unresolved_count != required_count:
        raise G5ControlIdentityGateError("G5 identity counts do not reconcile")

    ready = unresolved_count == 0
    result = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Fail-closed stable-security-identity gate for the complete G5 control-history "
            "symbol/date footprint. G2 overlap must be canonical; G5-only dates require "
            "hash-bound authorized evidence."
        ),
        "research_use_only": True,
        "ready_for_g5_control_identity": ready,
        "state": {
            "required_symbol_date_count": required_count,
            "verified_symbol_date_count": verified_count,
            "unresolved_symbol_date_count": unresolved_count,
            "canonical_g2_verified_reuse_required_count": canonical_reuse_required,
            "canonical_g2_verified_reuse_verified_count": canonical_reuse_verified,
            "canonical_g2_overlap_required_count": g2_overlap_required,
            "canonical_g2_overlap_verified_count": g2_overlap_verified,
            "g5_only_required_count": g5_only_required,
            "g5_only_verified_count": g5_only_verified,
            "unresolved_examples": unresolved[:20],
        },
        "inputs": {
            "identity_requirements": {
                "path": str(identity_requirements_path),
                "sha256": _sha256(identity_requirements_path),
            },
            "canonical_g2_identity_manifest": {
                "path": str(canonical_g2_identity_manifest_path),
                "sha256": _sha256(canonical_g2_identity_manifest_path),
            },
            "g5_only_staged_verified": {
                "path": str(g5_only_staged_verified_path),
                "sha256": actual_staged_sha,
            },
            "g5_staging_receipt": {
                "path": str(g5_staging_receipt_path),
                "sha256": _sha256(g5_staging_receipt_path),
            },
        },
        "policy": {
            "current_ticker_substitution_permitted": False,
            "cross_date_identity_continuity_assumed": False,
            "g2_overlap_must_be_canonically_verified": True,
            "g5_only_rows_require_authorized_hash_bound_evidence": True,
            "release_gate_may_infer_missing_identity": False,
        },
        "canonical_g2_write_performed": False,
        "canonical_g5_write_performed": False,
        "release_claimed": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the fail-closed G5 control-history stable identity gate."
    )
    parser.add_argument("--identity-requirements", type=Path, required=True)
    parser.add_argument("--canonical-g2-identity-manifest", type=Path, required=True)
    parser.add_argument("--g5-only-staged-verified", type=Path, required=True)
    parser.add_argument("--g5-staging-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        identity_requirements_path=args.identity_requirements,
        canonical_g2_identity_manifest_path=args.canonical_g2_identity_manifest,
        g5_only_staged_verified_path=args.g5_only_staged_verified,
        g5_staging_receipt_path=args.g5_staging_receipt,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ready_for_g5_control_identity"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
