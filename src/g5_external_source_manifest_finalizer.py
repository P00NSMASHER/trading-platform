from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import g5_external_metadata_adapter as external_adapter


SCHEMA_VERSION = "1"
MANIFEST_SCHEMA_VERSION = "1"
BINDINGS_SCHEMA_VERSION = "1"

EVENT_DATE_ALIASES = ("event_date", "trade_date", "date")
SYMBOL_ALIASES = ("symbol", "historical_symbol", "ticker")
EFFECTIVE_TS_ALIASES = (
    "effective_ts_utc",
    "available_at",
    "effective_timestamp",
)


class G5ExternalSourceManifestFinalizerError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, label: str) -> dict:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise G5ExternalSourceManifestFinalizerError(
            f"{label} does not exist: {path}"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise G5ExternalSourceManifestFinalizerError(
            f"{label} is not valid JSON"
        ) from exc
    if not isinstance(raw, dict):
        raise G5ExternalSourceManifestFinalizerError(
            f"{label} must be a JSON object"
        )
    return raw


def _resolve_path(owner_path: Path, raw: str, *, label: str) -> Path:
    value = Path(str(raw or "").strip())
    if not str(value):
        raise G5ExternalSourceManifestFinalizerError(
            f"{label} path is blank"
        )
    if not value.is_absolute():
        value = owner_path.parent / value
    value = value.expanduser().resolve()
    if not value.is_file():
        raise G5ExternalSourceManifestFinalizerError(
            f"{label} file does not exist: {value}"
        )
    return value


def _has_any(lower_fields: set[str], aliases: tuple[str, ...]) -> bool:
    return any(alias.lower() in lower_fields for alias in aliases)


def _preflight_source(path: Path, *, lane: str) -> tuple[list[str], int]:
    if lane not in external_adapter.LANE_FIELDS:
        raise G5ExternalSourceManifestFinalizerError(
            f"unsupported external lane: {lane}"
        )

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        row_count = sum(1 for _ in reader)

    if not fields:
        raise G5ExternalSourceManifestFinalizerError(
            f"source file has no CSV header: {path}"
        )
    if row_count < 1:
        raise G5ExternalSourceManifestFinalizerError(
            f"source file contains no data rows: {path}"
        )

    lower_fields = {field.lower() for field in fields}
    prohibited = sorted(
        external_adapter.PROHIBITED_SOURCE_COLUMNS.intersection(
            lower_fields
        )
    )
    if prohibited:
        raise G5ExternalSourceManifestFinalizerError(
            f"source file contains prohibited retrospective/post-event columns: {prohibited}"
        )

    base_requirements = (
        ("event date", EVENT_DATE_ALIASES),
        ("symbol", SYMBOL_ALIASES),
        ("effective timestamp", EFFECTIVE_TS_ALIASES),
    )
    for label, aliases in base_requirements:
        if not _has_any(lower_fields, aliases):
            raise G5ExternalSourceManifestFinalizerError(
                f"source file {path} is missing a {label} column"
            )

    for field in external_adapter.LANE_FIELDS[lane]:
        aliases = tuple(external_adapter.FIELD_ALIASES[field])
        if not _has_any(lower_fields, aliases):
            raise G5ExternalSourceManifestFinalizerError(
                f"source file {path} is missing a supported column for {field}"
            )
    return fields, row_count


def _load_template(path: Path) -> tuple[dict, dict[str, dict]]:
    raw = _load_json(path, label="manifest template")
    if str(raw.get("schema_version") or "") != MANIFEST_SCHEMA_VERSION:
        raise G5ExternalSourceManifestFinalizerError(
            f"manifest template schema_version must equal {MANIFEST_SCHEMA_VERSION}"
        )
    if raw.get("intake_ready") is not False:
        raise G5ExternalSourceManifestFinalizerError(
            "manifest template must be explicitly intake_ready=false"
        )

    sources = raw.get("sources")
    if not isinstance(sources, list) or not sources:
        raise G5ExternalSourceManifestFinalizerError(
            "manifest template sources must be a non-empty list"
        )

    by_id: dict[str, dict] = {}
    for index, item in enumerate(sources, 1):
        if not isinstance(item, dict):
            raise G5ExternalSourceManifestFinalizerError(
                f"manifest template source {index} must be an object"
            )
        source_id = str(item.get("source_id") or "").strip()
        if not source_id or source_id in by_id:
            raise G5ExternalSourceManifestFinalizerError(
                f"manifest template source {index}: source_id must be unique and nonblank"
            )
        lane = str(item.get("lane") or "").strip().lower()
        target_kind = str(item.get("target_kind") or "").strip().lower()
        if lane not in external_adapter.LANE_FIELDS:
            raise G5ExternalSourceManifestFinalizerError(
                f"manifest template source {source_id}: unsupported lane"
            )
        if target_kind not in {"control", "treated"}:
            raise G5ExternalSourceManifestFinalizerError(
                f"manifest template source {source_id}: target_kind must be control or treated"
            )
        if str(item.get("expected_sha256") or "").strip():
            raise G5ExternalSourceManifestFinalizerError(
                f"manifest template source {source_id}: expected_sha256 must still be blank"
            )
        if str(item.get("authorization_reference") or "").strip():
            raise G5ExternalSourceManifestFinalizerError(
                f"manifest template source {source_id}: authorization_reference must still be blank"
            )
        if str(item.get("source_name") or "").strip():
            raise G5ExternalSourceManifestFinalizerError(
                f"manifest template source {source_id}: source_name must still be blank"
            )
        by_id[source_id] = dict(item)
    return raw, by_id


def _load_bindings(path: Path) -> dict[str, dict[str, str]]:
    raw = _load_json(path, label="bindings file")
    if str(raw.get("schema_version") or "") != BINDINGS_SCHEMA_VERSION:
        raise G5ExternalSourceManifestFinalizerError(
            f"bindings schema_version must equal {BINDINGS_SCHEMA_VERSION}"
        )
    bindings = raw.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise G5ExternalSourceManifestFinalizerError(
            "bindings must be a non-empty list"
        )

    out: dict[str, dict[str, str]] = {}
    for index, item in enumerate(bindings, 1):
        if not isinstance(item, dict):
            raise G5ExternalSourceManifestFinalizerError(
                f"binding {index} must be an object"
            )
        source_id = str(item.get("source_id") or "").strip()
        if not source_id or source_id in out:
            raise G5ExternalSourceManifestFinalizerError(
                f"binding {index}: source_id must be unique and nonblank"
            )
        source_name = str(item.get("source_name") or "").strip()
        authorization_reference = str(
            item.get("authorization_reference") or ""
        ).strip()
        path_value = str(item.get("path") or "").strip()
        if not path_value or not source_name or not authorization_reference:
            raise G5ExternalSourceManifestFinalizerError(
                f"binding {source_id}: path, source_name, and authorization_reference are required"
            )
        out[source_id] = {
            "path": path_value,
            "source_name": source_name,
            "authorization_reference": authorization_reference,
        }
    return out


def build(
    *,
    template_manifest_path: Path,
    bindings_path: Path,
    output_dir: Path,
) -> dict:
    template_manifest_path = template_manifest_path.expanduser().resolve()
    bindings_path = bindings_path.expanduser().resolve()
    template, template_sources = _load_template(template_manifest_path)
    bindings = _load_bindings(bindings_path)

    template_ids = set(template_sources)
    binding_ids = set(bindings)
    if binding_ids != template_ids:
        missing = sorted(template_ids - binding_ids)
        extra = sorted(binding_ids - template_ids)
        raise G5ExternalSourceManifestFinalizerError(
            f"binding/source_id coverage mismatch: missing={missing}, extra={extra}"
        )

    finalized_sources: list[dict] = []
    source_receipts: list[dict[str, object]] = []

    for source_id in sorted(template_sources):
        source = dict(template_sources[source_id])
        binding = bindings[source_id]
        lane = str(source["lane"]).lower()

        scaffold_path = _resolve_path(
            template_manifest_path,
            str(source.get("path") or ""),
            label=f"scaffold source {source_id}",
        )
        recorded_template_sha = str(
            source.get("template_sha256") or ""
        ).strip().lower()
        if len(recorded_template_sha) != 64:
            raise G5ExternalSourceManifestFinalizerError(
                f"manifest template source {source_id}: template_sha256 is invalid"
            )
        if _sha256(scaffold_path) != recorded_template_sha:
            raise G5ExternalSourceManifestFinalizerError(
                f"manifest template source {source_id}: scaffold template hash mismatch"
            )

        real_path = _resolve_path(
            bindings_path,
            binding["path"],
            label=f"binding {source_id}",
        )
        if real_path == scaffold_path:
            raise G5ExternalSourceManifestFinalizerError(
                f"binding {source_id}: empty scaffold template may not be used as real source data"
            )

        source_fields, row_count = _preflight_source(
            real_path,
            lane=lane,
        )

        source_sha256 = _sha256(real_path)
        if source_sha256 == recorded_template_sha:
            raise G5ExternalSourceManifestFinalizerError(
                f"binding {source_id}: source content matches empty scaffold template"
            )

        source["path"] = str(real_path)
        source["expected_sha256"] = source_sha256
        source["authorization_reference"] = binding[
            "authorization_reference"
        ]
        source["source_name"] = binding["source_name"]
        source["status"] = "READY_FOR_INTAKE"
        finalized_sources.append(source)
        source_receipts.append(
            {
                "source_id": source_id,
                "target_kind": source["target_kind"],
                "lane": lane,
                "path": str(real_path),
                "sha256": source_sha256,
                "row_count": row_count,
                "field_count": len(source_fields),
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "g5_external_source_manifest.json"
    summary_path = output_dir / "g5_external_source_manifest_finalizer_summary.json"

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "purpose": (
            "Hash-bound finalized G5 external metadata source manifest. "
            "This file is structurally ready for g5_external_metadata_intake, "
            "but finalization alone does not make any source row G5 evidence."
        ),
        "research_use_only": True,
        "intake_ready": True,
        "sources": finalized_sources,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Finalize the fail-closed G5 external source scaffold by binding each "
            "source slot to a real local file, source name, authorization reference, "
            "and automatically computed SHA-256 without copying or fetching source data."
        ),
        "research_use_only": True,
        "template_source_count": len(template_sources),
        "binding_count": len(bindings),
        "finalized_source_count": len(finalized_sources),
        "all_source_ids_reconciled": binding_ids == template_ids,
        "intake_manifest_ready": True,
        "inputs": {
            "template_manifest": {
                "path": str(template_manifest_path),
                "sha256": _sha256(template_manifest_path),
            },
            "bindings": {
                "path": str(bindings_path),
                "sha256": _sha256(bindings_path),
            },
            "sources": source_receipts,
        },
        "outputs": {
            "finalized_manifest": str(manifest_path),
        },
        "policy": {
            "source_files_are_not_copied": True,
            "source_files_are_not_fetched": True,
            "source_hashes_are_computed_from_local_files": True,
            "authorization_reference_required": True,
            "source_name_required": True,
            "empty_scaffold_templates_may_not_be_finalized": True,
            "prohibited_retrospective_columns_fail_closed": True,
            "finalization_changes_canonical_g5_readiness": False,
            "finalized_manifest_is_g5_evidence": False,
            "purchase_performed": False,
        },
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Finalize the G5 external source manifest scaffold with local source "
            "bindings and computed SHA-256 identities."
        )
    )
    parser.add_argument("--template-manifest", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        template_manifest_path=args.template_manifest,
        bindings_path=args.bindings,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
