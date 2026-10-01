from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from g1_swarm_controller import STATE_MARKER, build_report, owner_for_event


def _manifest():
    return {
        "items": [
            {
                "event_id": "HEJFE-AAAAAAAAAAAAAAAA",
                "historical_symbol": "AAA",
                "acquisition_status": "NEEDS_EXACT_PUBLIC_RELEASE_CLOCK",
                "current_resolution_status": "excluded_fail_closed",
            },
            {
                "event_id": "HEJFE-BBBBBBBBBBBBBBBB",
                "historical_symbol": "BBB",
                "acquisition_status": "NEEDS_EXACT_PUBLIC_RELEASE_CLOCK",
                "current_resolution_status": "excluded_fail_closed",
            },
            {
                "event_id": "HEJFE-CCCCCCCCCCCCCCCC",
                "historical_symbol": "CCC",
                "acquisition_status": "RESOLVED_NO_ACTION",
                "current_resolution_status": "resolved_exact_public_timestamp",
            },
        ]
    }


def _exclusions():
    return {
        "g1_state": {"required": 3, "exact_resolved": 1, "reviewed_excluded": 2},
        "exclusions": [
            {"event_id": "HEJFE-AAAAAAAAAAAAAAAA"},
            {"event_id": "HEJFE-BBBBBBBBBBBBBBBB"},
        ],
    }


def _step_status():
    return {"steps": [{"step": 9, "status": "SOURCE_BLOCKED"}]}


def _comment(comment_id, at, body):
    return {"id": comment_id, "created_at": at, "body": body}


def test_owner_is_deterministic_and_sharded():
    event_id = "HEJFE-AAAAAAAAAAAAAAAA"
    assert owner_for_event(event_id) == owner_for_event(event_id)
    assert 0 <= owner_for_event(event_id) <= 4


def test_prepared_package_is_selected_before_found():
    comments = [
        _comment(
            1,
            "2026-10-01T10:00:00Z",
            "WORKER 1 | HEJFE-AAAAAAAAAAAAAAAA/AAA | FOUND | no batch/PR | source | next",
        ),
        _comment(
            2,
            "2026-10-01T10:05:00Z",
            "WORKER 2 | HEJFE-BBBBBBBBBBBBBBBB/BBB | PREPARED | batch 0067 | source | next",
        ),
    ]
    report = build_report(
        _manifest(),
        _exclusions(),
        _step_status(),
        comments,
        [],
        main_sha="deadbeef",
        now=datetime(2026, 10, 1, 10, 10, tzinfo=timezone.utc),
    )
    assert report["summary"]["next_package"]["status"] == "PREPARED"
    assert report["summary"]["next_package"]["event_ids"] == ["HEJFE-BBBBBBBBBBBBBBBB"]
    assert report["summary"]["exact_resolved"] == 1
    assert report["summary"]["reviewed_fail_closed"] == 2
    assert report["state_comment_body"].startswith(STATE_MARKER)


def test_closed_token_pr_forces_advance():
    comments = [
        _comment(
            1,
            "2026-10-01T08:00:00Z",
            "GLOBAL INTEGRATION TOKEN now advances to Worker 2 / AAA / reserved batch 0067.",
        ),
        _comment(
            2,
            "2026-10-01T08:10:00Z",
            "WORKER 3 | HEJFE-BBBBBBBBBBBBBBBB/BBB | PREPARED | batch 0073 | source | next",
        ),
    ]
    pulls = [
        {
            "title": "G1 batch 0067: recover AAA",
            "state": "closed",
            "merged_at": "2026-10-01T08:30:00Z",
            "updated_at": "2026-10-01T08:30:00Z",
        }
    ]
    report = build_report(
        _manifest(),
        _exclusions(),
        _step_status(),
        comments,
        pulls,
        main_sha="cafebabe",
        now=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )
    assert report["summary"]["token"]["stale"] is True
    assert report["summary"]["token"]["state"] == "RESOLVED"
    assert "Worker 3" in report["token_comment_body"]
    assert "0073" in report["token_comment_body"]


def test_token_lease_expires_without_progress():
    comments = [
        _comment(
            1,
            "2026-10-01T06:00:00Z",
            "GLOBAL INTEGRATION TOKEN now advances to Worker 2 / AAA / reserved batch 0067.",
        ),
        _comment(
            2,
            "2026-10-01T06:10:00Z",
            "WORKER 3 | HEJFE-BBBBBBBBBBBBBBBB/BBB | PREPARED | batch 0073 | source | next",
        ),
    ]
    report = build_report(
        _manifest(),
        _exclusions(),
        _step_status(),
        comments,
        [],
        main_sha="cafebabe",
        now=datetime(2026, 10, 1, 8, 1, tzinfo=timezone.utc),
        lease_hours=2.0,
    )
    assert report["summary"]["token"]["state"] == "STALLED"
    assert report["summary"]["token"]["stale"] is True
    assert "Worker 3" in report["token_comment_body"]


def test_recent_ci_keeps_token_active():
    comments = [
        _comment(
            1,
            "2026-10-01T06:00:00Z",
            "GLOBAL INTEGRATION TOKEN now advances to Worker 2 / AAA / reserved batch 0067.",
        ),
        _comment(
            2,
            "2026-10-01T07:50:00Z",
            "WORKER 2 | HEJFE-AAAAAAAAAAAAAAAA/AAA | CI | batch 0067 | exact-head gates running | next",
        ),
        _comment(
            3,
            "2026-10-01T07:00:00Z",
            "WORKER 3 | HEJFE-BBBBBBBBBBBBBBBB/BBB | PREPARED | batch 0073 | source | next",
        ),
    ]
    report = build_report(
        _manifest(),
        _exclusions(),
        _step_status(),
        comments,
        [],
        main_sha="cafebabe",
        now=datetime(2026, 10, 1, 8, 30, tzinfo=timezone.utc),
        lease_hours=2.0,
    )
    assert report["summary"]["token"]["state"] == "ACTIVE"
    assert report["summary"]["token"]["stale"] is False
    assert report["token_comment_body"] is None


def test_issue_comment_cannot_falsely_mark_event_resolved():
    comments = [
        _comment(
            1,
            "2026-10-01T06:00:00Z",
            "WORKER 1 | HEJFE-AAAAAAAAAAAAAAAA/AAA | MERGED | batch 0066 | claimed merged | next",
        )
    ]
    report = build_report(
        _manifest(),
        _exclusions(),
        _step_status(),
        comments,
        [],
        main_sha="cafebabe",
        now=datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc),
    )
    assert report["events"]["HEJFE-AAAAAAAAAAAAAAAA"]["state"] != "RESOLVED"
