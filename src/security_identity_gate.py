from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


SCHEMA_VERSION = "1"
DEFAULT_EVENTS = Path("data/processed/historical_events.csv")
DEFAULT_REQUIREMENTS = Path("data/processed/coverage_plan_real/symbol_date_requirements.csv")
DEFAULT_LISTING = Path("data/public/metadata/g3_primary_listing_history.csv")
DEFAULT_OUTPUT = Path("data/processed/security_identity_real/security_identity_manifest.json")


class SecurityIdentityError(ValueError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [
            {str(k): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(f)
        ]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _event_ids(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(";") if item.strip()]


def build_manifest_from_rows(
    events: list[dict[str, str]],
    requirements: list[dict[str, str]],
    listings: list[dict[str, str]],
    *,
    source_sha256: dict[str, str] | None = None,
) -> dict:
    if not events:
        raise SecurityIdentityError("historical events are empty")
    event_by_id: dict[str, dict[str, str]] = {}
    symbol_to_permnos: dict[str, set[str]] = {}
    permno_to_symbols: dict[str, set[str]] = {}

    for i, row in enumerate(events, 2):
        event_id = row.get("event_id", "")
        symbol = row.get("historical_symbol", "").upper()
        permno = row.get("permno", "")
        gvkey = row.get("gvkey", "")
        event_date = row.get("first_documented_illicit_trade_ts", "")[:10]
        if not event_id or event_id in event_by_id:
            raise SecurityIdentityError(f"event row {i}: event_id must be unique and nonblank")
        if not symbol or not permno or not gvkey or len(event_date) != 10:
            raise SecurityIdentityError(
                f"event row {i}: historical_symbol, permno, gvkey, and event date are required"
            )
        if row.get("research_use_only") != "1":
            raise SecurityIdentityError(f"event row {i}: research_use_only must equal 1")
        event_by_id[event_id] = {
            **row,
            "historical_symbol": symbol,
            "event_date": event_date,
        }
        symbol_to_permnos.setdefault(symbol, set()).add(permno)
        permno_to_symbols.setdefault(permno, set()).add(symbol)

    symbol_collisions = {
        symbol: sorted(values)
        for symbol, values in symbol_to_permnos.items()
        if len(values) > 1
    }
    permno_aliases = {
        permno: sorted(values)
        for permno, values in permno_to_symbols.items()
        if len(values) > 1
    }
    if symbol_collisions:
        raise SecurityIdentityError(
            f"historical symbol maps to multiple PERMNOs: {symbol_collisions}"
        )
    if permno_aliases:
        raise SecurityIdentityError(
            f"PERMNO maps to multiple historical symbols without explicit dated alias evidence: {permno_aliases}"
        )

    listing_by_id: dict[str, dict[str, str]] = {}
    for i, row in enumerate(listings, 2):
        event_id = row.get("event_id", "")
        if not event_id or event_id in listing_by_id:
            raise SecurityIdentityError(f"listing row {i}: event_id must be unique and nonblank")
        event = event_by_id.get(event_id)
        if event is None:
            raise SecurityIdentityError(f"listing row {i}: unknown event_id {event_id}")
        if row.get("historical_symbol", "").upper() != event["historical_symbol"]:
            raise SecurityIdentityError(f"listing row {i}: historical_symbol mismatch for {event_id}")
        if row.get("effective_date") != event["event_date"]:
            raise SecurityIdentityError(f"listing row {i}: effective_date mismatch for {event_id}")
        if row.get("primary_exchange") not in {"XNYS", "XNAS", "XASE"}:
            raise SecurityIdentityError(f"listing row {i}: invalid primary_exchange")
        if row.get("research_use_only") != "1":
            raise SecurityIdentityError(f"listing row {i}: research_use_only must equal 1")
        listing_by_id[event_id] = row

    missing_listing = sorted(set(event_by_id) - set(listing_by_id))
    if missing_listing:
        raise SecurityIdentityError(
            f"events missing point-in-time listing evidence: {missing_listing[:10]}"
        )

    dates_by_event: dict[str, set[str]] = {event_id: set() for event_id in event_by_id}
    requirement_rows = 0
    for i, row in enumerate(requirements, 2):
        requirement_rows += 1
        symbol = row.get("historical_symbol", "").upper()
        trade_date = row.get("trade_date", "")
        ids = _event_ids(row.get("event_ids", ""))
        if not symbol or len(trade_date) != 10 or not ids:
            raise SecurityIdentityError(
                f"requirement row {i}: historical_symbol, trade_date, and event_ids are required"
            )
        if row.get("research_use_only") != "1":
            raise SecurityIdentityError(f"requirement row {i}: research_use_only must equal 1")
        permnos: set[str] = set()
        for event_id in ids:
            event = event_by_id.get(event_id)
            if event is None:
                raise SecurityIdentityError(f"requirement row {i}: unknown event_id {event_id}")
            if event["historical_symbol"] != symbol:
                raise SecurityIdentityError(
                    f"requirement row {i}: symbol {symbol} does not match event {event_id} "
                    f"symbol {event['historical_symbol']}"
                )
            if trade_date > event["event_date"]:
                raise SecurityIdentityError(
                    f"requirement row {i}: trade_date {trade_date} is after event date "
                    f"{event['event_date']} for {event_id}"
                )
            permnos.add(event["permno"])
            dates_by_event[event_id].add(trade_date)
        if len(permnos) != 1:
            raise SecurityIdentityError(
                f"requirement row {i}: one symbol/date resolves to multiple PERMNOs {sorted(permnos)}"
            )

    event_records: list[dict] = []
    verified_date_count = 0
    unverified_date_count = 0
    for event_id in sorted(event_by_id):
        event = event_by_id[event_id]
        listing = listing_by_id[event_id]
        dates = sorted(dates_by_event[event_id])
        if not dates:
            raise SecurityIdentityError(f"event {event_id}: no market-date requirements")
        if event["event_date"] not in dates:
            raise SecurityIdentityError(
                f"event {event_id}: event date {event['event_date']} is absent from requirements"
            )
        verified = [event["event_date"]]
        unverified = [value for value in dates if value != event["event_date"]]
        verified_date_count += len(verified)
        unverified_date_count += len(unverified)
        event_records.append({
            "event_id": event_id,
            "permno": event["permno"],
            "gvkey": event["gvkey"],
            "historical_symbol": event["historical_symbol"],
            "event_date": event["event_date"],
            "primary_exchange": listing["primary_exchange"],
            "required_dates": dates,
            "verified_required_dates": verified,
            "unverified_required_dates": unverified,
            "identity_status": (
                "POINT_IN_TIME_SECURITY_MASTER_REQUIRED"
                if unverified
                else "FULL_REQUIRED_DATE_IDENTITY_VERIFIED"
            ),
            "event_date_listing_evidence": {
                "evidence_kind": listing.get("evidence_kind", ""),
                "source_grade": listing.get("source_grade", ""),
                "source_reference": listing.get("source_reference", ""),
            },
            "research_use_only": True,
        })

    ready = unverified_date_count == 0
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Stable security-identity gate for historical market-data joins. "
            "PERMNO anchors event identity; ticker continuity is never inferred across dates."
        ),
        "research_use_only": True,
        "sources": {
            "historical_events": str(DEFAULT_EVENTS),
            "symbol_date_requirements": str(DEFAULT_REQUIREMENTS),
            "event_date_listing_evidence": str(DEFAULT_LISTING),
            "sha256": dict(sorted((source_sha256 or {}).items())),
        },
        "state": {
            "event_count": len(event_by_id),
            "unique_permno_count": len(permno_to_symbols),
            "unique_historical_symbol_count": len(symbol_to_permnos),
            "required_symbol_date_count": requirement_rows,
            "event_date_identity_verified_count": verified_date_count,
            "baseline_identity_unverified_count": unverified_date_count,
            "symbol_to_multiple_permno_collision_count": 0,
            "permno_to_multiple_symbol_collision_count": 0,
            "ready_for_non_synthetic_market_join": ready,
            "reasons": (
                []
                if ready
                else ["baseline_point_in_time_security_identity_not_proven"]
            ),
        },
        "completion_contract": {
            "required_evidence": (
                "A dated security-master/crosswalk must bind each event PERMNO to the "
                "historical market-data identifier and symbol on every unverified required date."
            ),
            "minimum_fields": [
                "permno_or_explicit_crosswalk_to_permno",
                "historical_symbol",
                "valid_from_or_as_of_date",
                "valid_through_or_next_change_date",
                "source_reference",
            ],
            "corporate_action_policy": (
                "Renames, mergers, share-class changes, symbol reuse, and other identifier "
                "changes require explicit dated evidence. No alias is inferred."
            ),
            "prohibited_shortcuts": [
                "current_ticker_substitution",
                "event_date_identity_extended_backward_without_evidence",
                "undated_symbol_map",
                "symbol_only_join_when_stable_identity_is_unproven",
                "inferred_corporate_action_alias",
            ],
        },
        "events": event_records,
    }


def build_manifest(
    events_path: Path = DEFAULT_EVENTS,
    requirements_path: Path = DEFAULT_REQUIREMENTS,
    listing_path: Path = DEFAULT_LISTING,
) -> dict:
    return build_manifest_from_rows(
        _read_csv(events_path),
        _read_csv(requirements_path),
        _read_csv(listing_path),
        source_sha256={
            "historical_events": _sha256(events_path),
            "symbol_date_requirements": _sha256(requirements_path),
            "event_date_listing_evidence": _sha256(listing_path),
        },
    )


def render_manifest(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the fail-closed historical security-identity manifest."
    )
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--listing", type=Path, default=DEFAULT_LISTING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    rendered = render_manifest(
        build_manifest(args.events, args.requirements, args.listing)
    )
    if args.check:
        return 0 if args.output.exists() and args.output.read_text(encoding="utf-8") == rendered else 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
