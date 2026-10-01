from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

STATE_MARKER = "<!-- G1_SWARM_STATE:v1 -->"
WORKER_RE = re.compile(
    r"WORKER\s+([0-4])\s*\|\s*([^|]+?)\s*\|\s*"
    r"(FOUND|EXHAUSTED(?:_FOR_NOW)?|PREPARED|CI|MERGED|BLOCKED|BUILDING)\b",
    re.IGNORECASE,
)
EVENT_RE = re.compile(r"HEJFE-[0-9A-F]+", re.IGNORECASE)
BATCH_RE = re.compile(r"\bbatch\s+0*(\d+)\b", re.IGNORECASE)
TOKEN_WORKER_RE = re.compile(r"Worker\s+([0-4])\b", re.IGNORECASE)
TOKEN_PACKAGE_RE = re.compile(
    r"Worker\s+[0-4]\s*/\s*([^/\n]+?)\s*/\s*(?:reserved\s+)?batch\s+0*\d+",
    re.IGNORECASE,
)
LEASE_HOURS_DEFAULT = 2.0


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_time(value: object) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def owner_for_event(event_id: str) -> int:
    return int(hashlib.sha256(event_id.encode("utf-8")).hexdigest(), 16) % 5


def _norm_label(value: str) -> str:
    return re.sub(r"\s+", "", value.upper())


def _symbol_tokens(label: str) -> list[str]:
    cleaned = re.sub(r"\([^)]*\)", "", label.upper())
    return [
        token
        for token in re.split(r"[^A-Z0-9.]+", cleaned)
        if token and token not in {"BATCH", "PR", "HEAD", "WORKER"}
    ]


def _comment_time(comment: dict[str, Any]) -> datetime:
    return _parse_time(comment.get("created_at") or comment.get("updated_at"))


def _base_catalog(manifest: dict[str, Any], exclusions: dict[str, Any]) -> dict[str, dict[str, Any]]:
    excluded_ids = {
        str(row.get("event_id", "")).upper()
        for row in exclusions.get("exclusions", [])
        if str(row.get("event_id", "")).strip()
    }
    catalog: dict[str, dict[str, Any]] = {}
    for item in manifest.get("items", []):
        event_id = str(item.get("event_id", "")).upper()
        if not event_id:
            continue
        resolved = (
            str(item.get("current_resolution_status", "")) == "resolved_exact_public_timestamp"
            or str(item.get("acquisition_status", "")) == "RESOLVED_NO_ACTION"
            or event_id not in excluded_ids
        )
        catalog[event_id] = {
            "event_id": event_id,
            "symbol": str(item.get("historical_symbol", "")).upper(),
            "owner": owner_for_event(event_id),
            "state": "RESOLVED" if resolved else "UNTOUCHED",
            "last_status": None,
            "last_status_at": None,
            "last_comment_id": None,
        }
    return catalog


def _unresolved_symbol_index(catalog: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for event_id, row in catalog.items():
        if row["state"] != "RESOLVED":
            out.setdefault(row["symbol"], []).append(event_id)
    return out


def _infer_event_ids(label: str, catalog: dict[str, dict[str, Any]]) -> list[str]:
    ids = [match.upper() for match in EVENT_RE.findall(label)]
    if ids:
        return sorted(set(ids))
    by_symbol = _unresolved_symbol_index(catalog)
    inferred: list[str] = []
    for symbol in _symbol_tokens(label):
        candidates = by_symbol.get(symbol, [])
        if len(candidates) == 1:
            inferred.extend(candidates)
    return sorted(set(inferred))


def _status_to_state(status: str) -> str:
    status = status.upper()
    if status == "FOUND":
        return "FOUND"
    if status == "PREPARED":
        return "PREPARED"
    if status in {"CI", "BUILDING"}:
        return "IN_FLIGHT"
    if status.startswith("EXHAUSTED"):
        return "EXHAUSTED_FOR_NOW"
    if status == "BLOCKED":
        return "PREPARED"
    return "UNTOUCHED"


def parse_worker_history(
    comments: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    packages: dict[tuple[int, str], dict[str, Any]] = {}
    for comment in sorted(comments, key=_comment_time):
        body = str(comment.get("body", ""))
        match = WORKER_RE.search(body)
        if not match:
            continue
        worker = int(match.group(1))
        label = match.group(2).strip()
        status = match.group(3).upper()
        event_ids = [x.upper() for x in EVENT_RE.findall(body)]
        if not event_ids:
            event_ids = _infer_event_ids(label, catalog)
        batch_match = BATCH_RE.search(body)
        batch = int(batch_match.group(1)) if batch_match else None
        at = _comment_time(comment)
        packages[(worker, _norm_label(label))] = {
            "worker": worker,
            "label": label,
            "status": status,
            "event_ids": sorted(set(event_ids)),
            "batch": batch,
            "at": at,
            "comment_id": comment.get("id"),
        }
        for event_id in event_ids:
            row = catalog.get(event_id)
            if row is None or row["state"] == "RESOLVED":
                continue
            row["state"] = _status_to_state(status)
            row["last_status"] = status
            row["last_status_at"] = at.isoformat()
            row["last_comment_id"] = comment.get("id")
    return catalog, list(packages.values())


def parse_token(comments: list[dict[str, Any]]) -> dict[str, Any] | None:
    token = None
    phrases = (
        "TOKEN NOW ASSIGNED",
        "TOKEN NOW ADVANCES",
        "GLOBAL INTEGRATION TOKEN NOW ADVANCES",
        "CURRENT HOLDER",
        "TOKEN ASSIGNED TO",
    )
    for comment in sorted(comments, key=_comment_time):
        body = str(comment.get("body", ""))
        upper = body.upper()
        if "TOKEN" not in upper or not any(p in upper for p in phrases):
            continue
        worker_match = TOKEN_WORKER_RE.search(body)
        if not worker_match:
            continue
        batch_match = BATCH_RE.search(body)
        package_match = TOKEN_PACKAGE_RE.search(body)
        token = {
            "worker": int(worker_match.group(1)),
            "batch": int(batch_match.group(1)) if batch_match else None,
            "label": package_match.group(1).strip() if package_match else "",
            "assigned_at": _comment_time(comment),
            "comment_id": comment.get("id"),
        }
    return token


def _package_event_ids(package: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> list[str]:
    return list(package.get("event_ids") or _infer_event_ids(str(package.get("label", "")), catalog))


def _pr_matches_token(pr: dict[str, Any], token: dict[str, Any]) -> bool:
    haystack = " ".join(str(pr.get(k, "")) for k in ("title", "body", "head", "head_ref")).upper()
    if token.get("batch") is not None and f"{int(token['batch']):04d}" in haystack:
        return True
    compact = _norm_label(haystack)
    parts = [p for p in re.split(r"[^A-Z0-9.]+", str(token.get("label", "")).upper()) if p]
    return bool(parts) and all(p in compact for p in parts)


def _latest_holder_activity(
    worker: int,
    assigned_at: datetime,
    token: dict[str, Any],
    comments: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
) -> datetime:
    latest = assigned_at
    for comment in comments:
        at = _comment_time(comment)
        if at < assigned_at:
            continue
        match = WORKER_RE.search(str(comment.get("body", "")))
        if match and int(match.group(1)) == worker and match.group(3).upper() in {
            "BUILDING",
            "CI",
            "PREPARED",
            "MERGED",
            "BLOCKED",
        }:
            latest = max(latest, at)
    for pr in pulls:
        if not _pr_matches_token(pr, token):
            continue
        updated = _parse_time(pr.get("updated_at"))
        if updated >= assigned_at:
            latest = max(latest, updated)
    return latest


def token_status(
    token: dict[str, Any] | None,
    catalog: dict[str, dict[str, Any]],
    comments: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
    now: datetime,
    lease_hours: float,
) -> dict[str, Any]:
    if token is None:
        return {"state": "UNASSIGNED", "stale": True, "reason": "no token assignment"}
    event_ids = _infer_event_ids(str(token.get("label", "")), catalog)
    if event_ids and all(catalog.get(e, {}).get("state") == "RESOLVED" for e in event_ids):
        return {**token, "event_ids": event_ids, "state": "RESOLVED", "stale": True,
                "reason": "all token events are resolved on current main"}
    for pr in pulls:
        if not _pr_matches_token(pr, token):
            continue
        if bool(pr.get("merged_at")) or bool(pr.get("merged")) or str(pr.get("state", "")).lower() == "closed":
            return {**token, "event_ids": event_ids, "state": "RESOLVED", "stale": True,
                    "reason": "matching canonical PR is merged/closed"}
    latest = _latest_holder_activity(
        int(token["worker"]), token["assigned_at"], token, comments, pulls
    )
    if now > latest + timedelta(hours=lease_hours):
        return {**token, "event_ids": event_ids, "state": "STALLED", "stale": True,
                "latest_activity_at": latest,
                "reason": f"no holder progress for more than {lease_hours:g} hours"}
    return {**token, "event_ids": event_ids, "state": "ACTIVE", "stale": False,
            "latest_activity_at": latest,
            "reason": "holder has recent progress or lease remains active"}


def choose_next_package(
    packages: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
    current_token: dict[str, Any] | None,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for package in packages:
        if package["status"] not in {"PREPARED", "CI"}:
            continue
        event_ids = _package_event_ids(package, catalog)
        if event_ids and all(catalog.get(e, {}).get("state") == "RESOLVED" for e in event_ids):
            continue
        if current_token and int(package["worker"]) == int(current_token["worker"]) and package.get("batch") == current_token.get("batch"):
            continue
        candidates.append({**package, "event_ids": event_ids, "tier": 0})
    if not candidates:
        for row in catalog.values():
            if row["state"] == "FOUND":
                candidates.append({
                    "worker": row["owner"],
                    "label": f"{row['symbol']} ({row['event_id']})",
                    "status": "FOUND",
                    "event_ids": [row["event_id"]],
                    "batch": None,
                    "at": _parse_time(row["last_status_at"]),
                    "tier": 1,
                })
    if not candidates:
        return None
    candidates.sort(key=lambda p: (
        int(p["tier"]), p["at"],
        int(p["batch"]) if p.get("batch") is not None else 10**9,
        int(p["worker"]), str(p["label"])
    ))
    return candidates[0]


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def build_report(
    manifest: dict[str, Any],
    exclusions: dict[str, Any],
    step_status: dict[str, Any],
    comments: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
    *,
    main_sha: str,
    now: datetime,
    lease_hours: float = LEASE_HOURS_DEFAULT,
) -> dict[str, Any]:
    catalog = _base_catalog(manifest, exclusions)
    catalog, packages = parse_worker_history(comments, catalog)
    token = parse_token(comments)
    status = token_status(token, catalog, comments, pulls, now, lease_hours)
    next_package = choose_next_package(packages, catalog, token)

    counts = Counter(row["state"] for row in catalog.values())
    g1_state = exclusions.get("g1_state", {})
    exact = int(g1_state.get("exact_resolved", counts.get("RESOLVED", 0)))
    required = int(g1_state.get("required", len(catalog)))
    reviewed_excluded = int(g1_state.get("reviewed_excluded", required - exact))

    token_comment = None
    if status["stale"] and next_package is not None:
        batch_text = (
            f" / reserved batch {int(next_package['batch']):04d}"
            if next_package.get("batch") is not None else ""
        )
        token_comment = (
            "EXECUTIVE TOKEN ADVANCE — automated G1 swarm controller\n"
            f"- prior token state: {status['state']} ({status['reason']})\n"
            f"- verified main: {main_sha}; G1 {exact}/{required} exact, {reviewed_excluded} fail-closed\n"
            f"- GLOBAL INTEGRATION TOKEN now advances to Worker {next_package['worker']} "
            f"/ {next_package['label']}{batch_text}\n"
            "- holder must refresh/regenerate from exact current main and pass all existing exact-head gates; "
            "this handoff waives no evidence, ownership, lane, CI, or merge rule."
        )

    summary = {
        "schema_version": "1",
        "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "main_sha": main_sha,
        "required": required,
        "exact_resolved": exact,
        "reviewed_fail_closed": reviewed_excluded,
        "event_state_counts": dict(sorted(counts.items())),
        "token": _jsonable(status),
        "next_package": (
            {
                "worker": next_package["worker"],
                "label": next_package["label"],
                "status": next_package["status"],
                "batch": next_package.get("batch"),
                "event_ids": next_package.get("event_ids", []),
            } if next_package else None
        ),
        "step9_status": next(
            (row.get("status") for row in step_status.get("steps", []) if int(row.get("step", -1)) == 9),
            None,
        ),
    }
    state_comment_body = (
        STATE_MARKER + "\n"
        + "G1 swarm controller state (machine-maintained; canonical coordination snapshot):\n"
        + json.dumps(summary, indent=2, sort_keys=True)
    )
    return {
        "summary": summary,
        "events": catalog,
        "packages": [_jsonable({**p, "event_ids": _package_event_ids(p, catalog)}) for p in packages],
        "state_comment_body": state_comment_body,
        "token_comment_body": token_comment,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic G1 swarm coordination controller.")
    parser.add_argument("--manifest", type=Path, default=Path("data/public/metadata/g1_acquisition_manifest.json"))
    parser.add_argument("--exclusions", type=Path, default=Path("data/processed/authorized_input_real/g1_final_timing_exclusions.json"))
    parser.add_argument("--step-status", type=Path, default=Path("data/processed/real_data_release_sprint/step_status.json"))
    parser.add_argument("--comments", type=Path, required=True)
    parser.add_argument("--pulls", type=Path, required=True)
    parser.add_argument("--main-sha", required=True)
    parser.add_argument("--lease-hours", type=float, default=LEASE_HOURS_DEFAULT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = build_report(
        _read_json(args.manifest),
        _read_json(args.exclusions),
        _read_json(args.step_status),
        _read_json(args.comments),
        _read_json(args.pulls),
        main_sha=args.main_sha,
        now=datetime.now(timezone.utc),
        lease_hours=args.lease_hours,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
