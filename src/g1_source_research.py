from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


class G1SourceResearchError(ValueError):
    pass


_ALLOWED_EVIDENCE_SOURCE_FAMILIES = frozenset({
    "official_newswire_archive",
    "issuer_investor_relations_archive",
    "preserved_wire_mirror",
    "sec_litigation_public_distribution_record",
    "federal_court_public_distribution_record",
    "ibes_announcement",
    "licensed_ibes_actuals",
})
_ALLOWED_TIMESTAMP_EVIDENCE_KINDS = frozenset({
    "publisher_timestamp",
    "explicit_release_clock",
    "licensed_actual_announcement_time",
})
_FIRST_TRADE_TIMEZONE = ZoneInfo("America/New_York")
_MAX_RELEASE_LAG_DAYS = 7


def _parse_exact_public_release_ts(value: object, *, probe_id: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise G1SourceResearchError(
            f"probe {probe_id} cannot be evidence without exact_public_release_ts"
        )
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G1SourceResearchError(
            f"probe {probe_id} exact_public_release_ts must be valid ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise G1SourceResearchError(
            f"probe {probe_id} exact_public_release_ts must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def _parse_first_trade_ts(value: object, *, event_id: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise G1SourceResearchError(
            f"current exclusion {event_id} is missing first_documented_illicit_trade_ts"
        )
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G1SourceResearchError(
            f"current exclusion {event_id} has invalid first_documented_illicit_trade_ts"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_FIRST_TRADE_TIMEZONE)
    return parsed.astimezone(timezone.utc)


def _validate_evidence_eligible_probe(
    probe: dict, exclusion_by_id: dict[str, dict]
) -> None:
    probe_id = str(probe.get("probe_id", "")).strip() or "<unnamed>"
    event_id = str(probe.get("event_id", "")).strip()
    if not event_id:
        raise G1SourceResearchError(
            f"probe {probe_id} cannot be evidence without event_id"
        )
    current = exclusion_by_id.get(event_id)
    if current is None:
        raise G1SourceResearchError(
            f"probe {probe_id} event_id is not a current fail-closed exclusion: {event_id}"
        )

    symbol = str(probe.get("historical_symbol", "")).strip()
    if symbol != str(current.get("historical_symbol", "")).strip():
        raise G1SourceResearchError(
            f"probe {probe_id} historical_symbol does not match event_id {event_id}"
        )
    if not probe.get("historical_event_match"):
        raise G1SourceResearchError(
            f"probe {probe_id} cannot be evidence without historical_event_match"
        )
    if not probe.get("exact_clock_observed"):
        raise G1SourceResearchError(
            f"probe {probe_id} cannot be evidence without exact_clock_observed"
        )
    if str(probe.get("timestamp_kind", "")).strip() != "first_public_release":
        raise G1SourceResearchError(
            f"probe {probe_id} timestamp_kind must be first_public_release"
        )

    evidence_kind = str(probe.get("timestamp_evidence_kind", "")).strip()
    if evidence_kind not in _ALLOWED_TIMESTAMP_EVIDENCE_KINDS:
        raise G1SourceResearchError(
            f"probe {probe_id} timestamp_evidence_kind is not admissible"
        )

    source_family = str(probe.get("source_family", "")).strip()
    if source_family not in _ALLOWED_EVIDENCE_SOURCE_FAMILIES:
        raise G1SourceResearchError(
            f"probe {probe_id} source_family is not admissible for an exact release clock"
        )
    if not str(probe.get("source_reference", "")).strip():
        raise G1SourceResearchError(
            f"probe {probe_id} cannot be evidence without source_reference"
        )
    if (
        source_family == "preserved_wire_mirror"
        and not str(probe.get("corroboration_reference", "")).strip()
    ):
        raise G1SourceResearchError(
            f"probe {probe_id} preserved_wire_mirror evidence requires corroboration_reference"
        )

    if source_family == "sec_litigation_public_distribution_record":
        source_reference = str(probe.get("source_reference", "")).strip()
        corroboration_reference = str(probe.get("corroboration_reference", "")).strip()
        if not source_reference.startswith(
            "https://www.sec.gov/files/litigation/complaints/"
        ):
            raise G1SourceResearchError(
                f"probe {probe_id} SEC litigation evidence requires an SEC complaint source_reference"
            )
        if not corroboration_reference.startswith(
            "https://www.sec.gov/Archives/edgar/data/"
        ):
            raise G1SourceResearchError(
                f"probe {probe_id} SEC litigation evidence requires independent SEC Exhibit corroboration"
            )
        if evidence_kind != "explicit_release_clock":
            raise G1SourceResearchError(
                f"probe {probe_id} SEC litigation evidence requires explicit_release_clock semantics"
            )
        if probe.get("public_distribution_explicit") is not True:
            raise G1SourceResearchError(
                f"probe {probe_id} SEC litigation evidence must explicitly identify public distribution"
            )

    if source_family == "federal_court_public_distribution_record":
        source_reference = str(probe.get("source_reference", "")).strip()
        corroboration_reference = str(probe.get("corroboration_reference", "")).strip()
        if not source_reference.startswith(
            "https://www.supremecourt.gov/DocketPDF/"
        ):
            raise G1SourceResearchError(
                f"probe {probe_id} federal-court evidence requires an official Supreme Court docket source_reference"
            )
        if not corroboration_reference.startswith(
            "https://www.sec.gov/Archives/edgar/data/"
        ):
            raise G1SourceResearchError(
                f"probe {probe_id} federal-court evidence requires independent SEC Exhibit corroboration"
            )
        if evidence_kind != "explicit_release_clock":
            raise G1SourceResearchError(
                f"probe {probe_id} federal-court evidence requires explicit_release_clock semantics"
            )
        if probe.get("public_distribution_explicit") is not True:
            raise G1SourceResearchError(
                f"probe {probe_id} federal-court evidence must explicitly identify public distribution"
            )

    release_ts = _parse_exact_public_release_ts(
        probe.get("exact_public_release_ts"), probe_id=probe_id
    )
    trade_ts = _parse_first_trade_ts(
        current.get("first_documented_illicit_trade_ts"), event_id=event_id
    )
    if release_ts <= trade_ts:
        raise G1SourceResearchError(
            f"probe {probe_id} exact public release must be strictly after first documented trade"
        )

    release_local = release_ts.astimezone(_FIRST_TRADE_TIMEZONE)
    trade_local = trade_ts.astimezone(_FIRST_TRADE_TIMEZONE)
    if release_local.date() > trade_local.date() + timedelta(days=_MAX_RELEASE_LAG_DAYS):
        raise G1SourceResearchError(
            f"probe {probe_id} exact public release exceeds seven calendar days after first documented trade"
        )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_research_map(research: dict, exclusions: dict) -> dict:
    if str(research.get("schema_version", "")) != "1":
        raise G1SourceResearchError("unsupported research schema_version")
    if not research.get("research_use_only"):
        raise G1SourceResearchError("source research must remain research_use_only")

    exclusion_rows = exclusions.get("exclusions", [])
    exclusion_by_id = {str(row.get("event_id")): row for row in exclusion_rows}
    seen: set[str] = set()

    for item in research.get("priority_events", []):
        event_id = str(item.get("event_id", ""))
        if not event_id or event_id in seen:
            raise G1SourceResearchError(f"duplicate or missing priority event_id: {event_id!r}")
        seen.add(event_id)
        current = exclusion_by_id.get(event_id)
        if current is None:
            raise G1SourceResearchError(f"priority event is not in current fail-closed exclusions: {event_id}")
        if str(current.get("historical_symbol", "")) != str(item.get("historical_symbol", "")):
            raise G1SourceResearchError(f"symbol mismatch for priority event: {event_id}")
        if str(current.get("resolution_status", "")) != "FAIL_CLOSED_NO_ADMISSIBLE_EXACT_PUBLIC_RELEASE_CLOCK_TIME":
            raise G1SourceResearchError(f"priority event is not fail-closed: {event_id}")

    for probe in research.get("validation_probes", []):
        if not probe.get("evidence_eligible"):
            continue
        _validate_evidence_eligible_probe(probe, exclusion_by_id)

    current_state = research.get("current_g1_state", {})
    g1_state = exclusions.get("g1_state", {})
    if int(current_state.get("required_event_count", -1)) != int(g1_state.get("required", -2)):
        raise G1SourceResearchError("research required_event_count does not match exclusions")
    if int(current_state.get("exact_resolved_event_records", -1)) != int(g1_state.get("exact_resolved", -2)):
        raise G1SourceResearchError("research exact_resolved_event_records does not match exclusions")
    if int(current_state.get("reviewed_excluded_event_records", -1)) != int(g1_state.get("reviewed_excluded", -2)):
        raise G1SourceResearchError("research reviewed_excluded_event_records does not match exclusions")

    return {
        "priority_event_count": len(seen),
        "validation_probe_count": len(research.get("validation_probes", [])),
        "public_one_stop_exact_timestamp_dataset_found": bool(
            research.get("consolidated_source_search", {}).get(
                "public_one_stop_exact_timestamp_dataset_found", False
            )
        ),
        "licensed_complete_candidate": deepcopy(
            research.get("consolidated_source_search", {}).get("licensed_complete_candidate", {})
        ),
    }


def build_priority_queue(research: dict, exclusions: dict) -> dict:
    summary = validate_research_map(research, exclusions)
    exclusion_by_id = {
        str(row.get("event_id")): row for row in exclusions.get("exclusions", [])
    }
    queue = []
    for item in sorted(
        research.get("priority_events", []),
        key=lambda row: (int(row.get("priority_rank", 10**9)), str(row.get("event_id", ""))),
    ):
        current = exclusion_by_id[str(item["event_id"])]
        queue.append(
            {
                "priority_rank": int(item["priority_rank"]),
                "event_id": str(item["event_id"]),
                "historical_symbol": str(item["historical_symbol"]),
                "first_documented_illicit_trade_ts": str(
                    current.get("first_documented_illicit_trade_ts", "")
                ),
                "current_resolution_status": str(current.get("resolution_status", "")),
                "research_signal": str(item.get("research_signal", "")),
                "next_source_families": list(item.get("next_source_families", [])),
                "evidence_requirement": (
                    "authoritative/authorized timezone-aware exact first-public release timestamp "
                    "matching this historical event"
                ),
            }
        )

    return {
        "schema_version": "1",
        "status": "RESEARCH_PRIORITIES_READY",
        "research_use_only": True,
        "required_event_count": int(exclusions["g1_state"]["required"]),
        "exact_resolved_event_records": int(exclusions["g1_state"]["exact_resolved"]),
        "reviewed_excluded_event_records": int(exclusions["g1_state"]["reviewed_excluded"]),
        **summary,
        "queue": queue,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate G1 source research and emit a fail-closed sweep queue.")
    parser.add_argument(
        "--research-map",
        type=Path,
        default=Path("data/public/metadata/g1_source_research_20260928.json"),
    )
    parser.add_argument(
        "--exclusions",
        type=Path,
        default=Path("data/processed/authorized_input_real/g1_final_timing_exclusions.json"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = build_priority_queue(_read_json(args.research_map), _read_json(args.exclusions))
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
