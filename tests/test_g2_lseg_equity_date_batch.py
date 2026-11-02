import json
from pathlib import Path

import pytest

import g2_lseg_equity_date_batch as equity_batch


def test_equity_date_batch_covers_full_frozen_queue_without_network():
    first = equity_batch.build_equity_date_batch(start=0, limit=5)
    last = equity_batch.build_equity_date_batch(start=413, limit=5)

    assert first["queue_size"] == 414
    assert first["selected_count"] == 5
    assert first["next_start"] == 5
    assert first["network_execution_enabled"] is False
    assert first["g2_coverage_change"] == 0
    assert all(task["candidate_rics"] for task in first["tasks"])

    assert last["queue_size"] == 414
    assert last["selected_count"] == 1
    assert last["next_start"] == 414

    with pytest.raises(ValueError):
        equity_batch.build_equity_date_batch(start=-1)
    with pytest.raises(ValueError):
        equity_batch.build_equity_date_batch(limit=0)


def test_execute_equity_date_batch_normalizes_and_resumes(tmp_path, monkeypatch):
    extraction_calls = []
    normalization_calls = []

    class FakeClient:
        def extract_time_and_sales(self, candidate_rics, trade_date, output_path):
            extraction_calls.append((candidate_rics, trade_date, output_path))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"private-licensed-test-bytes")
            return {
                "job_id": "job-1",
                "output_path": str(output_path),
                "size_bytes": output_path.stat().st_size,
            }

    def fake_normalize(input_path, *, lane, trade_date, output_dir):
        normalization_calls.append((input_path, lane, trade_date, output_dir))
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "summary.json"
        summary_path.write_text(
            json.dumps({"trade_date": trade_date, "g2_coverage_change": 0}),
            encoding="utf-8",
        )
        return {
            "summary_path": str(summary_path),
            "normalized_rows": {"equity_trade": 3, "equity_quote": 4},
            "rejected_rows": 0,
        }

    monkeypatch.setattr(equity_batch.delivery, "normalize_delivery", fake_normalize)

    batch = {
        "tasks": [
            {
                "trade_date": "2011-03-21",
                "historical_symbols": ["JNPR", "VMW"],
                "candidate_rics": ["JNPR.K", "VMW.N"],
            }
        ]
    }
    output_dir = tmp_path / "licensed-equity"

    first = equity_batch.execute_equity_date_batch(
        FakeClient(),
        batch,
        output_dir,
    )
    second = equity_batch.execute_equity_date_batch(
        FakeClient(),
        batch,
        output_dir,
    )

    assert first["network_dates_completed"] == 1
    assert first["skipped_existing_dates"] == 0
    assert first["entitlement_promotions"] == 0
    assert first["g2_coverage_change"] == 0
    assert first["receipts"][0]["normalized_rows"] == {
        "equity_trade": 3,
        "equity_quote": 4,
    }

    assert second["network_dates_completed"] == 0
    assert second["skipped_existing_dates"] == 1
    assert len(extraction_calls) == 1
    assert len(normalization_calls) == 1

    completion = output_dir / "receipts/lseg_equity_2011-03-21.json"
    payload = json.loads(completion.read_text(encoding="utf-8"))
    assert payload["requires_entitlement_binding"] is True
    assert payload["requires_production_content_preflight"] is True
    assert payload["g2_coverage_change"] == 0

    # If the candidate set changes, the old receipt must not suppress reacquisition.
    changed = {
        "tasks": [
            {
                "trade_date": "2011-03-21",
                "historical_symbols": ["JNPR", "VMW"],
                "candidate_rics": ["JNPR.K"],
            }
        ]
    }
    third = equity_batch.execute_equity_date_batch(
        FakeClient(),
        changed,
        output_dir,
    )
    assert third["network_dates_completed"] == 1
    assert len(extraction_calls) == 2


def test_live_equity_date_batch_is_hard_capped(tmp_path):
    class FakeClient:
        pass

    batch = {
        "tasks": [
            {
                "trade_date": f"2011-03-{day:02d}",
                "historical_symbols": ["X"],
                "candidate_rics": ["X.N"],
            }
            for day in range(1, equity_batch.MAX_LIVE_EQUITY_DATES + 2)
        ]
    }
    with pytest.raises(ValueError, match="capped"):
        equity_batch.execute_equity_date_batch(
            FakeClient(),
            batch,
            tmp_path / "private",
        )


def test_corrupt_completion_receipt_does_not_skip(tmp_path, monkeypatch):
    calls = []

    class FakeClient:
        def extract_time_and_sales(self, candidate_rics, trade_date, output_path):
            calls.append(trade_date)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"x")
            return {"job_id": "job", "output_path": str(output_path), "size_bytes": 1}

    def fake_normalize(input_path, *, lane, trade_date, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "summary.json"
        summary_path.write_text("{}", encoding="utf-8")
        return {
            "summary_path": str(summary_path),
            "normalized_rows": {"equity_trade": 1, "equity_quote": 1},
            "rejected_rows": 0,
        }

    monkeypatch.setattr(equity_batch.delivery, "normalize_delivery", fake_normalize)
    batch = {
        "tasks": [
            {
                "trade_date": "2011-03-21",
                "historical_symbols": ["JNPR"],
                "candidate_rics": ["JNPR.K"],
            }
        ]
    }
    out = tmp_path / "private"
    equity_batch.execute_equity_date_batch(FakeClient(), batch, out)
    receipt = out / "receipts/lseg_equity_2011-03-21.json"
    receipt.write_text("{", encoding="utf-8")

    result = equity_batch.execute_equity_date_batch(FakeClient(), batch, out)
    assert result["network_dates_completed"] == 1
    assert len(calls) == 2
