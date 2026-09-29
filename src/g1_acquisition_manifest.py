from __future__ import annotations

import argparse
import csv
import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path


SCHEMA_VERSION = "1"
DEFAULT_RESOLUTIONS = Path("data/processed/authorized_input_real/announcement_resolutions.csv")
DEFAULT_EXCLUSIONS = Path("data/processed/authorized_input_real/g1_final_timing_exclusions.json")
DEFAULT_RESEARCH = Path("data/public/metadata/g1_source_research_20260928.json")
DEFAULT_OUTPUT = Path("data/public/metadata/g1_acquisition_manifest.json")


class G1AcquisitionManifestError(ValueError):
    pass


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _add_days(value: str, days: int) -> str:
    return (date.fromisoformat(value) + timedelta(days=days)).isoformat()


def _preferred_public_families(research: dict) -> list[dict]:
    rows = sorted(
        research.get("preferred_public_source_families", []),
        key=lambda row: (int(row.get("rank", 10**9)), str(row.get("source_family", ""))),
    )
    return rows


def build_manifest_from_data(
    resolution_rows: list[dict[str, str]],
    exclusions: dict,
    research: dict,
) -> dict:
    if len(resolution_rows) != 174:
        raise G1AcquisitionManifestError(
            f"expected 174 announcement resolution rows, got {len(resolution_rows)}"
        )

    exclusion_rows = exclusions.get("exclusions", [])
    exclusion_by_id = {str(row.get("event_id", "")): row for row in exclusion_rows}
    if len(exclusion_by_id) != len(exclusion_rows):
        raise G1AcquisitionManifestError("duplicate event_id in final G1 exclusion dossier")

    priority_rows = research.get("priority_events", [])
    priority_by_id = {
        str(row.get("event_id", "")): row for row in priority_rows
        if str(row.get("event_id", "")).strip()
    }

    preferred = _preferred_public_families(research)
    default_families = [str(row.get("source_family", "")) for row in preferred]
    licensed = deepcopy(
        research.get("consolidated_source_search", {}).get("licensed_complete_candidate", {})
    )
    provider = str(
        licensed.get("provider_family", "LSEG I/B/E/S Historical Estimates / Actuals")
    )
    adapter = str(licensed.get("repository_adapter", "src/g1_ibes_timestamp_adapter.py"))
    required_fields = list(
        licensed.get(
            "required_fields",
            ["TICKER or OFTIC", "ANNDATS_ACT", "ANNTIMS_ACT"],
        )
    )

    seen: set[str] = set()
    items: list[dict] = []
    work_queue: list[dict] = []
    exact_resolved = 0
    acquisition_needed = 0
    public_file_present = 0
    no_public_candidate = 0
    explicit_priorities = 0

    for row in resolution_rows:
        event_id = str(row.get("event_id", "")).strip()
        if not event_id or event_id in seen:
            raise G1AcquisitionManifestError(
                f"duplicate or missing event_id in announcement resolutions: {event_id!r}"
            )
        seen.add(event_id)

        common = {
            "acquisition_status": "",
            "current_resolution_status": str(row.get("resolution_status", "")),
            "dedupe_key": f"g1-exact-public-release:{event_id}",
            "event_date": str(row.get("event_date", "")),
            "event_id": event_id,
            "first_documented_illicit_trade_ts": str(
                row.get("first_documented_illicit_trade_ts", "")
            ),
            "historical_symbol": str(row.get("historical_symbol", "")),
            "research_use_only": True,
        }

        status = str(row.get("resolution_status", ""))
        if status == "resolved_exact_public_timestamp":
            if not str(row.get("public_announcement_ts", "")).strip():
                raise G1AcquisitionManifestError(
                    f"resolved event lacks public_announcement_ts: {event_id}"
                )
            exact_resolved += 1
            items.append({
                **common,
                "acquisition_status": "RESOLVED_NO_ACTION",
                "public_announcement_ts": str(row.get("public_announcement_ts", "")),
                "resolved_source": {
                    "source_family": str(row.get("source_family", "")),
                    "source_grade": str(row.get("source_grade", "")),
                    "source_id": str(row.get("source_id", "")),
                    "source_reference": str(row.get("source_reference", "")),
                    "timestamp_confidence": str(row.get("timestamp_confidence", "")),
                    "timestamp_kind": str(row.get("timestamp_kind", "")),
                },
                "routes": [],
            })
            continue

        if status != "excluded_fail_closed":
            raise G1AcquisitionManifestError(
                f"unsupported announcement resolution status for {event_id}: {status}"
            )

        acquisition_needed += 1
        exclusion = exclusion_by_id.get(event_id)
        if exclusion is None:
            raise G1AcquisitionManifestError(
                f"excluded resolution is missing final exclusion dossier row: {event_id}"
            )

        file_status = str(exclusion.get("public_release_file_status", "UNKNOWN"))
        if "PUBLIC_RELEASE_FILE_PRESENT" in file_status:
            public_file_present += 1
        if file_status == "NO_PUBLIC_REPLICATION_CANDIDATE_FILE":
            no_public_candidate += 1

        priority = priority_by_id.get(event_id)
        if priority is not None:
            explicit_priorities += 1

        if "PUBLIC_RELEASE_FILE_PRESENT" in file_status:
            public_mode = "clock_recovery"
            route_order = ["public_exact_clock_recovery", "licensed_ibes_bulk"]
            queue_priority = int(priority.get("priority_rank")) if priority else 1000
        elif file_status == "NO_PUBLIC_REPLICATION_CANDIDATE_FILE":
            public_mode = "release_discovery"
            route_order = ["licensed_ibes_bulk", "public_release_discovery"]
            queue_priority = int(priority.get("priority_rank")) if priority else 2000
        else:
            public_mode = "release_discovery"
            route_order = ["public_release_discovery", "licensed_ibes_bulk"]
            queue_priority = int(priority.get("priority_rank")) if priority else 2000

        families = (
            list(priority.get("next_source_families", []))
            if priority and priority.get("next_source_families")
            else list(default_families)
        )

        item = {
            **common,
            "acquisition_status": "NEEDS_EXACT_PUBLIC_RELEASE_CLOCK",
            "public_release_file_status": file_status,
            "research_priority_rank": (
                int(priority.get("priority_rank")) if priority else None
            ),
            "research_signal": (
                str(priority.get("research_signal")) if priority else None
            ),
            "route_order": route_order,
            "routes": {
                "licensed_ibes": {
                    "adapter": adapter,
                    "entitlement_required": True,
                    "lawful_access_only": True,
                    "provider_family": provider,
                    "required_fields": list(required_fields),
                },
                "public_archive": {
                    "exact_first_public_clock_required": True,
                    "mode": public_mode,
                    "prohibited_timestamp_substitutes": [
                        "archive_capture_time",
                        "edgar_acceptance_time",
                        "inferred_time",
                        "scheduled_release_time",
                    ],
                    "source_families": families,
                },
            },
            "search_window": {
                "end_date": _add_days(str(row.get("event_date", "")), 7),
                "start_date": str(row.get("event_date", "")),
            },
        }
        items.append(item)
        work_queue.append({
            "dedupe_key": item["dedupe_key"],
            "event_date": item["event_date"],
            "event_id": event_id,
            "historical_symbol": item["historical_symbol"],
            "public_release_file_status": file_status,
            "queue_priority": queue_priority,
            "research_priority_rank": item["research_priority_rank"],
            "route_order": list(route_order),
        })

    g1_state = exclusions.get("g1_state", {})
    if exact_resolved != int(g1_state.get("exact_resolved", -1)):
        raise G1AcquisitionManifestError(
            "announcement resolutions disagree with final exact-resolved count"
        )
    if acquisition_needed != int(g1_state.get("reviewed_excluded", -1)):
        raise G1AcquisitionManifestError(
            "announcement resolutions disagree with final reviewed-exclusion count"
        )
    if exact_resolved + acquisition_needed != len(resolution_rows):
        raise G1AcquisitionManifestError("G1 acquisition manifest does not reconcile")

    items.sort(key=lambda row: (row["event_date"], row["event_id"]))
    work_queue.sort(
        key=lambda row: (
            int(row["queue_priority"]),
            row["event_date"],
            row["event_id"],
        )
    )

    research_state = research.get("current_g1_state", {})
    research_exact = research_state.get("exact_resolved_event_records")
    research_excluded = research_state.get("reviewed_excluded_event_records")

    return {
        "authoritative_sources": {
            "announcement_resolutions": str(DEFAULT_RESOLUTIONS),
            "final_exclusions": str(DEFAULT_EXCLUSIONS),
            "research_hints": str(DEFAULT_RESEARCH),
        },
        "items": items,
        "licensed_bulk_route": {
            "adapter": adapter,
            "entitlement_required": True,
            "lawful_access_only": True,
            "likely_full_universe_path": bool(
                licensed.get("likely_full_universe_path", False)
            ),
            "provider_family": provider,
            "request_event_count": acquisition_needed,
            "required_fields": list(required_fields),
        },
        "public_source_policy": [
            {
                "admissibility": str(row.get("admissibility", "")),
                "rank": int(row.get("rank")),
                "source_family": str(row.get("source_family", "")),
            }
            for row in preferred
        ],
        "purpose": (
            "Deterministic acquisition and source-routing manifest for G1 exact "
            "first-public announcement clocks."
        ),
        "research_use_only": True,
        "schema_version": SCHEMA_VERSION,
        "state": {
            "accounted_for": exact_resolved + acquisition_needed,
            "acquisition_needed": acquisition_needed,
            "event_count": len(resolution_rows),
            "exact_resolved": exact_resolved,
            "research_hint_exact_resolved": research_exact,
            "research_hint_excluded": research_excluded,
            "research_hint_state_matches_authoritative": (
                research_exact == exact_resolved
                and research_excluded == acquisition_needed
            ),
        },
        "summary": {
            "explicit_research_priorities": explicit_priorities,
            "no_public_replication_candidate": no_public_candidate,
            "public_release_file_present_without_clock": public_file_present,
            "resolved_no_action": exact_resolved,
            "routed_for_acquisition": acquisition_needed,
        },
        "work_queue": work_queue,
    }


def build_manifest(
    resolutions_path: Path = DEFAULT_RESOLUTIONS,
    exclusions_path: Path = DEFAULT_EXCLUSIONS,
    research_path: Path = DEFAULT_RESEARCH,
) -> dict:
    return build_manifest_from_data(
        _read_csv(resolutions_path),
        _read_json(exclusions_path),
        _read_json(research_path),
    )


def render_manifest(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic G1 acquisition/source-routing manifest."
    )
    parser.add_argument("--resolutions", type=Path, default=DEFAULT_RESOLUTIONS)
    parser.add_argument("--exclusions", type=Path, default=DEFAULT_EXCLUSIONS)
    parser.add_argument("--research", type=Path, default=DEFAULT_RESEARCH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    rendered = render_manifest(
        build_manifest(args.resolutions, args.exclusions, args.research)
    )
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            return 2
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
