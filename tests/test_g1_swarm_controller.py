from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import g1_swarm_controller as ctl


def policy() -> dict:
    return {
        "batch_lanes": {
            "0": {"start": 60, "step": 5},
            "1": {"start": 61, "step": 5},
            "2": {"start": 62, "step": 5},
            "3": {"start": 63, "step": 5},
            "4": {"start": 64, "step": 5},
        },
        "token_lease_minutes": 120,
    }


def manifest(*, unresolved_symbols: dict[str, set[str]] | None = None) -> dict:
    unresolved_symbols = unresolved_symbols or {}
    unresolved_ids = set().union(*unresolved_symbols.values()) if unresolved_symbols else set()
    return {
        "total": 174,
        "exact": 174 - len(unresolved_ids),
        "unresolved": len(unresolved_ids),
        "resolved_ids": set(),
        "unresolved_ids": unresolved_ids,
        "unresolved_by_symbol": unresolved_symbols,
    }


def comment(cid: int, created_at: str, body: str) -> dict:
    return {"id": cid, "created_at": created_at, "body": body}


def test_latest_explicit_token_assignment_wins() -> None:
    comments = [
        comment(
            1,
            "2026-10-01T12:00:00Z",
            "INTEGRATION TOKEN ADVANCE\n- Token now assigned to Worker 4 / BRKR / reserved batch 0064.",
        ),
        comment(
            2,
            "2026-10-01T13:00:00Z",
            "EXECUTIVE TOKEN RECOVERY\n- GLOBAL INTEGRATION TOKEN now advances to Worker 2 / EW+TIBX / reserved batch 0067.",
        ),
    ]

    token = ctl.parse_latest_token(comments)

    assert token is not None
    assert token.worker == 2
    assert token.package == "EW+TIBX"
    assert token.batch == 67
    assert token.comment_id == 2


def test_unassigned_token_supersedes_older_assignment() -> None:
    comments = [
        comment(
            1,
            "2026-10-01T12:00:00Z",
            "GLOBAL INTEGRATION TOKEN now advances to Worker 2 / EW+TIBX / reserved batch 0067.",
        ),
        comment(
            2,
            "2026-10-01T13:00:00Z",
            "GLOBAL INTEGRATION TOKEN is now UNASSIGNED because no eligible package exists.",
        ),
    ]

    token = ctl.parse_latest_token(comments)

    assert token is not None
    assert token.worker is None
    assert token.batch is None


def test_worker_update_parser_preserves_event_identity() -> None:
    comments = [
        comment(
            3,
            "2026-10-01T13:10:00Z",
            "WORKER 0 | HEJFE-760E36DA94752F1E/CAKE | FOUND | next eligible Worker-0 batch | source | next target",
        )
    ]

    updates = ctl.parse_worker_updates(comments)

    assert len(updates) == 1
    assert updates[0].worker == 0
    assert updates[0].status == "FOUND"
    assert updates[0].event_ids == ("HEJFE-760E36DA94752F1E",)
    assert updates[0].symbols == ("CAKE",)


def test_batch_lane_is_deterministic() -> None:
    p = policy()

    assert ctl.lane_valid(2, 67, p)
    assert ctl.lane_valid(3, 73, p)
    assert not ctl.lane_valid(4, 68, p)
    assert not ctl.lane_valid(1, 67, p)


def test_token_stalls_after_lease_without_progress() -> None:
    token = ctl.TokenAssignment(
        worker=2,
        package="EW+TIBX",
        batch=67,
        assigned_at="2026-10-01T10:00:00Z",
        comment_id=10,
    )

    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=[],
        updates=[],
        manifest=manifest(
            unresolved_symbols={
                "EW": {"HEJFE-ED329F780A1085DA"},
                "TIBX": {"HEJFE-2C887DA6F617936F"},
            }
        ),
        lease_minutes=120,
        now=datetime(2026, 10, 1, 12, 1, tzinfo=timezone.utc),
    )

    assert result.state == "STALLED"
    assert result.progress_after_assignment is False


def test_building_update_keeps_token_active_past_lease() -> None:
    token = ctl.TokenAssignment(
        worker=2,
        package="EW+TIBX",
        batch=67,
        assigned_at="2026-10-01T10:00:00Z",
        comment_id=10,
    )
    updates = ctl.parse_worker_updates(
        [
            comment(
                11,
                "2026-10-01T11:30:00Z",
                "WORKER 2 | EW+TIBX | BUILDING | batch 0067 / branch g1/public-batch-0067 | source | next",
            )
        ]
    )

    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=[],
        updates=updates,
        manifest=manifest(
            unresolved_symbols={
                "EW": {"HEJFE-ED329F780A1085DA"},
                "TIBX": {"HEJFE-2C887DA6F617936F"},
            }
        ),
        lease_minutes=120,
        now=datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc),
    )

    assert result.state == "ACTIVE"
    assert result.progress_after_assignment is True


def test_closed_matching_pr_releases_token() -> None:
    token = ctl.TokenAssignment(
        worker=2,
        package="EW+TIBX",
        batch=67,
        assigned_at="2026-10-01T10:00:00Z",
        comment_id=10,
    )
    pulls = [
        {
            "number": 170,
            "state": "closed",
            "merged_at": "2026-10-01T10:30:00Z",
            "title": "G1 Worker 2 batch 0067: recover EW and TIBX",
            "body": "",
            "head": {"ref": "g1/public-batch-0067-worker-2-ew-tibx"},
        }
    ]

    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=pulls,
        updates=[],
        manifest=manifest(
            unresolved_symbols={
                "EW": {"HEJFE-ED329F780A1085DA"},
                "TIBX": {"HEJFE-2C887DA6F617936F"},
            }
        ),
        lease_minutes=120,
        now=datetime(2026, 10, 1, 10, 31, tzinfo=timezone.utc),
    )

    assert result.state == "RESOLVED"
    assert result.matching_closed_pr == 170


def test_uncorroborated_queue_hint_does_not_beat_live_branch_prep() -> None:
    p = policy()
    token = ctl.TokenAssignment(2, "EW+TIBX", 67, "2026-10-01T10:00:00Z", 10)
    candidates = [
        ctl.Candidate(
            worker=1,
            package="VDSI",
            batch=66,
            event_ids=(),
            symbols=("VDSI",),
            created_at="",
            source="prep_branch_fallback",
            status="PREPARED",
            branch="g1/prep-0066-worker-1-vdsi",
            behind_by=1,
            ahead_by=1,
        ),
        ctl.Candidate(
            worker=3,
            package="PNRA+ALGN",
            batch=73,
            event_ids=(),
            symbols=("PNRA", "ALGN"),
            created_at="2026-10-01T10:05:00Z",
            source="queue_hint",
            status="PREPARED",
        ),
    ]
    m = manifest(
        unresolved_symbols={
            "VDSI": {"HEJFE-AAAA000000000001"},
            "PNRA": {"HEJFE-AAAA000000000002"},
            "ALGN": {"HEJFE-AAAA000000000003"},
            "EW": {"HEJFE-AAAA000000000004"},
            "TIBX": {"HEJFE-AAAA000000000005"},
        }
    )

    chosen = ctl.choose_prepared_candidate(
        candidates,
        token=token,
        manifest=m,
        pulls=[],
        updates=[],
        policy=p,
    )

    assert chosen is not None
    assert chosen.worker == 1
    assert chosen.batch == 66


def test_controller_invalidates_token_backed_only_by_historical_queue_hint() -> None:
    token = ctl.TokenAssignment(
        worker=3,
        package="PNRA+ALGN",
        batch=73,
        assigned_at="2026-10-01T10:00:00Z",
        comment_id=10,
    )
    candidates = [
        ctl.Candidate(
            worker=3,
            package="PNRA+ALGN",
            batch=73,
            event_ids=(),
            symbols=("PNRA", "ALGN"),
            created_at="2026-10-01T09:00:00Z",
            source="queue_hint",
            status="PREPARED",
        )
    ]
    m = manifest(
        unresolved_symbols={
            "PNRA": {"HEJFE-AAAA000000000002"},
            "ALGN": {"HEJFE-AAAA000000000003"},
        }
    )

    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=[],
        updates=[],
        manifest=m,
        lease_minutes=120,
        now=datetime(2026, 10, 1, 10, 5, tzinfo=timezone.utc),
        candidates=candidates,
    )

    assert result.state == "INVALID"
    assert result.progress_after_assignment is False


def test_live_prepared_update_supports_active_token() -> None:
    token = ctl.TokenAssignment(
        worker=2,
        package="EW+TIBX",
        batch=67,
        assigned_at="2026-10-01T10:00:00Z",
        comment_id=10,
    )
    updates = ctl.parse_worker_updates(
        [
            comment(
                9,
                "2026-10-01T09:55:00Z",
                "WORKER 2 | EW+TIBX | PREPARED | batch 0067 / prep branch g1/prep-batch-0067-worker-2-ew-tibx | source | next",
            )
        ]
    )
    m = manifest(
        unresolved_symbols={
            "EW": {"HEJFE-AAAA000000000004"},
            "TIBX": {"HEJFE-AAAA000000000005"},
        }
    )

    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=[],
        updates=updates,
        manifest=m,
        lease_minutes=120,
        now=datetime(2026, 10, 1, 10, 5, tzinfo=timezone.utc),
        candidates=[],
    )

    assert result.state == "ACTIVE"

def test_resolved_candidate_is_skipped() -> None:
    p = policy()
    candidates = [
        ctl.Candidate(
            worker=4,
            package="BRKR",
            batch=64,
            event_ids=(),
            symbols=("BRKR",),
            created_at="2026-10-01T09:00:00Z",
            source="issue_prepared",
            status="PREPARED",
        ),
        ctl.Candidate(
            worker=3,
            package="PNRA+ALGN",
            batch=73,
            event_ids=(),
            symbols=("PNRA", "ALGN"),
            created_at="2026-10-01T10:00:00Z",
            source="issue_prepared",
            status="PREPARED",
        ),
    ]
    m = manifest(
        unresolved_symbols={
            "PNRA": {"HEJFE-AAAA000000000002"},
            "ALGN": {"HEJFE-AAAA000000000003"},
        }
    )

    chosen = ctl.choose_prepared_candidate(
        candidates,
        token=None,
        manifest=m,
        pulls=[],
        updates=[],
        policy=p,
    )

    assert chosen is not None
    assert chosen.package == "PNRA+ALGN"


def test_parse_prep_branch_strips_base_sha_suffix() -> None:
    parsed = ctl.parse_prep_branch("g1/prep-batch-0073-worker-3-pnra-algn-cf5a70f")

    assert parsed == (3, 73, "PNRA+ALGN")


def test_next_unused_batch_respects_worker_lane() -> None:
    p = policy()
    used = {worker: set() for worker in range(5)}
    used[0].update({60, 65})

    assert ctl.next_unused_batch(0, used, p) == 70
    assert ctl.next_unused_batch(2, used, p) == 62


def test_closed_unmerged_candidate_remains_eligible_for_later_repair() -> None:
    p = policy()
    candidate = ctl.Candidate(
        worker=2,
        package="EW+TIBX",
        batch=67,
        event_ids=(),
        symbols=("EW", "TIBX"),
        created_at="2026-10-01T10:00:00Z",
        source="issue_prepared",
        status="PREPARED",
    )
    pulls = [
        {
            "number": 170,
            "state": "closed",
            "merged_at": None,
            "title": "G1 Worker 2 batch 0067: recover EW and TIBX",
            "body": "",
            "head": {"ref": "g1/public-batch-0067-worker-2-ew-tibx"},
        }
    ]
    m = manifest(
        unresolved_symbols={
            "EW": {"HEJFE-AAAA000000000004"},
            "TIBX": {"HEJFE-AAAA000000000005"},
        }
    )

    chosen = ctl.choose_prepared_candidate(
        [candidate],
        token=None,
        manifest=m,
        pulls=pulls,
        updates=[],
        policy=p,
    )

    assert chosen is not None
    assert chosen.batch == 67


def test_closed_unmerged_token_releases_lease_without_resolving_package() -> None:
    token = ctl.TokenAssignment(
        worker=2,
        package="EW+TIBX",
        batch=67,
        assigned_at="2026-10-01T10:00:00Z",
        comment_id=10,
    )
    pulls = [
        {
            "number": 170,
            "state": "closed",
            "merged_at": None,
            "merged": False,
            "title": "G1 Worker 2 batch 0067: recover EW and TIBX",
            "body": "",
            "head": {"ref": "g1/public-batch-0067-worker-2-ew-tibx"},
        }
    ]
    m = manifest(
        unresolved_symbols={
            "EW": {"HEJFE-AAAA000000000004"},
            "TIBX": {"HEJFE-AAAA000000000005"},
        }
    )

    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=pulls,
        updates=[],
        manifest=m,
        lease_minutes=120,
        now=datetime(2026, 10, 1, 10, 31, tzinfo=timezone.utc),
    )

    assert result.state == "CLOSED_UNMERGED"
    assert result.matching_closed_pr == 170

    candidate = ctl.Candidate(
        worker=2,
        package="EW+TIBX",
        batch=67,
        event_ids=(),
        symbols=("EW", "TIBX"),
        created_at="2026-10-01T10:00:00Z",
        source="issue_prepared",
        status="PREPARED",
    )
    assert ctl.candidate_is_resolved(candidate, m, pulls, []) is False


def test_pr_batch_match_requires_batch_context_not_random_digits() -> None:
    unrelated = {
        "number": 999,
        "state": "closed",
        "merged_at": None,
        "title": "Maintenance change",
        "body": "receipt digest abc67def remains unchanged",
        "head": {"ref": "maintenance/abc67def"},
    }
    assert ctl.pr_matches(2, "EW+TIBX", 67, unrelated) is False

    related = {
        "number": 1000,
        "state": "open",
        "merged_at": None,
        "title": "G1 Worker 2 batch 0067: recover EW and TIBX",
        "body": "",
        "head": {"ref": "g1/public-batch-0067-worker-2-ew-tibx"},
    }
    assert ctl.pr_matches(2, "EW+TIBX", 67, related) is True


def test_token_parser_accepts_event_id_slash_symbol_package() -> None:
    comments = [
        comment(
            20,
            "2026-10-01T15:17:00Z",
            "EXECUTIVE TOKEN ADVANCE\n- GLOBAL INTEGRATION TOKEN now advances to Worker 2 / HEJFE-ED329F780A1085DA/EW / reserved batch 0072.",
        )
    ]
    token = ctl.parse_latest_token(comments)
    assert token is not None
    assert token.worker == 2
    assert token.package == "HEJFE-ED329F780A1085DA/EW"
    assert token.batch == 72


def test_token_parser_accepts_explicit_correction_and_makes_it_latest() -> None:
    comments = [
        comment(
            20,
            "2026-10-01T15:17:00Z",
            "GLOBAL INTEGRATION TOKEN now advances to Worker 2 / HEJFE-ED329F780A1085DA/EW / reserved batch 0072.",
        ),
        comment(
            21,
            "2026-10-01T15:17:33Z",
            "GLOBAL INTEGRATION TOKEN is corrected back to Worker 2 / EW+TIBX / reserved batch 0067.",
        ),
    ]
    token = ctl.parse_latest_token(comments)
    assert token is not None
    assert token.worker == 2
    assert token.package == "EW+TIBX"
    assert token.batch == 67
    assert token.comment_id == 21
