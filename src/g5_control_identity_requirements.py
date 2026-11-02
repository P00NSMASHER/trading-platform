from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class ControlIdentityRequirement:
    historical_symbol: str
    trade_date: str
    roles: str
    identity_status: str
    canonical_g2_overlap: str
    canonical_permno: str
    canonical_gvkey: str
    samplefirms_permno: str
    samplefirms_gvkey: str
    samplefirms_exact_mapping_status: str
    required_evidence: str
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


def _load_history_pairs(path: Path) -> list[dict[str, str]]:
    fields, rows = _read_csv(path)
    required = {"historical_symbol", "trade_date", "roles"}
    missing = required.difference(fields)
    if missing:
        raise ValueError(
            f"control history requirements missing columns: {sorted(missing)}"
        )
    seen = set()
    out = []
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        trade_date = row["trade_date"][:10]
        if not symbol or not trade_date:
            raise ValueError(
                f"control history row {row_no}: symbol/trade_date required"
            )
        key = (symbol, trade_date)
        if key in seen:
            raise ValueError(
                f"duplicate control history symbol-date: {symbol}|{trade_date}"
            )
        seen.add(key)
        out.append(
            {
                "symbol": symbol,
                "trade_date": trade_date,
                "roles": row["roles"],
            }
        )
    if not out:
        raise ValueError("control history requirements are empty")
    return out


def _load_primary_candidates(path: Path) -> set[tuple[str, str]]:
    fields, rows = _read_csv(path)
    required = {"event_date", "candidate_symbol"}
    missing = required.difference(fields)
    if missing:
        raise ValueError(
            f"primary candidate file missing columns: {sorted(missing)}"
        )
    out = set()
    for row_no, row in enumerate(rows, 2):
        event_date = row["event_date"][:10]
        symbol = row["candidate_symbol"].upper()
        if not event_date or not symbol:
            raise ValueError(
                f"primary candidate row {row_no}: event_date/symbol required"
            )
        key = (symbol, event_date)
        if key in out:
            raise ValueError(
                f"duplicate primary candidate symbol-date: {symbol}|{event_date}"
            )
        out.add(key)
    return out


def _load_samplefirms_exact(
    path: Path,
) -> tuple[dict[tuple[str, str], tuple[str, str]], set[tuple[str, str]]]:
    fields, rows = _read_csv(path)
    required = {"PERMNO", "GVKEY", "SYMBOL", "date"}
    missing = required.difference(fields)
    if missing:
        raise ValueError(f"SampleFirms missing columns: {sorted(missing)}")

    raw: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for row_no, row in enumerate(rows, 2):
        symbol = row["SYMBOL"].upper()
        trade_date = row["date"][:10]
        permno = row["PERMNO"]
        gvkey = row["GVKEY"]
        if not symbol or not trade_date:
            continue
        if not permno:
            raise ValueError(
                f"SampleFirms row {row_no}: blank PERMNO for {symbol}|{trade_date}"
            )
        raw.setdefault((symbol, trade_date), set()).add((permno, gvkey))

    unique: dict[tuple[str, str], tuple[str, str]] = {}
    ambiguous: set[tuple[str, str]] = set()
    for key, mappings in raw.items():
        if len(mappings) == 1:
            unique[key] = next(iter(mappings))
        else:
            ambiguous.add(key)
    return unique, ambiguous


def _load_canonical_g2_identity(
    path: Path,
) -> tuple[
    dict[tuple[str, str], tuple[str, str]],
    dict[tuple[str, str], tuple[str, str]],
]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    events = obj.get("events")
    if not isinstance(events, list):
        raise ValueError("canonical security identity manifest missing events list")

    verified: dict[tuple[str, str], tuple[str, str]] = {}
    unverified: dict[tuple[str, str], tuple[str, str]] = {}
    for i, event in enumerate(events, 1):
        if not isinstance(event, dict):
            raise ValueError(f"canonical identity event {i} is not an object")
        symbol = str(event.get("historical_symbol", "")).strip().upper()
        permno = str(event.get("permno", "")).strip()
        gvkey = str(event.get("gvkey", "")).strip()
        if not symbol or not permno:
            raise ValueError(
                f"canonical identity event {i}: missing historical_symbol/permno"
            )
        for trade_date in event.get("verified_required_dates", []) or []:
            key = (symbol, str(trade_date)[:10])
            prior = verified.get(key)
            value = (permno, gvkey)
            if prior is not None and prior != value:
                raise ValueError(
                    f"canonical verified identity collision for {key}"
                )
            verified[key] = value
        for trade_date in event.get("unverified_required_dates", []) or []:
            key = (symbol, str(trade_date)[:10])
            prior = unverified.get(key)
            value = (permno, gvkey)
            if prior is not None and prior != value:
                raise ValueError(
                    f"canonical unresolved identity collision for {key}"
                )
            unverified[key] = value
    return verified, unverified


def build(
    *,
    control_history_path: Path,
    primary_candidates_path: Path,
    samplefirms_path: Path,
    canonical_g2_identity_manifest_path: Path,
    output_dir: Path,
) -> dict:
    history = _load_history_pairs(control_history_path)
    primary = _load_primary_candidates(primary_candidates_path)
    sample_unique, sample_ambiguous = _load_samplefirms_exact(samplefirms_path)
    g2_verified, g2_unverified = _load_canonical_g2_identity(
        canonical_g2_identity_manifest_path
    )

    requirements: list[ControlIdentityRequirement] = []
    status_counts: dict[str, int] = {}
    primary_sample_exact_unique = 0
    primary_sample_exact_ambiguous = 0
    primary_sample_exact_missing = 0

    for item in sorted(
        history,
        key=lambda row: (row["trade_date"], row["symbol"]),
    ):
        symbol = item["symbol"]
        trade_date = item["trade_date"]
        key = (symbol, trade_date)

        canonical_permno = ""
        canonical_gvkey = ""
        canonical_overlap = "NONE"

        if key in g2_verified:
            canonical_overlap = "CANONICAL_G2_VERIFIED"
            canonical_permno, canonical_gvkey = g2_verified[key]
            status = "REUSE_CANONICAL_G2_VERIFIED_IDENTITY"
            required_evidence = ""
        elif key in g2_unverified:
            canonical_overlap = "CANONICAL_G2_UNVERIFIED"
            canonical_permno, canonical_gvkey = g2_unverified[key]
            status = "OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE"
            required_evidence = "DATED_STABLE_ID_CROSSWALK"
        else:
            status = "NEW_G5_IDENTITY_EVIDENCE_REQUIRED"
            required_evidence = "DATED_STABLE_ID_CROSSWALK"

        sample_permno = ""
        sample_gvkey = ""
        if key in sample_ambiguous:
            sample_status = "AMBIGUOUS_EXACT_DATE_MAPPING"
            if status != "REUSE_CANONICAL_G2_VERIFIED_IDENTITY":
                status = "AMBIGUOUS_PUBLIC_MAPPING_REQUIRES_STABLE_ID_EVIDENCE"
        elif key in sample_unique:
            sample_status = "UNIQUE_EXACT_DATE_MAPPING_AVAILABLE"
            sample_permno, sample_gvkey = sample_unique[key]
            if canonical_permno and canonical_permno != sample_permno:
                raise ValueError(
                    "SampleFirms exact mapping conflicts with canonical G2 PERMNO "
                    f"for {symbol}|{trade_date}: "
                    f"{sample_permno} != {canonical_permno}"
                )
            if status == "NEW_G5_IDENTITY_EVIDENCE_REQUIRED":
                status = "PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION"
                required_evidence = "ADMISSIBLE_DATE_SPECIFIC_STABLE_ID_EVIDENCE"
        else:
            sample_status = "NO_EXACT_DATE_MAPPING"

        if key in primary:
            if sample_status == "UNIQUE_EXACT_DATE_MAPPING_AVAILABLE":
                primary_sample_exact_unique += 1
            elif sample_status == "AMBIGUOUS_EXACT_DATE_MAPPING":
                primary_sample_exact_ambiguous += 1
            else:
                primary_sample_exact_missing += 1

        status_counts[status] = status_counts.get(status, 0) + 1
        requirements.append(
            ControlIdentityRequirement(
                historical_symbol=symbol,
                trade_date=trade_date,
                roles=item["roles"],
                identity_status=status,
                canonical_g2_overlap=canonical_overlap,
                canonical_permno=canonical_permno,
                canonical_gvkey=canonical_gvkey,
                samplefirms_permno=sample_permno,
                samplefirms_gvkey=sample_gvkey,
                samplefirms_exact_mapping_status=sample_status,
                required_evidence=required_evidence,
            )
        )

    if (
        primary_sample_exact_unique
        + primary_sample_exact_ambiguous
        + primary_sample_exact_missing
        != len(primary)
    ):
        raise ValueError("primary candidate identity accounting does not reconcile")

    output_dir.mkdir(parents=True, exist_ok=True)
    detail_path = output_dir / "g5_control_identity_requirements.csv"
    with detail_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(ControlIdentityRequirement.__dataclass_fields__),
        )
        writer.writeheader()
        for row in requirements:
            writer.writerow(asdict(row))

    unresolved_path = output_dir / "g5_control_identity_acquisition_queue.csv"
    unresolved = [
        row
        for row in requirements
        if row.identity_status != "REUSE_CANONICAL_G2_VERIFIED_IDENTITY"
    ]
    with unresolved_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(ControlIdentityRequirement.__dataclass_fields__),
        )
        writer.writeheader()
        for row in unresolved:
            writer.writerow(asdict(row))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Plan stable-security-identity evidence for the G5 primary-control "
            "history footprint, maximizing reuse of canonical G2 identity while "
            "recording exact-date public SampleFirms mappings as admission leads "
            "rather than silently treating them as canonical identity evidence."
        ),
        "research_use_only": True,
        "primary_candidate_symbol_date_count": len(primary),
        "control_history_symbol_date_count": len(requirements),
        "canonical_g2_verified_reuse_count": status_counts.get(
            "REUSE_CANONICAL_G2_VERIFIED_IDENTITY", 0
        ),
        "canonical_g2_unverified_overlap_count": status_counts.get(
            "OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE", 0
        ),
        "public_exact_mapping_available_requires_admission_count": status_counts.get(
            "PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION", 0
        ),
        "new_g5_identity_evidence_required_count": status_counts.get(
            "NEW_G5_IDENTITY_EVIDENCE_REQUIRED", 0
        ),
        "ambiguous_public_mapping_count": status_counts.get(
            "AMBIGUOUS_PUBLIC_MAPPING_REQUIRES_STABLE_ID_EVIDENCE", 0
        ),
        "identity_acquisition_queue_count": len(unresolved),
        "primary_candidate_exact_sample_mapping": {
            "unique": primary_sample_exact_unique,
            "ambiguous": primary_sample_exact_ambiguous,
            "missing": primary_sample_exact_missing,
        },
        "status_counts": dict(sorted(status_counts.items())),
        "inputs": {
            "control_history": {
                "path": str(control_history_path),
                "sha256": _sha256(control_history_path),
            },
            "primary_candidates": {
                "path": str(primary_candidates_path),
                "sha256": _sha256(primary_candidates_path),
            },
            "samplefirms": {
                "path": str(samplefirms_path),
                "sha256": _sha256(samplefirms_path),
            },
            "canonical_g2_identity_manifest": {
                "path": str(canonical_g2_identity_manifest_path),
                "sha256": _sha256(canonical_g2_identity_manifest_path),
            },
        },
        "outputs": {
            "identity_requirements": str(detail_path),
            "identity_acquisition_queue": str(unresolved_path),
        },
        "policy": {
            "samplefirms_retrospective_labels_used": False,
            "samplefirms_exact_mapping_is_automatically_canonical_identity": False,
            "canonical_g2_verified_identity_may_be_reused": True,
            "undated_or_symbol_only_identity_may_close_g5": False,
            "identity_requirements_are_g5_evidence": False,
        },
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_control_identity_requirement_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan stable identity evidence for G5 control history."
    )
    parser.add_argument("--control-history", type=Path, required=True)
    parser.add_argument("--primary-candidates", type=Path, required=True)
    parser.add_argument("--samplefirms", type=Path, required=True)
    parser.add_argument(
        "--canonical-g2-identity-manifest",
        type=Path,
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        control_history_path=args.control_history,
        primary_candidates_path=args.primary_candidates,
        samplefirms_path=args.samplefirms,
        canonical_g2_identity_manifest_path=args.canonical_g2_identity_manifest,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
