import json
from pathlib import Path

import pytest

import g2_lseg_option_batch_pipeline as pipeline


def _combined_payload(*, complete: bool = True, with_contracts: bool = True):
    chain_constituents = (
        [
            {"Identifier": "ACHCC201505000.U"},
            {"Identifier": "ACHCO201505000.U"},
        ]
        if with_contracts
        else []
    )
    payload = {
        "schema_version": "2",
        "trade_date": "2015-02-12",
        "historical_symbol": "ACHC",
        "candidate_rics": ["ACHC.O", "ACHC.OQ"],
        "discoveries": [
            {
                "underlying_ric": "ACHC.O",
                "option_chain_ric": "0#ACHC*.U",
                "search_results": [{"Identifier": "ACHCC201505000.U"}],
                "historical_chain_result": {
                    "value": [
                        {
                            "Identifier": "0#ACHC*.U",
                            "Constituents": chain_constituents,
                        }
                    ]
                },
            },
            {
                "underlying_ric": "ACHC.OQ",
                "option_chain_ric": "0#ACHC*.U",
                "search_results": [],
                "historical_chain_result": {
                    "value": [
                        {
                            "Identifier": "0#ACHC*.U",
                            "Constituents": chain_constituents,
                        }
                    ]
                },
            },
        ],
    }
    if complete:
        payload["historical_chain_resolution_completed"] = True
    return payload


def _write_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_select_batch_is_bounded_and_deterministic(tmp_path: Path):
    input_dir = tmp_path / "inputs"
    _write_payload(input_dir / "b.json", _combined_payload())
    _write_payload(input_dir / "a.json", _combined_payload())
    _write_payload(input_dir / "ignored.receipt.json", {"not": "a task"})

    batch = pipeline.select_batch(input_dir, start=0, limit=1)

    assert batch["queue_size"] == 2
    assert batch["selected_count"] == 1
    assert batch["next_start"] == 1
    assert batch["files"][0].name == "a.json"

    with pytest.raises(ValueError, match="between 1 and 25"):
        pipeline.select_batch(input_dir, limit=26)


def test_dry_run_materializes_contract_and_records_bad_batch(tmp_path: Path):
    input_dir = tmp_path / "inputs"
    _write_payload(input_dir / "good.json", _combined_payload())
    _write_payload(
        input_dir / "legacy.json",
        _combined_payload(complete=False),
    )
    batch = pipeline.select_batch(input_dir, limit=2)

    out = pipeline.process_batch(
        batch,
        contract_dir=tmp_path / "contracts",
    )

    assert out["selected_count"] == 2
    assert out["contract_manifests_written"] == 1
    assert out["contracts_ready_for_time_and_sales"] == 1
    assert out["validation_failures"] == 1
    assert out["network_downloads_completed"] == 0
    assert out["g2_coverage_change"] == 0

    good = next(row for row in out["results"] if row["input_path_name"] == "good.json")
    bad = next(row for row in out["results"] if row["input_path_name"] == "legacy.json")
    assert good["status"] == "contract_ready_download_not_requested"
    assert Path(good["contract_path"]).exists()
    assert bad["status"] == "validation_failed"
    assert "HistoricalChainResolution" in bad["error"]


def test_historical_chain_with_no_contracts_is_not_downloaded(tmp_path: Path):
    input_dir = tmp_path / "inputs"
    _write_payload(
        input_dir / "empty-chain.json",
        _combined_payload(with_contracts=False),
    )
    batch = pipeline.select_batch(input_dir)

    out = pipeline.process_batch(
        batch,
        contract_dir=tmp_path / "contracts",
    )

    assert out["contract_manifests_written"] == 1
    assert out["contracts_ready_for_time_and_sales"] == 0
    assert out["results"][0]["status"] == "validated_no_historical_contracts"


def test_execute_downloads_uses_only_validated_contract_manifest_and_resumes(tmp_path: Path):
    input_dir = tmp_path / "inputs"
    _write_payload(input_dir / "good.json", _combined_payload())
    batch = pipeline.select_batch(input_dir)
    calls = []

    class FakeClient:
        def extract_time_and_sales(self, rics, trade_date, output_path):
            calls.append((list(rics), trade_date, output_path))
            output_path.write_bytes(b"licensed-option-bytes")
            return {
                "job_id": "job-1",
                "output_path": str(output_path),
                "size_bytes": len(b"licensed-option-bytes"),
            }

    first = pipeline.process_batch(
        batch,
        contract_dir=tmp_path / "contracts",
        download_dir=tmp_path / "downloads",
        client=FakeClient(),
    )
    second = pipeline.process_batch(
        batch,
        contract_dir=tmp_path / "contracts",
        download_dir=tmp_path / "downloads",
        client=FakeClient(),
    )

    assert first["network_downloads_completed"] == 1
    assert first["network_downloads_skipped_existing"] == 0
    assert second["network_downloads_completed"] == 0
    assert second["network_downloads_skipped_existing"] == 1
    assert len(calls) == 1
    assert calls[0][0] == [
        "ACHCC201505000.U",
        "ACHCO201505000.U",
    ]
    assert calls[0][1] == "2015-02-12"


def test_client_requires_download_dir(tmp_path: Path):
    input_dir = tmp_path / "inputs"
    _write_payload(input_dir / "good.json", _combined_payload())
    batch = pipeline.select_batch(input_dir)

    class FakeClient:
        pass

    with pytest.raises(ValueError, match="download_dir"):
        pipeline.process_batch(
            batch,
            contract_dir=tmp_path / "contracts",
            client=FakeClient(),
        )
