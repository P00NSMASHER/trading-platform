from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path


SCHEMA_VERSION = "1"
DEFAULT_IDENTITY = Path("data/processed/security_identity_real/security_identity_manifest.json")
DEFAULT_QUEUE = Path("data/processed/security_identity_real/security_identity_acquisition_queue.csv")
DEFAULT_SUMMARY = Path("data/processed/security_identity_real/security_identity_acquisition_summary.json")

QUEUE_FIELDS = [
    "request_id",
    "permno",
    "gvkey",
    "historical_symbol",
    "trade_date",
    "event_ids",
    "status",
    "required_evidence",
    "primary_lane",
    "secondary_lane",
    "corroboration_lane",
    "research_use_only",
]

ACQUISITION_LANES = {
    "LICENSED_STABLE_ID_MASTER": {
        "role": "PRIMARY",
        "requirement": (
            "Use lawfully licensed point-in-time security-master data that directly binds "
            "PERMNO (or an explicit stable identifier crosswalk to PERMNO) to the historical "
            "market identifier/symbol for the requested date."
        ),
        "examples": [
            "CRSP/WRDS security-name or security-master history",
            "equivalent licensed stable-ID security master",
        ],
        "can_close_request": True,
    },
    "AUTHORIZED_MARKET_SECURITY_MASTER": {
        "role": "SECONDARY",
        "requirement": (
            "Use an authorized historical market-data symbol/security master only when it "
            "includes or is joined through an explicit dated bridge to PERMNO for the "
            "requested date."
        ),
        "examples": [
            "authorized TAQ/market-data symbol master plus dated PERMNO bridge",
            "exchange/vendor security master with explicit stable-ID crosswalk",
        ],
        "can_close_request": True,
    },
    "PUBLIC_CORPORATE_ACTION_CORROBORATION": {
        "role": "CORROBORATION_ONLY",
        "requirement": (
            "Use issuer, SEC, or exchange notices to corroborate renames, mergers, "
            "share-class changes, symbol changes, or other corporate actions. Public "
            "corroboration alone cannot close a request unless it explicitly establishes "
            "the stable-ID binding."
        ),
        "examples": [
            "SEC filings/exhibits",
            "issuer corporate-action notices",
            "exchange symbol-change notices",
        ],
        "can_close_request": False,
    },
}


class IdentityAcquisitionError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _request_id(permno: str, trade_date: str) -> str:
    digest = hashlib.sha256(f"{permno}|{trade_date}".encode("utf-8")).hexdigest()
    return "SID-" + digest[:16].upper()


def load_identity(path: Path = DEFAULT_IDENTITY) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1":
        raise IdentityAcquisitionError("identity manifest schema_version must equal '1'")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise IdentityAcquisitionError("identity manifest events are empty")
    return payload


def build_acquisition(identity: dict, *, identity_sha256: str | None = None) -> tuple[list[dict[str, str]], dict]:
    events = identity.get("events") or []
    state = identity.get("state") or {}
    request_map: dict[tuple[str, str], dict] = {}
    security_map: dict[str, dict] = {}
    raw_instances = 0

    for i, event in enumerate(events, 1):
        event_id = str(event.get("event_id") or "")
        permno = str(event.get("permno") or "")
        gvkey = str(event.get("gvkey") or "")
        symbol = str(event.get("historical_symbol") or "").upper()
        unverified = list(event.get("unverified_required_dates") or [])
        if not event_id or not permno or not gvkey or not symbol:
            raise IdentityAcquisitionError(f"event {i}: identity fields are incomplete")

        sec = None
        if unverified:
            sec = security_map.setdefault(
                permno,
                {
                    "permno": permno,
                    "gvkey": gvkey,
                    "historical_symbol": symbol,
                    "dates": set(),
                    "event_ids": set(),
                },
            )
            if sec["gvkey"] != gvkey or sec["historical_symbol"] != symbol:
                raise IdentityAcquisitionError(
                    f"PERMNO {permno} maps to conflicting GVKEY/symbol values in the identity manifest"
                )

        for trade_date in unverified:
            raw_instances += 1
            if not isinstance(trade_date, str) or len(trade_date) != 10:
                raise IdentityAcquisitionError(f"event {event_id}: invalid unverified trade date")
            assert sec is not None
            sec["dates"].add(trade_date)
            sec["event_ids"].add(event_id)

            key = (permno, trade_date)
            row = request_map.get(key)
            if row is None:
                row = {
                    "request_id": _request_id(permno, trade_date),
                    "permno": permno,
                    "gvkey": gvkey,
                    "historical_symbol": symbol,
                    "trade_date": trade_date,
                    "event_ids": set(),
                    "status": "PENDING_STABLE_ID_EVIDENCE",
                    "required_evidence": "DATED_STABLE_ID_CROSSWALK",
                    "primary_lane": "LICENSED_STABLE_ID_MASTER",
                    "secondary_lane": "AUTHORIZED_MARKET_SECURITY_MASTER",
                    "corroboration_lane": "PUBLIC_CORPORATE_ACTION_CORROBORATION",
                    "research_use_only": "1",
                }
                request_map[key] = row
            elif row["gvkey"] != gvkey or row["historical_symbol"] != symbol:
                raise IdentityAcquisitionError(
                    f"request {permno}/{trade_date} resolves to conflicting security identity"
                )
            row["event_ids"].add(event_id)

    expected = int(state.get("baseline_identity_unverified_count", -1))
    if expected != raw_instances:
        raise IdentityAcquisitionError(
            f"identity manifest unverified count mismatch: state={expected} computed={raw_instances}"
        )

    queue: list[dict[str, str]] = []
    for key in sorted(request_map):
        row = dict(request_map[key])
        row["event_ids"] = ";".join(sorted(row["event_ids"]))
        queue.append(row)

    securities = []
    for permno in sorted(security_map):
        sec = security_map[permno]
        dates = sorted(sec["dates"])
        securities.append({
            "permno": permno,
            "gvkey": sec["gvkey"],
            "historical_symbol": sec["historical_symbol"],
            "request_count": len(dates),
            "first_required_date": dates[0],
            "last_required_date": dates[-1],
            "event_count": len(sec["event_ids"]),
            "event_ids": sorted(sec["event_ids"]),
        })

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Acquisition plan for unresolved point-in-time security identities required "
            "before non-synthetic historical market joins can unlock."
        ),
        "research_use_only": True,
        "source_identity_manifest": str(DEFAULT_IDENTITY),
        "source_identity_manifest_sha256": identity_sha256,
        "state": {
            "raw_unverified_event_date_instances": raw_instances,
            "unique_permno_date_requests": len(queue),
            "duplicate_request_instances_removed": raw_instances - len(queue),
            "unique_permno_count": len(securities),
            "ready_for_non_synthetic_market_join": len(queue) == 0,
            "reasons": (
                []
                if len(queue) == 0
                else ["stable_id_acquisition_queue_unresolved"]
            ),
        },
        "acquisition_lanes": ACQUISITION_LANES,
        "completion_contract": {
            "close_each_request_only_if": [
                "requested trade_date is covered by the evidence",
                "evidence binds the requested PERMNO or an explicit stable identifier crosswalk to that PERMNO",
                "historical symbol/market identifier is explicit for that date",
                "source reference and validity/as-of dates are retained",
                "corporate-action aliases are explicit rather than inferred",
            ],
            "prohibited_shortcuts": [
                "current_ticker_substitution",
                "undated_symbol_map",
                "symbol_only_join_without_stable_id",
                "backward_extension_from_event_date_without_evidence",
                "inferred_rename_or_merger_alias",
            ],
        },
        "securities": securities,
    }
    return queue, summary


def render_queue(queue: list[dict[str, str]]) -> str:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=QUEUE_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(queue)
    return out.getvalue()


def render_summary(summary: dict) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"


def build_from_path(identity_path: Path = DEFAULT_IDENTITY) -> tuple[str, str]:
    identity = load_identity(identity_path)
    queue, summary = build_acquisition(
        identity,
        identity_sha256=_sha256_path(identity_path),
    )
    return render_queue(queue), render_summary(summary)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the stable-ID acquisition queue.")
    parser.add_argument("--identity", type=Path, default=DEFAULT_IDENTITY)
    parser.add_argument("--queue-output", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    queue_text, summary_text = build_from_path(args.identity)
    if args.check:
        ok = (
            args.queue_output.exists()
            and args.summary_output.exists()
            and args.queue_output.read_text(encoding="utf-8") == queue_text
            and args.summary_output.read_text(encoding="utf-8") == summary_text
        )
        return 0 if ok else 2

    args.queue_output.parent.mkdir(parents=True, exist_ok=True)
    args.queue_output.write_text(queue_text, encoding="utf-8")
    args.summary_output.write_text(summary_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
