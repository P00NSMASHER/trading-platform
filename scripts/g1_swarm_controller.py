from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "data/public/metadata/g1_swarm_controller_policy.json"

EVENT_ID_RE = re.compile(r"\bHEJFE-[0-9A-F]{16}\b")
BATCH_RE = re.compile(r"\bbatch(?:[- _:#]+)?0*(\d{2,4})\b", re.IGNORECASE)
WORKER_UPDATE_RE = re.compile(
    r"^\s*WORKER\s+([0-4])\s*\|\s*([^|]+?)\s*\|\s*([A-Z_]+)\s*\|\s*([^|\n]*)",
    re.MULTILINE,
)
PREP_BRANCH_RE = re.compile(
    r"^g1/prep-(?:batch-)?(?P<batch>\d{4})-worker-(?P<worker>[0-4])-(?P<label>.+)$",
    re.IGNORECASE,
)
HEX_SUFFIX_RE = re.compile(r"^(?P<label>.+)-(?P<sha>[0-9a-f]{7,40})(?:-v\d+)?$", re.IGNORECASE)

TOKEN_PATTERNS = [
    re.compile(
        r"GLOBAL\s+INTEGRATION\s+TOKEN\s+(?:is\s+)?(?:corrected(?:\s+back)?|restored)\s+to\s+"
        r"Worker\s+([0-4])\s*/\s*([^\n]+?)\s*/\s*(?:reserved\s+)?batch\s+0*(\d{2,4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"GLOBAL\s+INTEGRATION\s+TOKEN.*?(?:now\s+)?(?:advances|assigned)\s+to\s+"
        r"Worker\s+([0-4])\s*/\s*([^\n]+?)\s*/\s*(?:reserved\s+)?batch\s+0*(\d{2,4})",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"Token\s+now\s+assigned\s+to\s+Worker\s+([0-4])\s*/\s*([^\n]+?)\s*/\s*"
        r"(?:reserved\s+)?batch\s+0*(\d{2,4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"Current\s+token:\s*Worker\s+([0-4])\s*/\s*([^\n]+?)\s*/\s*"
        r"(?:reserved\s+)?batch\s+0*(\d{2,4})",
        re.IGNORECASE,
    ),
]
TOKEN_HOLDER_PATTERN = re.compile(
    r"Current\s+holder:.*?Worker\s+([0-4])\s*/\s*batch\s+0*(\d{2,4})\s*/\s*([^\n.]+)",
    re.IGNORECASE,
)
TOKEN_UNASSIGNED_RE = re.compile(
    r"GLOBAL\s+INTEGRATION\s+TOKEN.*?\bUNASSIGNED\b", re.IGNORECASE | re.DOTALL
)

QUEUE_HINT_PATTERNS = [
    re.compile(
        r"Worker\s+([0-4])\s*/\s*([^\n]+?)\s*/\s*(?:reserved\s+)?batch\s+0*(\d{2,4})"
        r"(?:\s+remains\s+next\s+prepared\s+candidate)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"Worker\s+([0-4])\s*/\s*(?:reserved\s+)?batch\s+0*(\d{2,4})\s*/\s*([^\n.]+)",
        re.IGNORECASE,
    ),
]

MEANINGFUL_PROGRESS = {"BUILDING", "CI", "PREPARED", "MERGED"}
PREPARED_STATUSES = {"PREPARED", "CI"}
TERMINAL_STATUSES = {"MERGED", "EXHAUSTED", "EXHAUSTED_FOR_NOW"}


@dataclass(frozen=True)
class TokenAssignment:
    worker: int | None
    package: str
    batch: int | None
    assigned_at: str
    comment_id: int | None


@dataclass(frozen=True)
class WorkerUpdate:
    worker: int
    label: str
    status: str
    batch: int | None
    event_ids: tuple[str, ...]
    symbols: tuple[str, ...]
    created_at: str
    comment_id: int | None
    body: str


@dataclass(frozen=True)
class Candidate:
    worker: int
    package: str
    batch: int
    event_ids: tuple[str, ...]
    symbols: tuple[str, ...]
    created_at: str
    source: str
    status: str
    branch: str | None = None
    behind_by: int | None = None
    ahead_by: int | None = None


@dataclass(frozen=True)
class TokenEvaluation:
    state: str
    reason: str
    age_minutes: float | None
    progress_after_assignment: bool
    matching_open_pr: int | None
    matching_closed_pr: int | None


def load_policy(root: Path = ROOT) -> dict[str, Any]:
    return json.loads((root / POLICY_PATH.relative_to(ROOT)).read_text(encoding="utf-8"))


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalized_package(label: str) -> str:
    label = re.sub(r"\s+", " ", label.strip())
    label = label.strip(" .:-")
    return label


def symbols_from_label(label: str) -> tuple[str, ...]:
    symbols: list[str] = []
    for symbol in re.findall(r"/([A-Za-z][A-Za-z0-9.-]{0,11})\b", label):
        symbols.append(symbol.upper())
    if not symbols and not EVENT_ID_RE.search(label):
        for piece in re.split(r"\s*\+\s*|\s*,\s*", label):
            piece = piece.strip().upper()
            if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,11}", piece):
                symbols.append(piece)
    return tuple(dict.fromkeys(symbols))


def parse_worker_updates(comments: Iterable[dict[str, Any]]) -> list[WorkerUpdate]:
    rows: list[WorkerUpdate] = []
    for comment in comments:
        body = str(comment.get("body") or "")
        created_at = str(comment.get("created_at") or "")
        for match in WORKER_UPDATE_RE.finditer(body):
            worker = int(match.group(1))
            label = normalized_package(match.group(2))
            status = match.group(3).upper()
            batch_match = BATCH_RE.search(body)
            batch = int(batch_match.group(1)) if batch_match else None
            event_ids = tuple(dict.fromkeys(EVENT_ID_RE.findall(label)))
            symbols = symbols_from_label(label)
            rows.append(
                WorkerUpdate(
                    worker=worker,
                    label=label,
                    status=status,
                    batch=batch,
                    event_ids=event_ids,
                    symbols=symbols,
                    created_at=created_at,
                    comment_id=comment.get("id"),
                    body=body,
                )
            )
    return rows


def parse_latest_token(comments: Iterable[dict[str, Any]]) -> TokenAssignment | None:
    latest: TokenAssignment | None = None
    latest_key: tuple[datetime, int] | None = None
    for comment in comments:
        body = str(comment.get("body") or "")
        created = parse_time(str(comment.get("created_at") or "")) or datetime.min.replace(tzinfo=timezone.utc)
        cid = int(comment.get("id") or 0)
        assignment: TokenAssignment | None = None

        if TOKEN_UNASSIGNED_RE.search(body):
            assignment = TokenAssignment(
                worker=None,
                package="UNASSIGNED",
                batch=None,
                assigned_at=str(comment.get("created_at") or ""),
                comment_id=comment.get("id"),
            )
        else:
            for pattern in TOKEN_PATTERNS:
                match = pattern.search(body)
                if match:
                    assignment = TokenAssignment(
                        worker=int(match.group(1)),
                        package=normalized_package(match.group(2)),
                        batch=int(match.group(3)),
                        assigned_at=str(comment.get("created_at") or ""),
                        comment_id=comment.get("id"),
                    )
                    break
            if assignment is None:
                match = TOKEN_HOLDER_PATTERN.search(body)
                if match:
                    assignment = TokenAssignment(
                        worker=int(match.group(1)),
                        package=normalized_package(match.group(3)),
                        batch=int(match.group(2)),
                        assigned_at=str(comment.get("created_at") or ""),
                        comment_id=comment.get("id"),
                    )

        if assignment is not None and (latest_key is None or (created, cid) > latest_key):
            latest = assignment
            latest_key = (created, cid)
    return latest


def parse_queue_hints(comments: Iterable[dict[str, Any]]) -> list[Candidate]:
    candidates: list[Candidate] = []
    for comment in comments:
        body = str(comment.get("body") or "")
        created_at = str(comment.get("created_at") or "")
        for i, pattern in enumerate(QUEUE_HINT_PATTERNS):
            for match in pattern.finditer(body):
                if i == 0:
                    worker = int(match.group(1))
                    package = normalized_package(match.group(2))
                    batch = int(match.group(3))
                else:
                    worker = int(match.group(1))
                    batch = int(match.group(2))
                    package = normalized_package(match.group(3))
                # Only treat explicit queue/prepared language as a queue hint.
                window = body[max(0, match.start() - 120): min(len(body), match.end() + 180)].lower()
                if not any(word in window for word in ("queue", "prepared", "next", "after", "candidate")):
                    continue
                candidates.append(
                    Candidate(
                        worker=worker,
                        package=package,
                        batch=batch,
                        event_ids=tuple(EVENT_ID_RE.findall(window.upper())),
                        symbols=symbols_from_label(package),
                        created_at=created_at,
                        source="queue_hint",
                        status="PREPARED",
                    )
                )
    return candidates


def lane_valid(worker: int, batch: int, policy: dict[str, Any]) -> bool:
    lane = policy["batch_lanes"][str(worker)]
    start = int(lane["start"])
    step = int(lane["step"])
    return batch >= start and (batch - start) % step == 0


def manifest_state(root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    path = root / policy["canonical_inputs"]["acquisition_manifest"]
    data = json.loads(path.read_text(encoding="utf-8"))
    items = list(data.get("items") or [])
    resolved_ids = {
        str(item["event_id"])
        for item in items
        if item.get("current_resolution_status") == "resolved_exact_public_timestamp"
    }
    unresolved_ids = {str(item["event_id"]) for item in items} - resolved_ids
    unresolved_by_symbol: dict[str, set[str]] = {}
    for item in items:
        event_id = str(item["event_id"])
        if event_id not in unresolved_ids:
            continue
        symbol = str(item.get("historical_symbol") or "").upper()
        unresolved_by_symbol.setdefault(symbol, set()).add(event_id)
    return {
        "total": len(items),
        "exact": len(resolved_ids),
        "unresolved": len(unresolved_ids),
        "resolved_ids": resolved_ids,
        "unresolved_ids": unresolved_ids,
        "unresolved_by_symbol": unresolved_by_symbol,
    }


def candidate_is_resolved(candidate: Candidate, manifest: dict[str, Any], pulls: list[dict[str, Any]], updates: list[WorkerUpdate]) -> bool:
    if batch_merged(candidate.batch, pulls, updates):
        return True
    if candidate.event_ids and all(eid in manifest["resolved_ids"] for eid in candidate.event_ids):
        return True
    if candidate.symbols and all(not manifest["unresolved_by_symbol"].get(symbol) for symbol in candidate.symbols):
        return True
    return False


def package_words(package: str) -> tuple[str, ...]:
    words = []
    for token in re.split(r"[^A-Za-z0-9]+", package.upper()):
        if len(token) >= 2 and token not in {"HEJFE", "BATCH", "WORKER"}:
            words.append(token)
    return tuple(dict.fromkeys(words))


def pr_matches(worker: int | None, package: str, batch: int | None, pr: dict[str, Any]) -> bool:
    text = " ".join(
        str(x or "")
        for x in (
            pr.get("title"),
            pr.get("body"),
            (pr.get("head") or {}).get("ref"),
        )
    )
    upper = text.upper()
    if batch is not None and re.search(
        rf"\bBATCH(?:[- _:#]+)?0*{batch}\b",
        upper,
        re.IGNORECASE,
    ):
        # A batch hit alone is insufficient when worker identity is known.
        # This prevents an unrelated PR mentioning the same number from being
        # treated as the token holder's integration PR.
        if worker is None:
            return True
        return bool(re.search(rf"\bWORKER[- _]*{worker}\b", upper))
    words = package_words(package)
    if words and all(re.search(rf"\b{re.escape(word)}\b", upper) for word in words):
        if worker is None:
            return True
        worker_match = re.search(rf"\bWORKER[- _]*{worker}\b", upper)
        return bool(worker_match or len(words) >= 2)
    return False


def update_matches_token(update: WorkerUpdate, token: TokenAssignment) -> bool:
    if token.worker is None or update.worker != token.worker:
        return False
    token_words = set(package_words(token.package))
    update_words = set(package_words(update.label))
    if token.batch is not None and update.batch == token.batch:
        # Same batch is necessary but not sufficient: require compatible package
        # identity whenever both sides provide one.
        return not token_words or not update_words or token_words == update_words
    # Package fallback matching must be exact enough to prevent an update for one
    # symbol in a multi-event package from extending the whole package's lease.
    return bool(token_words and update_words and token_words == update_words)


def batch_merged(batch: int, pulls: list[dict[str, Any]], updates: list[WorkerUpdate]) -> bool:
    for update in updates:
        if update.batch == batch and update.status == "MERGED":
            return True
    for pr in pulls:
        if pr_matches(None, "", batch, pr) and pr.get("merged_at"):
            return True
    return False


def evaluate_token(
    token: TokenAssignment | None,
    *,
    comments: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
    updates: list[WorkerUpdate],
    manifest: dict[str, Any],
    lease_minutes: int,
    now: datetime,
    candidates: list[Candidate] | None = None,
) -> TokenEvaluation:
    if token is None or token.worker is None or token.batch is None:
        return TokenEvaluation("UNASSIGNED", "no active token assignment", None, False, None, None)

    assigned_at = parse_time(token.assigned_at)
    age_minutes = None if assigned_at is None else max(0.0, (now - assigned_at).total_seconds() / 60.0)

    matching_open: int | None = None
    matching_open_fresh = False
    matching_closed: int | None = None
    matching_merged: int | None = None
    for pr in pulls:
        if not pr_matches(token.worker, token.package, token.batch, pr):
            continue
        number = int(pr.get("number") or 0) or None
        if pr.get("merged_at") or pr.get("merged") is True:
            matching_merged = number
        elif str(pr.get("state") or "").lower() == "open":
            matching_open = number
            # An open PR is material progress only while it still targets the
            # exact current-main snapshot represented by this controller run.
            # Callers normalize base.sha when reading live PRs.
            base_sha = str((pr.get("base") or {}).get("sha") or pr.get("base_sha") or "")
            matching_open_fresh = bool(base_sha and base_sha == manifest.get("main_sha"))
        else:
            # A closed-unmerged PR should release a token only when that PR was
            # built from the controller's exact current-main snapshot. Stale
            # closed PRs from earlier main SHAs are historical evidence and must
            # not immediately invalidate a freshly reassigned package.
            base_sha = str((pr.get("base") or {}).get("sha") or pr.get("base_sha") or "")
            if base_sha and base_sha == manifest.get("main_sha"):
                matching_closed = number

    token_candidate = Candidate(
        worker=token.worker,
        package=token.package,
        batch=token.batch,
        event_ids=tuple(),
        symbols=symbols_from_label(token.package),
        created_at=token.assigned_at,
        source="token",
        status="IN_FLIGHT",
    )
    if matching_merged is not None or candidate_is_resolved(token_candidate, manifest, pulls, updates):
        return TokenEvaluation(
            "RESOLVED",
            "token package merged or package no longer unresolved",
            age_minutes,
            True,
            matching_open,
            matching_merged,
        )
    if matching_closed is not None:
        return TokenEvaluation(
            "CLOSED_UNMERGED",
            "matching token PR closed without merge; release token but keep package eligible for later repair",
            age_minutes,
            True,
            matching_open,
            matching_closed,
        )

    if candidates is not None:
        live_support = matching_open is not None and matching_open_fresh
        if not live_support:
            for candidate in candidates:
                # A matching prep branch keeps an existing token alive within its
                # bounded lease even if unrelated main movement made the branch stale.
                # The holder must still regenerate from exact current main before
                # canonical PR/merge; stale branches cannot receive new assignments.
                if candidate.source != "prep_branch_fallback":
                    continue
                if candidate.behind_by is None or (candidate.ahead_by or 0) < 1:
                    continue
                if candidate.worker != token.worker or candidate.batch != token.batch:
                    continue
                if not candidate_is_resolved(candidate, manifest, pulls, updates):
                    live_support = True
                    break
        if not live_support:
            for update in updates:
                if update.status not in {"FOUND", "BUILDING", "CI"}:
                    continue
                if update_matches_token(update, token) and not update_is_resolved(update, manifest):
                    live_support = True
                    break
        if not live_support:
            return TokenEvaluation(
                "INVALID",
                "token assignment lacks live same-worker FOUND/PREPARED/CI, prep branch, or open PR support",
                age_minutes,
                False,
                matching_open,
                matching_closed,
            )

    progress_after = matching_open is not None and matching_open_fresh
    if assigned_at is not None:
        for update in updates:
            update_time = parse_time(update.created_at)
            if update_time is None or update_time <= assigned_at:
                continue
            if update.status in MEANINGFUL_PROGRESS and update_matches_token(update, token):
                progress_after = True
                break

    if age_minutes is not None and age_minutes > lease_minutes and not progress_after:
        return TokenEvaluation(
            "STALLED",
            f"token lease exceeded {lease_minutes} minutes without BUILDING/CI/PR evidence",
            age_minutes,
            False,
            matching_open,
            matching_closed,
        )
    return TokenEvaluation(
        "ACTIVE",
        "token holder still within lease or has material progress",
        age_minutes,
        progress_after,
        matching_open,
        matching_closed,
    )


def latest_updates_by_batch(updates: list[WorkerUpdate]) -> dict[tuple[int, int], WorkerUpdate]:
    result: dict[tuple[int, int], WorkerUpdate] = {}
    for update in updates:
        if update.batch is None:
            continue
        key = (update.worker, update.batch)
        previous = result.get(key)
        if previous is None:
            result[key] = update
            continue
        ptime = parse_time(previous.created_at) or datetime.min.replace(tzinfo=timezone.utc)
        utime = parse_time(update.created_at) or datetime.min.replace(tzinfo=timezone.utc)
        if (utime, update.comment_id or 0) >= (ptime, previous.comment_id or 0):
            result[key] = update
    return result


def collect_issue_candidates(comments: list[dict[str, Any]], updates: list[WorkerUpdate]) -> list[Candidate]:
    candidates = parse_queue_hints(comments)
    for update in latest_updates_by_batch(updates).values():
        if update.status not in PREPARED_STATUSES:
            continue
        candidates.append(
            Candidate(
                worker=update.worker,
                package=update.label,
                batch=int(update.batch),
                event_ids=update.event_ids,
                symbols=update.symbols,
                created_at=update.created_at,
                source="issue_prepared",
                status=update.status,
            )
        )
    return candidates


def parse_prep_branch(branch: str) -> tuple[int, int, str] | None:
    match = PREP_BRANCH_RE.match(branch)
    if not match:
        return None
    worker = int(match.group("worker"))
    batch = int(match.group("batch"))
    label = match.group("label")
    suffix = HEX_SUFFIX_RE.match(label)
    if suffix:
        label = suffix.group("label")
    package = "+".join(piece.upper() for piece in label.split("-") if piece)
    return worker, batch, package


def branch_candidates(
    refs: list[dict[str, Any]],
    compares: dict[str, dict[str, Any]],
) -> list[Candidate]:
    rows: list[Candidate] = []
    for ref in refs:
        name = str(ref.get("ref") or "").removeprefix("refs/heads/")
        parsed = parse_prep_branch(name)
        if parsed is None:
            continue
        worker, batch, package = parsed
        compare = compares.get(name) or {}
        behind = compare.get("behind_by")
        ahead = compare.get("ahead_by")
        if ahead is None or int(ahead) < 1:
            continue
        # Keep diverged prep branches visible so an already-assigned token can
        # retain its bounded lease while the holder regenerates from current main.
        # Unknown compare state is not durable support. Freshness is still required
        # by require_live_prepared_support() before a package can receive a new token.
        if behind is None:
            continue
        rows.append(
            Candidate(
                worker=worker,
                package=package,
                batch=batch,
                event_ids=tuple(EVENT_ID_RE.findall(package)),
                symbols=symbols_from_label(package.replace("-", "+")),
                created_at="",
                source="prep_branch_fallback",
                status="PREPARED",
                branch=name,
                behind_by=None if behind is None else int(behind),
                ahead_by=None if ahead is None else int(ahead),
            )
        )
    return rows


def candidate_key(candidate: Candidate) -> tuple[int, int]:
    return candidate.worker, candidate.batch


def require_live_prepared_support(candidates: list[Candidate]) -> list[Candidate]:
    # A PREPARED comment or queue hint is not durable evidence. The package must
    # have a prep branch compared against *current* main with behind_by == 0.
    # branch_candidates() already rejects stale/diverged prep branches.
    live_branch_keys = {
        candidate_key(candidate)
        for candidate in candidates
        if candidate.source == "prep_branch_fallback"
        and candidate.behind_by == 0
        and (candidate.ahead_by or 0) >= 1
    }
    return [
        candidate
        for candidate in candidates
        if candidate_key(candidate) in live_branch_keys
    ]


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    priority = {"issue_prepared": 0, "prep_branch_fallback": 1, "queue_hint": 2, "found": 3}
    best: dict[tuple[int, int], Candidate] = {}
    for candidate in candidates:
        key = candidate_key(candidate)
        current = best.get(key)
        if current is None or priority.get(candidate.source, 9) < priority.get(current.source, 9):
            best[key] = candidate
    return list(best.values())


def choose_prepared_candidate(
    candidates: list[Candidate],
    *,
    token: TokenAssignment | None,
    manifest: dict[str, Any],
    pulls: list[dict[str, Any]],
    updates: list[WorkerUpdate],
    policy: dict[str, Any],
) -> Candidate | None:
    eligible: list[Candidate] = []
    for candidate in dedupe_candidates(require_live_prepared_support(candidates)):
        if token and token.worker == candidate.worker and token.batch == candidate.batch:
            continue
        if not lane_valid(candidate.worker, candidate.batch, policy):
            continue
        if candidate_is_resolved(candidate, manifest, pulls, updates):
            continue
        eligible.append(candidate)

    source_priority = {"prep_branch_fallback": 0, "issue_prepared": 1, "queue_hint": 2}
    eligible.sort(
        key=lambda c: (
            source_priority.get(c.source, 9),
            parse_time(c.created_at) or datetime.max.replace(tzinfo=timezone.utc),
            c.batch,
            c.worker,
        )
    )
    return eligible[0] if eligible else None


def update_is_resolved(update: WorkerUpdate, manifest: dict[str, Any]) -> bool:
    if update.event_ids and all(eid in manifest["resolved_ids"] for eid in update.event_ids):
        return True
    if update.symbols and all(not manifest["unresolved_by_symbol"].get(s) for s in update.symbols):
        return True
    return False


def used_batches(
    updates: list[WorkerUpdate],
    hints: list[Candidate],
    branches: list[Candidate],
    pulls: list[dict[str, Any]],
) -> dict[int, set[int]]:
    used = {worker: set() for worker in range(5)}
    for update in updates:
        if update.batch is not None:
            used[update.worker].add(update.batch)
    for candidate in hints + branches:
        used[candidate.worker].add(candidate.batch)
    for pr in pulls:
        text = " ".join(str(x or "") for x in (pr.get("title"), pr.get("body"), (pr.get("head") or {}).get("ref")))
        worker_match = re.search(r"\bworker[- _]*([0-4])\b", text, re.IGNORECASE)
        batches = [int(x) for x in BATCH_RE.findall(text)]
        for batch in batches:
            if worker_match:
                used[int(worker_match.group(1))].add(batch)
            else:
                for worker in range(5):
                    if batch >= 60 and batch % 5 == worker:
                        used[worker].add(batch)
    return used


def next_unused_batch(worker: int, used: dict[int, set[int]], policy: dict[str, Any]) -> int:
    lane = policy["batch_lanes"][str(worker)]
    batch = int(lane["start"])
    step = int(lane["step"])
    while batch in used[worker]:
        batch += step
    return batch


def latest_updates_by_identity(updates: list[WorkerUpdate]) -> dict[tuple[int, tuple[str, ...], str], WorkerUpdate]:
    latest: dict[tuple[int, tuple[str, ...], str], WorkerUpdate] = {}
    for update in updates:
        identity = (update.worker, update.event_ids, update.label.upper())
        previous = latest.get(identity)
        if previous is None:
            latest[identity] = update
            continue
        ptime = parse_time(previous.created_at) or datetime.min.replace(tzinfo=timezone.utc)
        utime = parse_time(update.created_at) or datetime.min.replace(tzinfo=timezone.utc)
        if (utime, update.comment_id or 0) >= (ptime, previous.comment_id or 0):
            latest[identity] = update
    return latest


def choose_found_candidate(
    updates: list[WorkerUpdate],
    *,
    manifest: dict[str, Any],
    used: dict[int, set[int]],
    policy: dict[str, Any],
) -> Candidate | None:
    found: list[WorkerUpdate] = [
        update
        for update in latest_updates_by_identity(updates).values()
        if update.status == "FOUND" and not update_is_resolved(update, manifest)
    ]
    found.sort(key=lambda u: parse_time(u.created_at) or datetime.max.replace(tzinfo=timezone.utc))
    if not found:
        return None
    update = found[0]
    return Candidate(
        worker=update.worker,
        package=update.label,
        batch=next_unused_batch(update.worker, used, policy),
        event_ids=update.event_ids,
        symbols=update.symbols,
        created_at=update.created_at,
        source="found",
        status="FOUND",
    )


def github_api(
    repo: str,
    token: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> Any:
    url = f"https://api.github.com/repos/{repo}{path}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "g1-swarm-controller",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {exc.code} {method} {path}: {detail[:500]}") from exc


def paginated(repo: str, token: str, path: str, *, max_pages: int = 10) -> list[dict[str, Any]]:
    sep = "&" if "?" in path else "?"
    rows: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        chunk = github_api(repo, token, f"{path}{sep}per_page=100&page={page}")
        if not isinstance(chunk, list):
            raise RuntimeError(f"expected list from paginated endpoint: {path}")
        rows.extend(chunk)
        if len(chunk) < 100:
            break
    return rows


def fetch_branch_fallbacks(repo: str, token: str, main_sha: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    try:
        refs = github_api(repo, token, "/git/matching-refs/heads/g1/prep-")
    except RuntimeError:
        return [], {}
    if not isinstance(refs, list):
        return [], {}

    compares: dict[str, dict[str, Any]] = {}
    # Do not cap prep-branch discovery: workers may legitimately accumulate
    # more than 30 disposable prep branches between cleanup cycles.
    for ref in refs:
        branch = str(ref.get("ref") or "").removeprefix("refs/heads/")
        parsed = parse_prep_branch(branch)
        if parsed is None:
            continue
        head_sha = str((ref.get("object") or {}).get("sha") or "")
        if not head_sha:
            continue
        base = urllib.parse.quote(main_sha, safe="")
        head = urllib.parse.quote(head_sha, safe="")
        try:
            compares[branch] = github_api(repo, token, f"/compare/{base}...{head}")
        except RuntimeError:
            compares[branch] = {}
    return refs, compares


def find_state_comment(comments: list[dict[str, Any]], marker: str) -> dict[str, Any] | None:
    for comment in reversed(comments):
        if marker in str(comment.get("body") or ""):
            return comment
    return None


def render_state_comment(
    *,
    policy: dict[str, Any],
    main_sha: str,
    manifest: dict[str, Any],
    token: TokenAssignment | None,
    evaluation: TokenEvaluation,
    prepared: list[Candidate],
    found: list[WorkerUpdate],
    controller_sha: str,
) -> str:
    marker = policy["state_comment_marker"]
    token_text = "UNASSIGNED"
    if token and token.worker is not None:
        token_text = f"Worker {token.worker} / {token.package} / batch {token.batch:04d}"
    age = "n/a" if evaluation.age_minutes is None else f"{evaluation.age_minutes:.1f} min"

    queue_lines = []
    for candidate in prepared[:8]:
        freshness = ""
        if candidate.branch:
            freshness = f" / branch {candidate.branch} / +{candidate.ahead_by or 0} -{candidate.behind_by or 0}"
        queue_lines.append(
            f"- Worker {candidate.worker} / {candidate.package} / batch {candidate.batch:04d} / {candidate.source}{freshness}"
        )
    if not queue_lines:
        queue_lines.append("- none")

    found_lines = []
    for update in found[:8]:
        found_lines.append(f"- Worker {update.worker} / {update.label}")
    if not found_lines:
        found_lines.append("- none")

    state = {
        "schema_version": "1",
        "generated_at": iso_now(),
        "controller_sha": controller_sha,
        "main_sha": main_sha,
        "exact_count": manifest["exact"],
        "event_count": manifest["total"],
        "unresolved_count": manifest["unresolved"],
        "step9": "PASS" if manifest["exact"] == policy["fail_closed_until_exact_count"] else "SOURCE_BLOCKED",
        "token": None if token is None else asdict(token),
        "token_evaluation": asdict(evaluation),
        "prepared_queue": [asdict(c) for c in prepared[:8]],
    }

    return (
        f"{marker}\n"
        "## G1 Swarm Controller State\n\n"
        f"- Main: {main_sha}\n"
        f"- G1 exact: {manifest['exact']}/{manifest['total']} ({manifest['unresolved']} unresolved)\n"
        f"- Step 9: {'PASS' if manifest['exact'] == policy['fail_closed_until_exact_count'] else 'SOURCE_BLOCKED'}\n"
        f"- Token: {token_text}\n"
        f"- Token state: {evaluation.state} — {evaluation.reason} — age {age}\n"
        f"- Lease: {policy['token_lease_minutes']} minutes\n\n"
        "### Prepared queue\n"
        + "\n".join(queue_lines)
        + "\n\n### Recovered-but-not-prepared\n"
        + "\n".join(found_lines)
        + "\n\n### Machine state\n"
        + json.dumps(state, indent=2, sort_keys=True)
        + "\n\nThis controller coordinates only. It never edits G1 evidence, runs a write-enabled publisher, opens a canonical G1 PR, merges a PR, or weakens CI/release gates."
    )


def render_advance_comment(
    *,
    candidate: Candidate | None,
    reason: str,
    main_sha: str,
    manifest: dict[str, Any],
    lease_minutes: int,
) -> str:
    if candidate is None:
        return (
            "EXECUTIVE TOKEN ADVANCE — automatic G1 swarm controller\n\n"
            f"- Trigger: {reason}\n"
            f"- Verified main: {main_sha}\n"
            f"- G1: {manifest['exact']}/{manifest['total']} exact, {manifest['unresolved']} fail-closed.\n"
            "- GLOBAL INTEGRATION TOKEN is now UNASSIGNED because no eligible PREPARED or FOUND package exists.\n"
            "- All workers should continue research/prep within ownership; no canonical publisher/PR is authorized until a new explicit assignment appears."
        )

    preparation = (
        "regenerate its prepared package"
        if candidate.status in PREPARED_STATUSES
        else "prepare and regenerate its recovered package"
    )
    return (
        "EXECUTIVE TOKEN ADVANCE — automatic G1 swarm controller\n\n"
        f"- Trigger: {reason}\n"
        f"- Verified main: {main_sha}\n"
        f"- G1: {manifest['exact']}/{manifest['total']} exact, {manifest['unresolved']} fail-closed; Step 9 remains SOURCE_BLOCKED.\n"
        f"- GLOBAL INTEGRATION TOKEN now advances to Worker {candidate.worker} / {candidate.package} / reserved batch {candidate.batch:04d}.\n"
        f"- Worker {candidate.worker} must {preparation} from exact current main, verify the events remain unresolved/unclaimed, and run the complete exact-head gate set before merge.\n"
        f"- Token lease: {lease_minutes} minutes to produce new BUILDING/CI/PR evidence. If the holder silently stalls, the controller advances to the next eligible package.\n"
        "- This handoff does not waive ownership, source admissibility, batch-lane, current-base, CI, expected_head_sha, or post-merge verification requirements."
    )


def controller_plan(
    *,
    root: Path,
    policy: dict[str, Any],
    comments: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
    refs: list[dict[str, Any]],
    compares: dict[str, dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    manifest = manifest_state(root, policy)
    # Thread the exact main snapshot through token evaluation so open PRs based
    # on older main commits cannot masquerade as live progress.
    manifest["main_sha"] = str(compares.get("__main_sha__") or "")
    updates = parse_worker_updates(comments)
    token = parse_latest_token(comments)

    issue_candidates = collect_issue_candidates(comments, updates)
    branch_rows = branch_candidates(refs, compares)
    candidate_evidence = issue_candidates + branch_rows
    evaluation = evaluate_token(
        token,
        comments=comments,
        pulls=pulls,
        updates=updates,
        manifest=manifest,
        lease_minutes=int(policy["token_lease_minutes"]),
        now=now,
        candidates=candidate_evidence,
    )

    all_prepared = dedupe_candidates(require_live_prepared_support(candidate_evidence))
    prepared = [
        c
        for c in all_prepared
        if lane_valid(c.worker, c.batch, policy)
        and not candidate_is_resolved(c, manifest, pulls, updates)
        and not (token and token.worker == c.worker and token.batch == c.batch)
    ]
    prepared.sort(
        key=lambda c: (
            {"issue_prepared": 0, "prep_branch_fallback": 1, "queue_hint": 2}.get(c.source, 9),
            parse_time(c.created_at) or datetime.max.replace(tzinfo=timezone.utc),
            c.batch,
        )
    )

    found_updates = [
        update
        for update in latest_updates_by_identity(updates).values()
        if update.status == "FOUND" and not update_is_resolved(update, manifest)
    ]
    found_updates.sort(key=lambda u: parse_time(u.created_at) or datetime.max.replace(tzinfo=timezone.utc))

    next_candidate = choose_prepared_candidate(
        candidate_evidence,
        token=token,
        manifest=manifest,
        pulls=pulls,
        updates=updates,
        policy=policy,
    )
    used = used_batches(updates, issue_candidates, branch_rows, pulls)
    if next_candidate is None:
        next_candidate = choose_found_candidate(
            updates,
            manifest=manifest,
            used=used,
            policy=policy,
        )

    action = "NONE"
    action_reason = ""
    if evaluation.state in {"RESOLVED", "CLOSED_UNMERGED", "STALLED", "INVALID"}:
        action = "ADVANCE"
        action_reason = evaluation.reason
    elif evaluation.state == "UNASSIGNED" and next_candidate is not None:
        action = "ADVANCE"
        action_reason = "no active token and an eligible package is ready"

    return {
        "manifest": manifest,
        "updates": updates,
        "token": token,
        "evaluation": evaluation,
        "prepared": prepared,
        "found_updates": found_updates,
        "next_candidate": next_candidate,
        "action": action,
        "action_reason": action_reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic G1 swarm token coordinator")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--controller-sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    policy = load_policy(root)
    repo = str(args.repository or "").strip()
    token_env = str(os.environ.get("GITHUB_TOKEN") or "").strip()
    if not repo:
        raise SystemExit("--repository or GITHUB_REPOSITORY is required")
    if args.apply and not token_env:
        raise SystemExit("GITHUB_TOKEN is required with --apply")

    api_token = token_env
    if not api_token:
        raise SystemExit("GITHUB_TOKEN is required to reconstruct live swarm state")

    issue = int(policy["issue_number"])
    comments = paginated(repo, api_token, f"/issues/{issue}/comments")
    pulls = paginated(repo, api_token, "/pulls?state=all&sort=updated&direction=desc", max_pages=3)
    main = github_api(repo, api_token, "/branches/main")
    main_sha = str(((main or {}).get("commit") or {}).get("sha") or "")
    refs, compares = fetch_branch_fallbacks(repo, api_token, main_sha)
    compares["__main_sha__"] = main_sha

    now = datetime.now(timezone.utc)
    plan = controller_plan(
        root=root,
        policy=policy,
        comments=comments,
        pulls=pulls,
        refs=refs,
        compares=compares,
        now=now,
    )

    final_token = plan["token"]
    final_evaluation = plan["evaluation"]

    # Token mutation is the only authority-changing action this controller can take.
    # Re-read GitHub immediately before that write so a worker/PR update that landed
    # during this run cannot be overwritten by a stale handoff decision.
    if args.apply and plan["action"] == "ADVANCE":
        fresh_main = github_api(repo, api_token, "/branches/main")
        fresh_main_sha = str(((fresh_main or {}).get("commit") or {}).get("sha") or "")
        if fresh_main_sha != main_sha:
            print(
                json.dumps(
                    {
                        "action": "ABORT_STALE_MAIN",
                        "planned_main_sha": main_sha,
                        "fresh_main_sha": fresh_main_sha,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        fresh_comments = paginated(repo, api_token, f"/issues/{issue}/comments")
        fresh_pulls = paginated(
            repo,
            api_token,
            "/pulls?state=all&sort=updated&direction=desc",
            max_pages=3,
        )
        fresh_refs, fresh_compares = fetch_branch_fallbacks(repo, api_token, main_sha)
        fresh_compares["__main_sha__"] = main_sha
        plan = controller_plan(
            root=root,
            policy=policy,
            comments=fresh_comments,
            pulls=fresh_pulls,
            refs=fresh_refs,
            compares=fresh_compares,
            now=datetime.now(timezone.utc),
        )
        comments = fresh_comments
        pulls = fresh_pulls
        final_token = plan["token"]
        final_evaluation = plan["evaluation"]

    if args.apply and plan["action"] == "ADVANCE":
        body = render_advance_comment(
            candidate=plan["next_candidate"],
            reason=plan["action_reason"],
            main_sha=main_sha,
            manifest=plan["manifest"],
            lease_minutes=int(policy["token_lease_minutes"]),
        )
        created = github_api(repo, api_token, f"/issues/{issue}/comments", method="POST", payload={"body": body})
        if plan["next_candidate"] is None:
            final_token = TokenAssignment(None, "UNASSIGNED", None, str(created.get("created_at") or iso_now()), created.get("id"))
        else:
            candidate = plan["next_candidate"]
            final_token = TokenAssignment(
                candidate.worker,
                candidate.package,
                candidate.batch,
                str(created.get("created_at") or iso_now()),
                created.get("id"),
            )
        final_evaluation = TokenEvaluation(
            "ACTIVE" if final_token.worker is not None else "UNASSIGNED",
            "automatic controller handoff just written",
            0.0 if final_token.worker is not None else None,
            False,
            None,
            None,
        )
        comments.append(created)

    state_body = render_state_comment(
        policy=policy,
        main_sha=main_sha,
        manifest=plan["manifest"],
        token=final_token,
        evaluation=final_evaluation,
        prepared=plan["prepared"],
        found=plan["found_updates"],
        controller_sha=str(args.controller_sha or main_sha),
    )

    if args.apply:
        existing = find_state_comment(comments, str(policy["state_comment_marker"]))
        if existing is None:
            github_api(repo, api_token, f"/issues/{issue}/comments", method="POST", payload={"body": state_body})
        else:
            github_api(
                repo,
                api_token,
                f"/issues/comments/{existing['id']}",
                method="PATCH",
                payload={"body": state_body},
            )

    summary = {
        "main_sha": main_sha,
        "exact": plan["manifest"]["exact"],
        "total": plan["manifest"]["total"],
        "unresolved": plan["manifest"]["unresolved"],
        "token": None if final_token is None else asdict(final_token),
        "token_evaluation": asdict(final_evaluation),
        "action": plan["action"],
        "action_reason": plan["action_reason"],
        "next_candidate": None if plan["next_candidate"] is None else asdict(plan["next_candidate"]),
        "prepared_queue": [asdict(c) for c in plan["prepared"][:8]],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
