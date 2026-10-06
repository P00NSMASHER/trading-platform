from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


SCHEMA_VERSION = "1"

PREVIEW_FIELDS = [
    "historical_symbol",
    "trade_date",
    "canonical_g2_overlap",
    "canonical_permno",
    "samplefirms_permno",
    "preview_identity_status",
    "preview_verified",
    "research_use_only",
]


class G5ControlIdentityReadinessPreviewError(ValueError):
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



def _canonical_g2_verified(path: Path) -> dict[tuple[str, str], str]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise G5ControlIdentityReadinessPreviewError(
            "canonical G2 identity manifest is missing or invalid JSON"
        ) from exc
    events = obj.get("events") if isinstance(obj, dict) else None
    if not isinstance(events, list):
        raise G5ControlIdentityReadinessPreviewError(
            "canonical G2 identity manifest missing events"
        )

    verified: dict[tuple[str, str], str] = {}
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            raise G5ControlIdentityReadinessPreviewError(
                f"canonical G2 identity event {index} is not an object"
            )
        symbol = str(event.get("historical_symbol") or "").strip().upper()
        permno = str(event.get("permno") or "").strip()
        if not symbol or not permno:
            raise G5ControlIdentityReadinessPreviewError(
                f"canonical G2 identity event {index}: symbol/PERMNO required"
            )
        for raw_date in event.get("verified_required_dates") or []:
            trade_date = str(raw_date)[:10]
            key = (symbol, trade_date)
            prior = verified.get(key)
            if prior is not None and prior != permno:
                raise G5ControlIdentityReadinessPreviewError(
                    f"canonical G2 verified identity collision for {symbol}|{trade_date}"
                )
            verified[key] = permno
    return verified

def build_preview(
    *,
    identity_requirements_path: Path,
    canonical_g2_identity_manifest_path: Path,
    staged_g5_only_path: Path | None,
    staging_receipt_path: Path | None,
    output_path: Path,
    summary_path: Path,
) -> dict:
    requirement_fields, requirement_rows = _read_csv(identity_requirements_path)
    required_requirement_fields = {
        "historical_symbol",
        "trade_date",
        "identity_status",
        "canonical_g2_overlap",
        "canonical_permno",
        "samplefirms_permno",
        "research_use_only",
    }
    missing_requirement_fields = required_requirement_fields.difference(
        requirement_fields
    )
    if missing_requirement_fields:
        raise G5ControlIdentityReadinessPreviewError(
            "identity requirements missing columns: "
            f"{sorted(missing_requirement_fields)}"
        )
    if not requirement_rows:
        raise G5ControlIdentityReadinessPreviewError(
            "identity requirements are empty"
        )

    requirements: dict[tuple[str, str], dict[str, str]] = {}
    for row_no, row in enumerate(requirement_rows, 2):
        symbol = row["historical_symbol"].upper()
        trade_date = row["trade_date"][:10]
        if not symbol or len(trade_date) != 10:
            raise G5ControlIdentityReadinessPreviewError(
                f"identity requirement row {row_no}: symbol/trade_date required"
            )
        if row["research_use_only"] != "1":
            raise G5ControlIdentityReadinessPreviewError(
                f"identity requirement row {row_no}: research_use_only must equal 1"
            )
        key = (symbol, trade_date)
        if key in requirements:
            raise G5ControlIdentityReadinessPreviewError(
                f"duplicate identity requirement: {symbol}|{trade_date}"
            )
        normalized = dict(row)
        normalized["historical_symbol"] = symbol
        normalized["trade_date"] = trade_date
        requirements[key] = normalized
        if row["identity_status"] == "REUSE_CANONICAL_G2_VERIFIED_IDENTITY":
            if row["canonical_g2_overlap"] != "CANONICAL_G2_VERIFIED":
                raise G5ControlIdentityReadinessPreviewError(
                    f"canonical verified status disagrees with overlap for {symbol}|{trade_date}"
                )
    canonical_g2_verified = _canonical_g2_verified(
        canonical_g2_identity_manifest_path
    )
    canonical_verified: set[tuple[str, str]] = set()
    for key, requirement in requirements.items():
        overlap = requirement["canonical_g2_overlap"]
        if overlap in {"CANONICAL_G2_VERIFIED", "CANONICAL_G2_UNVERIFIED"}:
            actual_permno = canonical_g2_verified.get(key, "")
            expected_permno = (
                requirement["canonical_permno"]
                or requirement["samplefirms_permno"]
            )
            if actual_permno and (
                not expected_permno or actual_permno == expected_permno
            ):
                canonical_verified.add(key)
        elif overlap != "NONE":
            raise G5ControlIdentityReadinessPreviewError(
                f"unexpected canonical_g2_overlap for {key[0]}|{key[1]}: {overlap!r}"
            )

    staged_by_key: dict[tuple[str, str], dict[str, str]] = {}
    if (staged_g5_only_path is None) != (staging_receipt_path is None):
        raise G5ControlIdentityReadinessPreviewError(
            "staged G5 identity rows and staging receipt must be supplied together"
        )

    staged_receipt = None
    if staged_g5_only_path is not None:
        try:
            staged_receipt = json.loads(
                staging_receipt_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise G5ControlIdentityReadinessPreviewError(
                "staging receipt is missing or invalid JSON"
            ) from exc

        if not isinstance(staged_receipt, dict):
            raise G5ControlIdentityReadinessPreviewError(
                "staging receipt must be a JSON object"
            )
        output_sha256 = staged_receipt.get("output_sha256") or {}
        expected_staged_sha = str(
            output_sha256.get("g5_only_staged_verified") or ""
        )
        actual_staged_sha = _sha256(staged_g5_only_path)
        if expected_staged_sha != actual_staged_sha:
            raise G5ControlIdentityReadinessPreviewError(
                "staged G5 identity file hash does not match staging receipt"
            )
        if bool(staged_receipt.get("canonical_g2_write_performed")):
            raise G5ControlIdentityReadinessPreviewError(
                "staging receipt unexpectedly reports a canonical G2 write"
            )
        if bool(staged_receipt.get("canonical_g5_write_performed")):
            raise G5ControlIdentityReadinessPreviewError(
                "staging receipt unexpectedly reports a canonical G5 write"
            )
        if bool(staged_receipt.get("coverage_promoted")):
            raise G5ControlIdentityReadinessPreviewError(
                "staging receipt unexpectedly reports coverage promotion"
            )

        staged_fields, staged_rows = _read_csv(staged_g5_only_path)
        required_staged_fields = {
            "historical_symbol",
            "trade_date",
            "permno",
            "market_identifier",
            "evidence_ids",
            "source_references",
            "authorization_references",
            "research_use_only",
        }
        missing_staged_fields = required_staged_fields.difference(staged_fields)
        if missing_staged_fields:
            raise G5ControlIdentityReadinessPreviewError(
                f"staged G5 identity rows missing columns: {sorted(missing_staged_fields)}"
            )

        expected_staged_count = int(
            ((staged_receipt.get("counts") or {}).get(
                "g5_only_staged_verified_count", -1
            ))
        )
        if expected_staged_count != len(staged_rows):
            raise G5ControlIdentityReadinessPreviewError(
                "staged G5 identity row count does not match staging receipt"
            )

        for row_no, row in enumerate(staged_rows, 2):
            symbol = row["historical_symbol"].upper()
            trade_date = row["trade_date"][:10]
            key = (symbol, trade_date)
            requirement = requirements.get(key)
            if requirement is None:
                raise G5ControlIdentityReadinessPreviewError(
                    f"staged identity row {row_no}: unknown requirement {symbol}|{trade_date}"
                )
            if key in canonical_verified:
                raise G5ControlIdentityReadinessPreviewError(
                    f"staged identity row {row_no}: canonical G2-verified requirement may not be re-staged"
                )
            if requirement["canonical_g2_overlap"] != "NONE":
                raise G5ControlIdentityReadinessPreviewError(
                    f"staged identity row {row_no}: G2-overlap requirement must use the canonical G2 pipeline"
                )
            if row["research_use_only"] != "1":
                raise G5ControlIdentityReadinessPreviewError(
                    f"staged identity row {row_no}: research_use_only must equal 1"
                )
            if key in staged_by_key:
                raise G5ControlIdentityReadinessPreviewError(
                    f"duplicate staged identity requirement: {symbol}|{trade_date}"
                )
            if not all(
                row[field]
                for field in (
                    "permno",
                    "market_identifier",
                    "evidence_ids",
                    "source_references",
                    "authorization_references",
                )
            ):
                raise G5ControlIdentityReadinessPreviewError(
                    f"staged identity row {row_no}: verified evidence fields must be nonblank"
                )

            canonical_hint = requirement["canonical_permno"]
            sample_hint = requirement["samplefirms_permno"]
            if canonical_hint and sample_hint and canonical_hint != sample_hint:
                raise G5ControlIdentityReadinessPreviewError(
                    f"conflicting PERMNO hints for {symbol}|{trade_date}"
                )
            expected_hint = canonical_hint or sample_hint
            if expected_hint and row["permno"] != expected_hint:
                raise G5ControlIdentityReadinessPreviewError(
                    f"staged identity PERMNO conflicts with expected hint for {symbol}|{trade_date}"
                )
            staged_by_key[key] = {
                **row,
                "historical_symbol": symbol,
                "trade_date": trade_date,
            }

    preview_rows: list[dict[str, str]] = []
    unresolved_g2_overlap = 0
    unresolved_g5_only = 0

    for key in sorted(requirements, key=lambda item: (item[1], item[0])):
        requirement = requirements[key]
        if key in canonical_verified:
            preview_status = "CANONICAL_G2_VERIFIED_REUSE"
            verified = "1"
        elif key in staged_by_key:
            preview_status = "STAGED_G5_ONLY_AUTHORIZED_EVIDENCE"
            verified = "1"
        elif requirement["canonical_g2_overlap"] in {
            "CANONICAL_G2_VERIFIED",
            "CANONICAL_G2_UNVERIFIED",
        }:
            preview_status = "UNRESOLVED_CANONICAL_G2_OVERLAP"
            verified = "0"
            unresolved_g2_overlap += 1
        elif requirement["canonical_g2_overlap"] == "NONE":
            preview_status = "UNRESOLVED_G5_ONLY"
            verified = "0"
            unresolved_g5_only += 1
        else:
            raise G5ControlIdentityReadinessPreviewError(
                f"unexpected canonical_g2_overlap for {key[0]}|{key[1]}: "
                f"{requirement['canonical_g2_overlap']!r}"
            )

        preview_rows.append(
            {
                "historical_symbol": key[0],
                "trade_date": key[1],
                "canonical_g2_overlap": requirement["canonical_g2_overlap"],
                "canonical_permno": requirement["canonical_permno"],
                "samplefirms_permno": requirement["samplefirms_permno"],
                "preview_identity_status": preview_status,
                "preview_verified": verified,
                "research_use_only": "1",
            }
        )

    canonical_verified_count = len(canonical_verified)
    staged_verified_count = len(staged_by_key)
    total_requirement_count = len(requirements)
    preview_verified_count = canonical_verified_count + staged_verified_count
    unresolved_count = unresolved_g2_overlap + unresolved_g5_only
    if preview_verified_count + unresolved_count != total_requirement_count:
        raise G5ControlIdentityReadinessPreviewError(
            "identity preview counts do not reconcile"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PREVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(preview_rows)

    inputs = {
        "identity_requirements": {
            "path": str(identity_requirements_path),
            "sha256": _sha256(identity_requirements_path),
        },
        "canonical_g2_identity_manifest": {
            "path": str(canonical_g2_identity_manifest_path),
            "sha256": _sha256(canonical_g2_identity_manifest_path),
        },
    }
    if staged_g5_only_path is not None:
        inputs["staged_g5_only_identity"] = {
            "path": str(staged_g5_only_path),
            "sha256": _sha256(staged_g5_only_path),
        }
        inputs["staging_receipt"] = {
            "path": str(staging_receipt_path),
            "sha256": _sha256(staging_receipt_path),
        }

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Preview full control-history stable-identity completeness for G5 without "
            "modifying canonical G2 or G5 state. Current canonical G2-verified dates may be reused; "
            "only G5-only rows already staged from authorized dated evidence count as "
            "additional preview verification."
        ),
        "research_use_only": True,
        "identity_requirement_count": total_requirement_count,
        "canonical_g2_verified_reuse_count": canonical_verified_count,
        "staged_g5_only_verified_count": staged_verified_count,
        "preview_verified_count": preview_verified_count,
        "unresolved_canonical_g2_overlap_count": unresolved_g2_overlap,
        "unresolved_g5_only_count": unresolved_g5_only,
        "unresolved_identity_requirement_count": unresolved_count,
        "preview_full_history_identity_complete": unresolved_count == 0,
        "inputs": inputs,
        "outputs": {
            "identity_readiness_preview": str(output_path),
        },
        "canonical_g2_write_performed": False,
        "canonical_g5_write_performed": False,
        "canonical_g5_readiness_changed": False,
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
        "policy": {
            "g2_overlap_requires_canonical_g2_promotion": True,
            "requirements_status_alone_may_close_g2_overlap": False,
            "canonical_g2_manifest_revalidated_each_run": True,
            "staged_g5_only_rows_are_preview_evidence_only": True,
            "event_date_identity_does_not_substitute_for_full_history_identity": True,
            "undated_or_symbol_only_identity_may_close_g5": False,
        },
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preview G5 control-history stable-identity readiness."
    )
    parser.add_argument("--identity-requirements", type=Path, required=True)
    parser.add_argument(
        "--canonical-g2-identity-manifest", type=Path, required=True
    )
    parser.add_argument("--staged-g5-only", type=Path)
    parser.add_argument("--staging-receipt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    result = build_preview(
        identity_requirements_path=args.identity_requirements,
        canonical_g2_identity_manifest_path=args.canonical_g2_identity_manifest,
        staged_g5_only_path=args.staged_g5_only,
        staging_receipt_path=args.staging_receipt,
        output_path=args.output,
        summary_path=args.summary,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
