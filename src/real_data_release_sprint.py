from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

PROHIBITED_OUTPUTS = [
    "BUY", "SELL", "expected_return", "target_price", "position_size", "order", "execution_instruction"
]

CORE_KEYS = {
    ("nyse_daily_taq", "equity_trade"),
    ("nyse_daily_taq", "equity_quote"),
}
OPTION_KEYS = {
    ("cboe_option_trades", "option_trade"),
    ("cboe_option_quotes", "option_quote"),
}
ITCH_V4_FAMILY = "nasdaq_itch_4_1_decoded"
ITCH_V5_FAMILY = "nasdaq_itch_5_0_decoded"
ITCH_RECORD_KIND = "itch_decoded"
ITCH_V5_START_DATE = "2014-04-08"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [{str(k): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = fields or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def freeze_requirements(
    *,
    source_date_requirements: Path,
    event_exchange_resolutions: Path,
    outdir: Path,
) -> dict:
    reqs = _read_csv(source_date_requirements)
    exchanges = _read_csv(event_exchange_resolutions)

    core = [
        r for r in reqs
        if r.get("requirement") == "required_core"
        and (r.get("source_family"), r.get("record_kind")) in CORE_KEYS
    ]
    options = [
        r for r in reqs
        if r.get("requirement") == "required_full_replication"
        and (r.get("source_family"), r.get("record_kind")) in OPTION_KEYS
    ]
    legacy_itch = [
        r for r in reqs
        if r.get("requirement") == "conditional"
        and r.get("record_kind") == ITCH_RECORD_KIND
    ]
    nasdaq_events = []
    for r in exchanges:
        if r.get("resolution_status") != "resolved" or r.get("primary_exchange") != "XNAS":
            continue
        event_date = r["trade_date"]
        family = ITCH_V4_FAMILY if event_date < ITCH_V5_START_DATE else ITCH_V5_FAMILY
        version = "ITCH-4.1" if family == ITCH_V4_FAMILY else "ITCH-5.0"
        nasdaq_events.append({
            "event_id": r["event_id"],
            "historical_symbol": r["historical_symbol"],
            "event_date": event_date,
            "primary_exchange": r["primary_exchange"],
            "requirement": "required_event_order_flow",
            "source_family": family,
            "record_kind": ITCH_RECORD_KIND,
            "format_version": version,
            "research_use_only": "1",
        })

    if len(core) != 828:
        raise ValueError(f"expected 828 core source-date rows, found {len(core)}")
    if len(options) != 828:
        raise ValueError(f"expected 828 option source-date rows, found {len(options)}")
    if len(legacy_itch) != 414:
        raise ValueError(f"expected 414 legacy conditional ITCH date rows, found {len(legacy_itch)}")
    if len(nasdaq_events) != 80:
        raise ValueError(f"expected 80 G3-confirmed Nasdaq events, found {len(nasdaq_events)}")

    outdir.mkdir(parents=True, exist_ok=True)
    _write_csv(outdir / "g2_core_source_date_requirements.csv", core)
    _write_csv(outdir / "g2_option_source_date_requirements.csv", options)
    _write_csv(outdir / "g2_itch_event_requirements.csv", nasdaq_events)

    inventory = []
    for r in core + options:
        inventory.append({
            "source_family": r["source_family"],
            "record_kind": r["record_kind"],
            "trade_date": r["trade_date"],
            "required_symbols": r["historical_symbols"],
            "source_path": "",
            "license_reference": "",
            "data_classification": "authorized_historical_market_data",
            "format_version": "",
            "status": "MISSING_SOURCE",
        })
    _write_csv(
        outdir / "market_source_inventory.template.csv",
        inventory,
        [
            "source_family", "record_kind", "trade_date", "required_symbols",
            "source_path", "license_reference", "data_classification", "format_version", "status",
        ],
    )

    blueprint = {
        "schema_version": "1",
        "purpose": "Production source-contract blueprint for the real-data release sprint. This is not itself an authorization claim.",
        "authorization": {
            "authorized_must_be_true": True,
            "non_synthetic_class": "authorized_historical_market_data",
            "license_reference_required": True,
            "credentials_in_contract_prohibited": True,
        },
        "source_types": {
            "equity_trade": {
                "accepted_families": ["nyse_daily_taq", "generic_authorized_market_data"],
                "required_canonical_fields": ["timestamp_or_date+time", "symbol", "price", "size"],
            },
            "equity_quote": {
                "accepted_families": ["nyse_daily_taq", "generic_authorized_market_data"],
                "required_canonical_fields": ["timestamp_or_date+time", "symbol", "bid", "ask", "bid_size", "ask_size"],
            },
            "option_trade": {
                "accepted_families": ["cboe_option_trades", "generic_authorized_market_data"],
                "required_canonical_fields": [
                    "timestamp_or_date+time", "underlying_symbol", "option_symbol",
                    "expiration", "strike", "option_type", "price", "size",
                ],
            },
            "option_quote": {
                "accepted_families": ["cboe_option_quotes", "generic_authorized_market_data"],
                "required_canonical_fields": [
                    "timestamp_or_date+time", "underlying_symbol", "option_symbol",
                    "expiration", "strike", "option_type", "bid", "ask", "bid_size", "ask_size",
                ],
            },
            "itch_decoded": {
                "accepted_families": ["nasdaq_itch_4_1_decoded", "nasdaq_itch_5_0_decoded"],
                "required_canonical_fields": [
                    "timestamp", "message_type", "symbol", "order_reference", "side",
                    "shares", "price", "executed_shares", "execution_price", "match_number",
                    "printable", "cancelled_shares", "new_order_reference",
                ],
                "format_version_required": True,
                "scope": "G3-confirmed Nasdaq event rows only unless a separate point-in-time listing-history source proves additional baseline symbol-dates.",
            },
        },
        "content_validation": {
            "file_existence_is_not_coverage": True,
            "declared_trade_date_must_match_parsed_rows": True,
            "all_required_symbols_must_be_observed": True,
            "synthetic_rows_never_satisfy_G2": True,
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    _write_json(outdir / "production_source_contract_blueprint.json", blueprint)

    manifest = {
        "schema_version": "1",
        "purpose": "Frozen real-data requirements receipt for Steps 1-12.",
        "source_date_requirements_path": str(source_date_requirements),
        "source_date_requirements_sha256": _sha256(source_date_requirements),
        "event_exchange_resolutions_path": str(event_exchange_resolutions),
        "event_exchange_resolutions_sha256": _sha256(event_exchange_resolutions),
        "counts": {
            "core_equity_source_date_rows": len(core),
            "option_source_date_rows": len(options),
            "total_required_g2_source_date_rows": len(core) + len(options),
            "legacy_conditional_itch_market_date_rows": len(legacy_itch),
            "g3_confirmed_nasdaq_event_rows": len(nasdaq_events),
            "g3_confirmed_nasdaq_itch_4_1_event_rows": sum(r["source_family"] == ITCH_V4_FAMILY for r in nasdaq_events),
            "g3_confirmed_nasdaq_itch_5_0_event_rows": sum(r["source_family"] == ITCH_V5_FAMILY for r in nasdaq_events),
            "unique_g3_confirmed_nasdaq_event_dates": len({r["event_date"] for r in nasdaq_events}),
        },
        "artifacts": {
            "core": "g2_core_source_date_requirements.csv",
            "options": "g2_option_source_date_requirements.csv",
            "itch_events": "g2_itch_event_requirements.csv",
            "inventory_template": "market_source_inventory.template.csv",
            "contract_blueprint": "production_source_contract_blueprint.json",
        },
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    _write_json(outdir / "requirements_manifest.json", manifest)
    return manifest


def refresh_coverage(
    *,
    coverage_summary_path: Path,
    metadata_readiness_path: Path,
    metadata_quality_path: Path,
    requirements_manifest_path: Path,
    unresolved_gates_path: Path,
) -> dict:
    summary = json.loads(coverage_summary_path.read_text(encoding="utf-8"))
    readiness = json.loads(metadata_readiness_path.read_text(encoding="utf-8"))
    quality = json.loads(metadata_quality_path.read_text(encoding="utf-8"))
    req_manifest = json.loads(requirements_manifest_path.read_text(encoding="utf-8"))

    g1_required = int(readiness.get("event_count", summary.get("event_count", 0)) or 0)
    g1_exact = int(readiness.get("announcement_exact_resolved", 0) or 0)
    g1_excluded = int(readiness.get("announcement_events_excluded", 0) or 0)
    g1_unresolved = int(readiness.get("announcement_unresolved", 0) or 0)
    if g1_required <= 0 or min(g1_exact, g1_excluded, g1_unresolved) < 0:
        raise ValueError("invalid G1 readiness counts")
    if g1_exact + g1_excluded + g1_unresolved != g1_required:
        raise ValueError("G1 readiness counts do not reconcile to event_count")

    market_ready = bool((summary.get("contract_audit") or {}).get("ready_for_real_backfill"))
    blockers = []
    if not market_ready:
        blockers.append("G2_REAL_MARKET_DATA")
    if not readiness.get("ready_g1_exact_timing_analysis"):
        blockers.append("G1_EXACT_TIMING_ANALYSIS")
    if not readiness.get("ready_g5_model_evaluation_controls"):
        blockers.append("G5_MODEL_EVALUATION_CONTROLS")
    if not quality.get("quality_gate_clear"):
        blockers.append("G6_METADATA_QUALITY")

    summary["metadata_gate_overlay"] = {
        "G1_ANNOUNCEMENT_TIMES": "READY_WITH_REVIEWED_EXCLUSIONS" if readiness.get("ready_g1_announcement_times") else "BLOCKING",
        "G1_EXACT_TIMING_ANALYSIS": "READY" if readiness.get("ready_g1_exact_timing_analysis") else "BLOCKING",
        "G3_PRIMARY_LISTING_HISTORY": "READY" if readiness.get("ready_g3_primary_listing_history") else "BLOCKING",
        "G4_SHARES_OUTSTANDING": "READY_WITH_REVIEWED_EXCLUSIONS" if readiness.get("ready_g4_shares_outstanding") else "BLOCKING",
        "G5_MATCHED_CONTROL_UNIVERSE": "READY_WITH_REVIEWED_EXCLUSIONS" if readiness.get("ready_g5_matched_control_universe") else "BLOCKING",
        "G5_MODEL_EVALUATION_CONTROLS": "READY" if readiness.get("ready_g5_model_evaluation_controls") else "BLOCKING",
        "G6_METADATA_QUALITY": "READY" if quality.get("quality_gate_clear") else "BLOCKING",
    }
    summary["metadata_readiness_sha256"] = _sha256(metadata_readiness_path)
    summary["metadata_quality_sha256"] = _sha256(metadata_quality_path)
    summary["g3_conditioned_itch_event_rows"] = req_manifest["counts"]["g3_confirmed_nasdaq_event_rows"]
    summary["legacy_conditional_itch_market_date_rows"] = req_manifest["counts"]["legacy_conditional_itch_market_date_rows"]
    summary["missing_exact_announcement_timestamps"] = g1_required - g1_exact
    summary["blocking_gates"] = blockers
    summary["ready_for_non_synthetic_champion_challenger_comparison"] = len(blockers) == 0
    summary["coverage_summary_semantics"] = (
        "G1/G3/G4/G5 coarse metadata gates reflect current canonical metadata accounting. "
        "Exact timing and genuine model-control eligibility remain separate release locks."
    )
    coverage_summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    gates = [
        {
            "gate_id": "G1_ANNOUNCEMENT_TIMES",
            "status": summary["metadata_gate_overlay"]["G1_ANNOUNCEMENT_TIMES"],
            "required_rows": "174",
            "requirement": "All events accounted by exact timestamp or reviewed fail-closed exclusion.",
            "resolution": "Coarse accounting gate complete; exact-timing analysis remains separate.",
        },
        {
            "gate_id": "G1_EXACT_TIMING_ANALYSIS",
            "status": summary["metadata_gate_overlay"]["G1_EXACT_TIMING_ANALYSIS"],
            "required_rows": "174",
            "requirement": "Authoritative exact first-public announcement timestamp for every event.",
            "resolution": "Supply authorized I/B/E/S ANNDATS_ACT+ANNTIMS_ACT or independently verified exact newswire timestamps.",
        },
        {
            "gate_id": "G2_REAL_MARKET_DATA",
            "status": "READY" if market_ready else "BLOCKING",
            "required_rows": "1656",
            "requirement": "828 core equity + 828 option source-date rows, content validated and non-synthetic.",
            "resolution": "Populate a real authorized historical market source contract and rerun content validation.",
        },
        {
            "gate_id": "G3_PRIMARY_LISTING_HISTORY",
            "status": summary["metadata_gate_overlay"]["G3_PRIMARY_LISTING_HISTORY"],
            "required_rows": "174",
            "requirement": "Point-in-time primary listing exchange for every event.",
            "resolution": "Complete.",
        },
        {
            "gate_id": "G4_SHARES_OUTSTANDING",
            "status": summary["metadata_gate_overlay"]["G4_SHARES_OUTSTANDING"],
            "required_rows": "3828",
            "requirement": "All symbol-dates accounted by exact shares or reviewed fail-closed exclusion.",
            "resolution": "Complete at coarse accounting layer.",
        },
        {
            "gate_id": "G5_MATCHED_CONTROL_UNIVERSE",
            "status": summary["metadata_gate_overlay"]["G5_MATCHED_CONTROL_UNIVERSE"],
            "required_rows": "72",
            "requirement": "All event dates accounted by real controls or reviewed fail-closed exclusion.",
            "resolution": "Coarse accounting gate complete; model-evaluation controls remain separate.",
        },
        {
            "gate_id": "G5_MODEL_EVALUATION_CONTROLS",
            "status": summary["metadata_gate_overlay"]["G5_MODEL_EVALUATION_CONTROLS"],
            "required_rows": "72",
            "requirement": "Every event date has >=3 genuine point-in-time controls with complete pre-event covariates.",
            "resolution": "Supply authorized point-in-time control metadata and rerun matching.",
        },
        {
            "gate_id": "G6_METADATA_QUALITY",
            "status": summary["metadata_gate_overlay"]["G6_METADATA_QUALITY"],
            "required_rows": "1",
            "requirement": "Metadata quality gate clear for non-synthetic evaluation.",
            "resolution": "Requires the exact-timing and real-control locks plus real market-data coverage.",
        },
    ]
    _write_csv(
        unresolved_gates_path,
        gates,
        ["gate_id", "status", "required_rows", "requirement", "resolution"],
    )
    return summary


def build_status(
    *,
    requirements_manifest_path: Path,
    coverage_summary_path: Path,
    metadata_readiness_path: Path,
    metadata_quality_path: Path,
    outpath: Path,
) -> dict:
    req = json.loads(requirements_manifest_path.read_text(encoding="utf-8"))
    cov = json.loads(coverage_summary_path.read_text(encoding="utf-8"))
    meta = json.loads(metadata_readiness_path.read_text(encoding="utf-8"))
    quality = json.loads(metadata_quality_path.read_text(encoding="utf-8"))
    audit = cov.get("contract_audit") or {}

    real_covered = int(audit.get("real_authorized_required_rows_covered", 0) or 0)
    core_required = int(req["counts"]["core_equity_source_date_rows"])
    option_required = int(req["counts"]["option_source_date_rows"])
    all_required = core_required + option_required

    g1_required = int(meta.get("event_count", 0) or 0)
    g1_exact = int(meta.get("announcement_exact_resolved", 0) or 0)
    g1_excluded = int(meta.get("announcement_events_excluded", 0) or 0)
    g1_unresolved = int(meta.get("announcement_unresolved", 0) or 0)
    if g1_required <= 0 or min(g1_exact, g1_excluded, g1_unresolved) < 0:
        raise ValueError("invalid G1 readiness counts")
    if g1_exact + g1_excluded + g1_unresolved != g1_required:
        raise ValueError("G1 readiness counts do not reconcile to event_count")
    g1_exact_complete = (
        bool(meta.get("ready_g1_exact_timing_analysis"))
        and g1_exact == g1_required
        and g1_excluded == 0
        and g1_unresolved == 0
    )

    # Current repository has no non-synthetic source rows, so the split is provably zero.
    # Once a real contract is present, the existing coverage planner remains the source of truth
    # for total G2 coverage and this sprint must be rerun with that contract.
    if real_covered == 0:
        core_covered = 0
        option_covered = 0
    else:
        # Do not guess the split when only the aggregate audit is available.
        core_covered = None
        option_covered = None

    steps = [
        {"step": 1, "name": "Freeze exact G2 requirement list", "status": "PASS",
         "evidence": f"{core_required} core + {option_required} options = {all_required} required source-date rows"},
        {"step": 2, "name": "Define real-data source contract", "status": "PASS",
         "evidence": "production_source_contract_blueprint.json + 1,656-row source inventory template"},
        {"step": 3, "name": "Equity-trade ingestion pipeline", "status": "PASS",
         "evidence": "historical_market_backfill production parser + content coverage validation"},
        {"step": 4, "name": "Equity-quote ingestion pipeline", "status": "PASS",
         "evidence": "historical_market_backfill production parser + quote schema validation"},
        {"step": 5, "name": "Complete 828 core equity source-date rows",
         "status": "PASS" if real_covered >= all_required or core_covered == core_required else "SOURCE_BLOCKED",
         "evidence": f"real authorized aggregate coverage={real_covered}/{all_required}; core-specific covered={core_covered if core_covered is not None else 'requires real-contract rerun'}"},
        {"step": 6, "name": "Options trade/quote ingestion pipeline", "status": "PASS",
         "evidence": "option trade + option quote production schemas and parsers are installed"},
        {"step": 7, "name": "Complete 828 option source-date rows",
         "status": "PASS" if real_covered >= all_required or option_covered == option_required else "SOURCE_BLOCKED",
         "evidence": f"real authorized aggregate coverage={real_covered}/{all_required}; option-specific covered={option_covered if option_covered is not None else 'requires real-contract rerun'}"},
        {"step": 8, "name": "Conditional Nasdaq ITCH",
         "status": "SOURCE_BLOCKED",
         "evidence": f"{req['counts']['g3_confirmed_nasdaq_event_rows']} G3-confirmed Nasdaq events frozen; decoded authorized ITCH files are not present"},
        {"step": 9, "name": "Replace G1 timing exclusions with exact clocks",
         "status": "PASS" if g1_exact_complete else "SOURCE_BLOCKED",
         "evidence": (
             f"exact timestamps={g1_exact}/{g1_required}; "
             f"reviewed fail-closed exclusions={g1_excluded}; exclusions do not satisfy Step 9"
         )},
        {"step": 10, "name": "Replace G5 exclusions with genuine point-in-time controls",
         "status": "PASS" if meta.get("ready_g5_model_evaluation_controls") else "SOURCE_BLOCKED",
         "evidence": f"genuine control dates={meta.get('control_dates_resolved', 0)}/72"},
        {"step": 11, "name": "Regenerate fully non-synthetic historical feature corpus",
         "status": "PASS" if meta.get("ready_for_non_synthetic_model_evaluation_metadata") and audit.get("ready_for_real_backfill") else "DEPENDENCY_BLOCKED",
         "evidence": "requires G2 real market data + G1 exact timing + genuine G5 controls"},
        {"step": 12, "name": "Run non-synthetic release gates and champion/challenger evaluation",
         "status": "PASS" if cov.get("ready_for_non_synthetic_champion_challenger_comparison") and quality.get("quality_cleared_for_non_synthetic_model_evaluation") else "DEPENDENCY_BLOCKED",
         "evidence": "release remains fail-closed until source-dependent locks are genuinely clear"},
    ]

    status = {
        "schema_version": "1",
        "purpose": "Truthful execution status for the 12-step real-data release sprint.",
        "requirements_manifest_sha256": _sha256(requirements_manifest_path),
        "coverage_summary_sha256": _sha256(coverage_summary_path),
        "metadata_readiness_sha256": _sha256(metadata_readiness_path),
        "metadata_quality_sha256": _sha256(metadata_quality_path),
        "steps": steps,
        "completed_steps": [x["step"] for x in steps if x["status"] == "PASS"],
        "source_blocked_steps": [x["step"] for x in steps if x["status"] == "SOURCE_BLOCKED"],
        "dependency_blocked_steps": [x["step"] for x in steps if x["status"] == "DEPENDENCY_BLOCKED"],
        "all_12_genuinely_complete": all(x["status"] == "PASS" for x in steps),
        "policy": {
            "synthetic_substitution_prohibited": True,
            "reviewed_exclusion_substitution_for_real_data_steps_prohibited": True,
            "future_data_or_lookahead_prohibited": True,
            "prohibited_outputs": PROHIBITED_OUTPUTS,
        },
    }
    _write_json(outpath, status)
    return status


def main() -> None:
    p = argparse.ArgumentParser(description="Freeze, refresh, and audit the 12-step real-data release sprint.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("freeze")
    a.add_argument("--source-date-requirements", type=Path, required=True)
    a.add_argument("--event-exchange-resolutions", type=Path, required=True)
    a.add_argument("--outdir", type=Path, required=True)

    b = sub.add_parser("refresh-coverage")
    b.add_argument("--coverage-summary", type=Path, required=True)
    b.add_argument("--metadata-readiness", type=Path, required=True)
    b.add_argument("--metadata-quality", type=Path, required=True)
    b.add_argument("--requirements-manifest", type=Path, required=True)
    b.add_argument("--unresolved-gates", type=Path, required=True)

    c = sub.add_parser("status")
    c.add_argument("--requirements-manifest", type=Path, required=True)
    c.add_argument("--coverage-summary", type=Path, required=True)
    c.add_argument("--metadata-readiness", type=Path, required=True)
    c.add_argument("--metadata-quality", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--require-all-real", action="store_true")

    args = p.parse_args()
    if args.cmd == "freeze":
        result = freeze_requirements(
            source_date_requirements=args.source_date_requirements,
            event_exchange_resolutions=args.event_exchange_resolutions,
            outdir=args.outdir,
        )
    elif args.cmd == "refresh-coverage":
        result = refresh_coverage(
            coverage_summary_path=args.coverage_summary,
            metadata_readiness_path=args.metadata_readiness,
            metadata_quality_path=args.metadata_quality,
            requirements_manifest_path=args.requirements_manifest,
            unresolved_gates_path=args.unresolved_gates,
        )
    else:
        result = build_status(
            requirements_manifest_path=args.requirements_manifest,
            coverage_summary_path=args.coverage_summary,
            metadata_readiness_path=args.metadata_readiness,
            metadata_quality_path=args.metadata_quality,
            outpath=args.out,
        )
        if args.require_all_real and not result["all_12_genuinely_complete"]:
            print(json.dumps(result, indent=2, sort_keys=True))
            raise SystemExit(2)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
