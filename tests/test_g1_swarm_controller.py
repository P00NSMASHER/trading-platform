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
        "worker_count": 5,
        "event_owner_overrides": {
            "HEJFE-45E6DA32B37F83D4": 0,
            "HEJFE-66BA40A20548B7E3": 4,
            "HEJFE-81F188C0D790FE70": None,
            "HEJFE-8415E931D4314106": 4,
        },
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
            "EXECUTIVE TOKEN RECOVERY\n- GLOBAL INTEGRATION TOKEN now advances to Worker 2 / EW+MXIM / reserved batch 0067.",
        ),
    ]

    token = ctl.parse_latest_token(comments)

    assert token is not None
    assert token.worker == 2
    assert token.package == "EW+MXIM"
    assert token.batch == 67
    assert token.comment_id == 2


def test_unassigned_token_supersedes_older_assignment() -> None:
    comments = [
        comment(
            1,
            "2026-10-01T12:00:00Z",
            "GLOBAL INTEGRATION TOKEN now advances to Worker 2 / EW+MXIM / reserved batch 0067.",
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


def test_worker_update_parser_ignores_next_target_event_ids() -> None:
    comments = [
        comment(
            4,
            "2026-10-01T13:11:00Z",
            "WORKER 2 | HEJFE-ED329F780A1085DA/EW | FOUND | reserved 0067 prep | source | exact clock; next target: HEJFE-CCC7747CFBDE893E/PNRA",
        )
    ]

    updates = ctl.parse_worker_updates(comments)

    assert len(updates) == 1
    assert updates[0].event_ids == ("HEJFE-ED329F780A1085DA",)
    assert updates[0].symbols == ("EW",)

    m = manifest(unresolved_symbols={"PNRA": {"HEJFE-CCC7747CFBDE893E"}})
    m["resolved_ids"] = {"HEJFE-ED329F780A1085DA"}
    assert ctl.update_is_resolved(updates[0], m) is True


def test_batch_lane_is_deterministic() -> None:
    p = policy()

    assert ctl.lane_valid(2, 67, p)
    assert ctl.lane_valid(3, 73, p)
    assert not ctl.lane_valid(4, 68, p)
    assert not ctl.lane_valid(1, 67, p)


def test_event_owner_uses_hard_shards_and_explicit_overrides() -> None:
    p = policy()

    assert ctl.event_owner("HEJFE-AF5106891E058D23", p) == 1
    assert ctl.event_owner("HEJFE-47A3794D1C360650", p) == 3
    assert ctl.event_owner("HEJFE-EDFDC1213C9AF586", p) == 2
    assert ctl.event_owner("HEJFE-1783DE88400AF6CC", p) == 4
    assert ctl.event_owner("HEJFE-45E6DA32B37F83D4", p) == 0
    assert ctl.event_owner("HEJFE-66BA40A20548B7E3", p) == 4
    assert ctl.event_owner("HEJFE-8415E931D4314106", p) == 4
    assert ctl.event_owner("HEJFE-81F188C0D790FE70", p) is None


def test_cross_shard_token_is_invalid_even_with_matching_progress() -> None:
    token = ctl.TokenAssignment(
        worker=2,
        package="HEJFE-AF5106891E058D23/TNGO + HEJFE-EDFDC1213C9AF586/MXIM",
        batch=97,
        assigned_at="2026-10-01T10:00:00Z",
        comment_id=10,
    )
    updates = ctl.parse_worker_updates(
        [
            comment(
                11,
                "2026-10-01T10:30:00Z",
                "WORKER 2 | HEJFE-AF5106891E058D23/TNGO + HEJFE-EDFDC1213C9AF586/MXIM | BUILDING | batch 0097 | source | next",
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
                "TNGO": {"HEJFE-AF5106891E058D23"},
                "MXIM": {"HEJFE-EDFDC1213C9AF586"},
            }
        ),
        lease_minutes=120,
        now=datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc),
        policy=policy(),
    )

    assert result.state == "INVALID"
    assert "ownership shard" in result.reason


def test_token_stalls_after_lease_without_progress() -> None:
    token = ctl.TokenAssignment(
        worker=2,
        package="EW+MXIM",
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
                "MXIM": {"HEJFE-EDFDC1213C9AF586"},
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
        package="EW+MXIM",
        batch=67,
        assigned_at="2026-10-01T10:00:00Z",
        comment_id=10,
    )
    updates = ctl.parse_worker_updates(
        [
            comment(
                11,
                "2026-10-01T11:30:00Z",
                "WORKER 2 | EW+MXIM | BUILDING | batch 0067 / branch g1/public-batch-0067 | source | next",
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
                "MXIM": {"HEJFE-EDFDC1213C9AF586"},
            }
        ),
        lease_minutes=120,
        now=datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc),
    )

    assert result.state == "ACTIVE"
    assert result.progress_after_assignment is True


def test_stale_building_update_does_not_extend_token_forever() -> None:
    token = ctl.TokenAssignment(
        worker=2,
        package="HEJFE-EDFDC1213C9AF586/MXIM",
        batch=97,
        assigned_at="2026-10-01T10:00:00Z",
        comment_id=10,
    )
    updates = ctl.parse_worker_updates(
        [
            comment(
                11,
                "2026-10-01T10:30:00Z",
                "WORKER 2 | HEJFE-EDFDC1213C9AF586/MXIM | BUILDING | batch 0097 | source | next",
            )
        ]
    )

    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=[],
        updates=updates,
        manifest=manifest(unresolved_symbols={"MXIM": {"HEJFE-EDFDC1213C9AF586"}}),
        lease_minutes=120,
        now=datetime(2026, 10, 1, 12, 31, tzinfo=timezone.utc),
        policy=policy(),
    )

    assert result.state == "STALLED"
    assert result.progress_after_assignment is True
    assert "without fresh" in result.reason


def test_closed_matching_pr_releases_token() -> None:
    token = ctl.TokenAssignment(
        worker=2,
        package="EW+MXIM",
        batch=67,
        assigned_at="2026-10-01T10:00:00Z",
        comment_id=10,
    )
    pulls = [
        {
            "number": 170,
            "state": "closed",
            "merged_at": "2026-10-01T10:30:00Z",
            "title": "G1 Worker 2 batch 0067: recover EW and MXIM",
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
                "MXIM": {"HEJFE-EDFDC1213C9AF586"},
            }
        ),
        lease_minutes=120,
        now=datetime(2026, 10, 1, 10, 31, tzinfo=timezone.utc),
    )

    assert result.state == "RESOLVED"
    assert result.matching_closed_pr == 170


def test_uncorroborated_queue_hint_does_not_beat_live_branch_prep() -> None:
    p = policy()
    token = ctl.TokenAssignment(2, "EW+MXIM", 67, "2026-10-01T10:00:00Z", 10)
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
            behind_by=0,
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
            "MXIM": {"HEJFE-AAAA000000000005"},
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


def test_controller_plan_advances_unassigned_live_prepared_candidate(monkeypatch) -> None:
    p = policy()
    comments = [
        comment(
            10,
            "2026-10-02T01:00:00Z",
            "GLOBAL INTEGRATION TOKEN is now UNASSIGNED because no eligible package exists.",
        ),
        comment(
            11,
            "2026-10-02T01:11:53Z",
            "WORKER 4 | HEJFE-D7FD00AF94DD8F41/JNPR | PREPARED | batch 0079 / g1/prep-0079-worker-4-jnpr-deadbee | exact-current-main prep | next",
        ),
    ]
    refs = [
        {
            "ref": "refs/heads/g1/prep-0079-worker-4-jnpr-deadbee",
            "object": {"sha": "feedface"},
        }
    ]
    compares = {
        "__main_sha__": "current-main",
        "g1/prep-0079-worker-4-jnpr-deadbee": {
            "behind_by": 0,
            "ahead_by": 1,
        },
    }
    m = manifest(unresolved_symbols={"JNPR": {"HEJFE-D7FD00AF94DD8F41"}})
    monkeypatch.setattr(ctl, "manifest_state", lambda root, policy: m)

    plan = ctl.controller_plan(
        root=ROOT,
        policy=p,
        comments=comments,
        pulls=[],
        refs=refs,
        compares=compares,
        now=datetime(2026, 10, 2, 1, 12, tzinfo=timezone.utc),
    )

    assert plan["next_candidate"] is not None
    assert plan["next_candidate"].worker == 4
    assert plan["next_candidate"].batch == 79
    assert plan["next_candidate"].package == "HEJFE-D7FD00AF94DD8F41/JNPR"
    assert plan["action"] == "ADVANCE"


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


def test_prepared_comment_without_fresh_branch_does_not_support_active_token() -> None:
    token = ctl.TokenAssignment(
        worker=2,
        package="EW+MXIM",
        batch=67,
        assigned_at="2026-10-01T10:00:00Z",
        comment_id=10,
    )
    updates = ctl.parse_worker_updates(
        [
            comment(
                9,
                "2026-10-01T09:55:00Z",
                "WORKER 2 | EW+MXIM | PREPARED | batch 0067 / prep branch g1/prep-batch-0067-worker-2-ew-tibx | source | next",
            )
        ]
    )
    m = manifest(
        unresolved_symbols={
            "EW": {"HEJFE-AAAA000000000004"},
            "MXIM": {"HEJFE-AAAA000000000005"},
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

    assert result.state == "INVALID"

def test_stale_prep_branch_remains_visible_but_cannot_receive_new_token() -> None:
    candidates = ctl.branch_candidates(
        [
            {
                "ref": "refs/heads/g1/prep-batch-0067-worker-2-ew-tibx-deadbee",
                "object": {"sha": "deadbeef"},
            }
        ],
        {
            "g1/prep-batch-0067-worker-2-ew-tibx-deadbee": {
                "behind_by": 23,
                "ahead_by": 1,
            }
        },
    )

    assert len(candidates) == 1
    assert candidates[0].behind_by == 23

    chosen = ctl.choose_prepared_candidate(
        candidates,
        token=None,
        manifest=manifest(
            unresolved_symbols={
                "EW": {"HEJFE-AAAA000000000004"},
                "MXIM": {"HEJFE-AAAA000000000005"},
            }
        ),
        pulls=[],
        updates=[],
        policy=policy(),
    )
    assert chosen is None


def test_stale_prep_branch_with_latest_prepared_comment_can_receive_new_token() -> None:
    comments = [
        comment(
            11,
            "2026-10-02T01:11:53Z",
            "WORKER 0 | HEJFE-4291CBF555CED6A9/PBI | PREPARED | batch 0090 / g1/prep-0090-worker-0-pbi-deadbee | source | next",
        )
    ]
    updates = ctl.parse_worker_updates(comments)
    candidates = ctl.collect_issue_candidates(comments, updates)
    candidates.extend(
        ctl.branch_candidates(
            [
                {
                    "ref": "refs/heads/g1/prep-0090-worker-0-pbi-deadbee",
                    "object": {"sha": "deadbeef"},
                }
            ],
            {
                "g1/prep-0090-worker-0-pbi-deadbee": {
                    "behind_by": 7,
                    "ahead_by": 1,
                }
            },
        )
    )

    chosen = ctl.choose_prepared_candidate(
        candidates,
        token=None,
        manifest=manifest(
            unresolved_symbols={"PBI": {"HEJFE-4291CBF555CED6A9"}}
        ),
        pulls=[],
        updates=updates,
        policy=policy(),
    )

    assert chosen is not None
    assert chosen.worker == 0
    assert chosen.batch == 90
    assert chosen.package == "HEJFE-4291CBF555CED6A9/PBI"


def test_stale_prep_branch_with_invalidated_latest_comment_stays_ineligible() -> None:
    comments = [
        comment(
            11,
            "2026-10-02T01:11:53Z",
            "WORKER 0 | HEJFE-4291CBF555CED6A9/PBI | PREPARED | batch 0090 / g1/prep-0090-worker-0-pbi-deadbee | source | next",
        ),
        comment(
            12,
            "2026-10-02T01:12:53Z",
            "WORKER 0 | HEJFE-4291CBF555CED6A9/PBI | PREP_INVALIDATED | batch 0090 / evidence withdrawn",
        ),
    ]
    updates = ctl.parse_worker_updates(comments)
    candidates = ctl.collect_issue_candidates(comments, updates)
    candidates.extend(
        ctl.branch_candidates(
            [
                {
                    "ref": "refs/heads/g1/prep-0090-worker-0-pbi-deadbee",
                    "object": {"sha": "deadbeef"},
                }
            ],
            {
                "g1/prep-0090-worker-0-pbi-deadbee": {
                    "behind_by": 7,
                    "ahead_by": 1,
                }
            },
        )
    )

    chosen = ctl.choose_prepared_candidate(
        candidates,
        token=None,
        manifest=manifest(
            unresolved_symbols={"PBI": {"HEJFE-4291CBF555CED6A9"}}
        ),
        pulls=[],
        updates=updates,
        policy=policy(),
    )

    assert chosen is None


def test_stale_prep_branch_keeps_existing_token_within_lease() -> None:
    token = ctl.TokenAssignment(2, "EW+MXIM", 67, "2026-10-01T10:00:00Z", 10)
    candidates = [
        ctl.Candidate(
            worker=2,
            package="EW+MXIM",
            batch=67,
            event_ids=(),
            symbols=("EW", "MXIM"),
            created_at="",
            source="prep_branch_fallback",
            status="PREPARED",
            branch="g1/prep-batch-0067-worker-2-ew-tibx-deadbee",
            behind_by=1,
            ahead_by=1,
        )
    ]
    m = manifest(
        unresolved_symbols={
            "EW": {"HEJFE-AAAA000000000004"},
            "MXIM": {"HEJFE-AAAA000000000005"},
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

    assert result.state == "ACTIVE"
    assert result.progress_after_assignment is False


def test_stale_prep_branch_does_not_extend_token_past_lease() -> None:
    token = ctl.TokenAssignment(2, "EW+MXIM", 67, "2026-10-01T10:00:00Z", 10)
    candidates = [
        ctl.Candidate(
            worker=2,
            package="EW+MXIM",
            batch=67,
            event_ids=(),
            symbols=("EW", "MXIM"),
            created_at="",
            source="prep_branch_fallback",
            status="PREPARED",
            branch="g1/prep-batch-0067-worker-2-ew-tibx-deadbee",
            behind_by=1,
            ahead_by=1,
        )
    ]
    m = manifest(
        unresolved_symbols={
            "EW": {"HEJFE-AAAA000000000004"},
            "MXIM": {"HEJFE-AAAA000000000005"},
        }
    )

    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=[],
        updates=[],
        manifest=m,
        lease_minutes=120,
        now=datetime(2026, 10, 1, 12, 1, tzinfo=timezone.utc),
        candidates=candidates,
    )

    assert result.state == "STALLED"
    assert result.progress_after_assignment is False


def test_fetch_branch_fallbacks_does_not_truncate_after_30(monkeypatch) -> None:
    refs = [
        {
            "ref": f"refs/heads/g1/prep-0067-worker-2-ew-tibx-dead{i:02x}",
            "object": {"sha": f"{i:040x}"},
        }
        for i in range(35)
    ]

    def fake_github_api(repo: str, token: str, path: str, **kwargs):
        if path.startswith("/git/matching-refs/heads/g1/prep-"):
            return refs
        if path.startswith("/compare/"):
            return {"behind_by": 0, "ahead_by": 1}
        raise AssertionError(path)

    monkeypatch.setattr(ctl, "github_api", fake_github_api)

    found_refs, compares = ctl.fetch_branch_fallbacks("owner/repo", "token", "main-sha")

    assert len(found_refs) == 35
    assert len(compares) == 35


def test_exact_current_main_prep_branch_is_live_support() -> None:
    candidates = ctl.branch_candidates(
        [
            {
                "ref": "refs/heads/g1/prep-batch-0067-worker-2-ew-tibx-deadbee",
                "object": {"sha": "deadbeef"},
            }
        ],
        {
            "g1/prep-batch-0067-worker-2-ew-tibx-deadbee": {
                "behind_by": 0,
                "ahead_by": 1,
            }
        },
    )
    assert len(candidates) == 1
    assert candidates[0].behind_by == 0


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
            source="prep_branch_fallback",
            status="PREPARED",
            branch="g1/prep-0064-worker-4-brkr",
            behind_by=0,
            ahead_by=1,
        ),
        ctl.Candidate(
            worker=3,
            package="PNRA+ALGN",
            batch=73,
            event_ids=(),
            symbols=("PNRA", "ALGN"),
            created_at="2026-10-01T10:00:00Z",
            source="prep_branch_fallback",
            status="PREPARED",
            branch="g1/prep-0073-worker-3-pnra-algn",
            behind_by=0,
            ahead_by=1,
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


def test_latest_status_invalidates_older_found_for_same_event() -> None:
    updates = ctl.parse_worker_updates([
        comment(
            30,
            "2026-10-01T20:00:00Z",
            "WORKER 0 | HEJFE-8167467EBF64AABE/PNRA | FOUND | no batch/PR | candidate clock",
        ),
        comment(
            31,
            "2026-10-01T20:05:00Z",
            "WORKER 0 | HEJFE-8167467EBF64AABE/PNRA | PREP_INVALIDATED | stale prep must remain research-only",
        ),
    ])
    latest = ctl.latest_updates_by_identity(updates)

    assert len(latest) == 1
    row = next(iter(latest.values()))
    assert row.status == "PREP_INVALIDATED"

    chosen = ctl.choose_found_candidate(
        updates,
        manifest=manifest(unresolved_symbols={"PNRA": {"HEJFE-8167467EBF64AABE"}}),
        used={worker: set() for worker in range(5)},
        policy=policy(),
    )
    assert chosen is None


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
        package="EW+MXIM",
        batch=67,
        event_ids=(),
        symbols=("EW", "MXIM"),
        created_at="2026-10-01T10:00:00Z",
        source="prep_branch_fallback",
        status="PREPARED",
        branch="g1/prep-batch-0067-worker-2-ew-tibx-current",
        behind_by=0,
        ahead_by=1,
    )
    pulls = [
        {
            "number": 170,
            "state": "closed",
            "merged_at": None,
            "title": "G1 Worker 2 batch 0067: recover EW and MXIM",
            "body": "",
            "head": {"ref": "g1/public-batch-0067-worker-2-ew-tibx"},
        }
    ]
    m = manifest(
        unresolved_symbols={
            "EW": {"HEJFE-AAAA000000000004"},
            "MXIM": {"HEJFE-AAAA000000000005"},
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
        package="EW+MXIM",
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
            "title": "G1 Worker 2 batch 0067: recover EW and MXIM",
            "body": "",
            "head": {"ref": "g1/public-batch-0067-worker-2-ew-tibx"},
        }
    ]
    m = manifest(
        unresolved_symbols={
            "EW": {"HEJFE-AAAA000000000004"},
            "MXIM": {"HEJFE-AAAA000000000005"},
        }
    )
    m["main_sha"] = "current-main"
    pulls[0]["base"] = {"sha": "current-main"}

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
        package="EW+MXIM",
        batch=67,
        event_ids=(),
        symbols=("EW", "MXIM"),
        created_at="2026-10-01T10:00:00Z",
        source="issue_prepared",
        status="PREPARED",
    )
    assert ctl.candidate_is_resolved(candidate, m, pulls, []) is False


def test_stale_closed_unmerged_pr_does_not_release_fresh_token() -> None:
    token = ctl.TokenAssignment(
        worker=0,
        package="HEJFE-6C4EA140AD75FFE2/THC",
        batch=85,
        assigned_at="2026-10-02T13:35:00Z",
        comment_id=20,
    )
    pulls = [
        {
            "number": 230,
            "state": "closed",
            "merged_at": None,
            "merged": False,
            "title": "G1 batch 0085: recover THC exact public clock",
            "body": "Worker 0 batch 0085",
            "head": {"ref": "g1/public-batch-0085-worker-0-thc-main-28a180a"},
            "base": {"sha": "old-main"},
        }
    ]
    m = manifest(unresolved_symbols={"THC": {"HEJFE-6C4EA140AD75FFE2"}})
    m["main_sha"] = "current-main"
    candidates = [
        ctl.Candidate(
            worker=0,
            package="THC",
            batch=85,
            event_ids=("HEJFE-6C4EA140AD75FFE2",),
            symbols=("THC",),
            created_at="2026-10-02T13:34:00Z",
            source="prep_branch_fallback",
            status="PREPARED",
            branch="g1/prep-0085-worker-0-thc-current",
            behind_by=0,
            ahead_by=1,
        )
    ]

    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=pulls,
        updates=[],
        manifest=m,
        lease_minutes=120,
        now=datetime(2026, 10, 2, 13, 36, tzinfo=timezone.utc),
        candidates=candidates,
    )

    assert result.state == "ACTIVE"
    assert result.matching_closed_pr is None


def test_preassignment_current_main_closed_pr_does_not_release_new_token() -> None:
    token = ctl.TokenAssignment(
        worker=0,
        package="HEJFE-6C4EA140AD75FFE2/THC",
        batch=85,
        assigned_at="2026-10-02T13:35:00Z",
        comment_id=20,
    )
    pulls = [
        {
            "number": 230,
            "state": "closed",
            "closed_at": "2026-10-02T13:33:58Z",
            "merged_at": None,
            "merged": False,
            "title": "G1 batch 0085: recover THC exact public clock",
            "body": "Worker 0 batch 0085",
            "head": {"ref": "g1/public-batch-0085-worker-0-thc-main-current"},
            "base": {"sha": "current-main"},
        }
    ]
    m = manifest(unresolved_symbols={"THC": {"HEJFE-6C4EA140AD75FFE2"}})
    m["main_sha"] = "current-main"
    candidates = [
        ctl.Candidate(
            worker=0,
            package="THC",
            batch=85,
            event_ids=("HEJFE-6C4EA140AD75FFE2",),
            symbols=("THC",),
            created_at="2026-10-02T13:34:17Z",
            source="prep_branch_fallback",
            status="PREPARED",
            branch="g1/prep-0085-worker-0-thc-current",
            behind_by=0,
            ahead_by=1,
        )
    ]

    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=pulls,
        updates=[],
        manifest=m,
        lease_minutes=120,
        now=datetime(2026, 10, 2, 13, 36, tzinfo=timezone.utc),
        candidates=candidates,
    )

    assert result.state == "ACTIVE"
    assert result.matching_closed_pr is None


def test_pr_batch_match_requires_batch_context_not_random_digits() -> None:
    unrelated = {
        "number": 999,
        "state": "closed",
        "merged_at": None,
        "title": "Maintenance change",
        "body": "receipt digest abc67def remains unchanged",
        "head": {"ref": "maintenance/abc67def"},
    }
    assert ctl.pr_matches(2, "EW+MXIM", 67, unrelated) is False

    related = {
        "number": 1000,
        "state": "open",
        "merged_at": None,
        "title": "G1 Worker 2 batch 0067: recover EW and MXIM",
        "body": "",
        "head": {"ref": "g1/public-batch-0067-worker-2-ew-tibx"},
    }
    assert ctl.pr_matches(2, "EW+MXIM", 67, related) is True


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
            "GLOBAL INTEGRATION TOKEN is corrected back to Worker 2 / EW+MXIM / reserved batch 0067.",
        ),
    ]
    token = ctl.parse_latest_token(comments)
    assert token is not None
    assert token.worker == 2
    assert token.package == "EW+MXIM"
    assert token.batch == 67
    assert token.comment_id == 21


def test_partial_package_update_cannot_extend_multi_event_token() -> None:
    token = ctl.TokenAssignment(2, "EW+MXIM", 67, "2026-10-01T10:00:00Z", 10)
    update = ctl.WorkerUpdate(
        worker=2,
        label="EW",
        status="BUILDING",
        batch=None,
        event_ids=(),
        symbols=("EW",),
        created_at="2026-10-01T11:00:00Z",
        comment_id=11,
        body="",
    )
    assert ctl.update_matches_token(update, token) is False


def test_stale_open_pr_does_not_keep_token_live() -> None:
    token = ctl.TokenAssignment(2, "EW+MXIM", 67, "2026-10-01T10:00:00Z", 10)
    m = manifest(
        unresolved_symbols={
            "EW": {"HEJFE-AAAA000000000004"},
            "MXIM": {"HEJFE-AAAA000000000005"},
        }
    )
    m["main_sha"] = "new-main"
    pulls = [{
        "number": 170,
        "state": "open",
        "merged_at": None,
        "title": "G1 Worker 2 batch 0067: recover EW and MXIM",
        "body": "",
        "head": {"ref": "g1/public-batch-0067-worker-2-ew-tibx"},
        "base": {"sha": "old-main"},
    }]
    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=pulls,
        updates=[],
        manifest=m,
        lease_minutes=120,
        now=datetime(2026, 10, 1, 12, 1, tzinfo=timezone.utc),
        candidates=[],
    )
    assert result.state == "INVALID"
    assert result.progress_after_assignment is False


def test_current_main_open_pr_counts_as_live_progress() -> None:
    token = ctl.TokenAssignment(2, "EW+MXIM", 67, "2026-10-01T10:00:00Z", 10)
    m = manifest(
        unresolved_symbols={
            "EW": {"HEJFE-AAAA000000000004"},
            "MXIM": {"HEJFE-AAAA000000000005"},
        }
    )
    m["main_sha"] = "current-main"
    pulls = [{
        "number": 170,
        "state": "open",
        "merged_at": None,
        "title": "G1 Worker 2 batch 0067: recover EW and MXIM",
        "body": "",
        "head": {"ref": "g1/public-batch-0067-worker-2-ew-tibx"},
        "base": {"sha": "current-main"},
    }]
    result = ctl.evaluate_token(
        token,
        comments=[],
        pulls=pulls,
        updates=[],
        manifest=m,
        lease_minutes=120,
        now=datetime(2026, 10, 1, 12, 1, tzinfo=timezone.utc),
        candidates=[],
    )
    assert result.state == "ACTIVE"
    assert result.progress_after_assignment is True


def test_same_batch_wrong_package_does_not_extend_token() -> None:
    token = ctl.TokenAssignment(2, "EW+MXIM", 67, "2026-10-01T10:00:00Z", 10)
    update = ctl.WorkerUpdate(
        worker=2,
        label="OTHER",
        status="BUILDING",
        batch=67,
        event_ids=(),
        symbols=("OTHER",),
        created_at="2026-10-01T11:00:00Z",
        comment_id=11,
        body="",
    )
    assert ctl.update_matches_token(update, token) is False


def test_batch_number_without_worker_identity_does_not_match_token_pr() -> None:
    pr = {
        "number": 999,
        "state": "open",
        "title": "Maintenance batch 0067 cleanup",
        "body": "",
        "head": {"ref": "maintenance/batch-0067"},
    }
    assert ctl.pr_matches(2, "EW+MXIM", 67, pr) is False


def test_fetch_branch_fallbacks_probes_newest_batches_first(monkeypatch) -> None:
    refs = [
        {"ref": "refs/heads/g1/prep-0060-worker-0-old-aaaaaaa", "object": {"sha": "oldsha"}},
        {"ref": "refs/heads/g1/prep-0117-worker-2-seven-bbbbbbb", "object": {"sha": "newsha"}},
    ]
    compare_paths = []

    def fake_api(repo, token, path, **kwargs):
        if path.startswith("/git/matching-refs/heads/g1/prep-"):
            return refs
        if path.startswith("/compare/"):
            compare_paths.append(path)
            return {"ahead_by": 1, "behind_by": 0}
        raise AssertionError(path)

    monkeypatch.setattr(ctl, "github_api", fake_api)
    found, compares = ctl.fetch_branch_fallbacks("owner/repo", "token", "mainsha")
    assert found == refs
    assert compare_paths[0].endswith("...newsha")
    assert "g1/prep-0117-worker-2-seven-bbbbbbb" in compares

def test_fetch_branch_fallbacks_paginates_matching_refs_before_priority_sort(monkeypatch) -> None:
    older = [
        {
            "ref": f"refs/heads/g1/prep-0060-worker-0-old-{i:07x}",
            "object": {"sha": f"{i + 1:040x}"},
        }
        for i in range(100)
    ]
    newest = {
        "ref": "refs/heads/g1/prep-0117-worker-2-current-bbbbbbb",
        "object": {"sha": "f" * 40},
    }
    compare_paths = []

    def fake_api(repo, token, path, **kwargs):
        if path == "/git/matching-refs/heads/g1/prep-?per_page=100&page=1":
            return older
        if path == "/git/matching-refs/heads/g1/prep-?per_page=100&page=2":
            return [newest]
        if path.startswith("/compare/"):
            compare_paths.append(path)
            return {"ahead_by": 1, "behind_by": 0}
        raise AssertionError(path)

    monkeypatch.setattr(ctl, "github_api", fake_api)
    found, compares = ctl.fetch_branch_fallbacks("owner/repo", "token", "mainsha")

    assert len(found) == 101
    assert compare_paths[0].endswith("..." + "f" * 40)
    assert "g1/prep-0117-worker-2-current-bbbbbbb" in compares

