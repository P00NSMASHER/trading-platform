import json
from pathlib import Path

import pytest

import g2_lseg_option_time_and_sales as option_ts


def _manifest():
    return {
        "schema_version": "1",
        "trade_date": "2015-02-12",
        "historical_symbol": "ACHC",
        "summary": {
            "historical_contract_set_ready_for_time_and_sales": True,
        },
        "contracts": [
            {
                "source_ric": "ACHCC201505000.U",
                "historical_symbol": "ACHC",
                "trade_date": "2015-02-12",
                "historical_date_evidence": True,
                "validation_status": "historical_chain_candidate",
            },
            {
                "source_ric": "ACHCO201505000.U",
                "historical_symbol": "ACHC",
                "trade_date": "2015-02-12",
                "historical_date_evidence": True,
                "validation_status": "historical_chain_candidate",
            },
            {
                "source_ric": "ACHCC201506000.U",
                "historical_symbol": "ACHC",
                "trade_date": "2015-02-12",
                "historical_date_evidence": False,
                "validation_status": "search_candidate_requires_historical_confirmation",
            },
        ],
    }


def test_validated_contract_rics_excludes_search_only_contracts():
    symbol, trade_date, rics = option_ts.validated_contract_rics(_manifest())

    assert symbol == "ACHC"
    assert trade_date == "2015-02-12"
    assert rics == [
        "ACHCC201505000.U",
        "ACHCO201505000.U",
    ]


def test_search_only_manifest_fails_closed():
    payload = _manifest()
    payload["summary"]["historical_contract_set_ready_for_time_and_sales"] = False

    with pytest.raises(ValueError, match="historical-chain evidence"):
        option_ts.validated_contract_rics(payload)


def test_contract_identity_drift_fails_closed():
    payload = _manifest()
    payload["contracts"][0]["historical_symbol"] = "ALNY"

    with pytest.raises(ValueError, match="does not match manifest symbol"):
        option_ts.validated_contract_rics(payload)

    payload = _manifest()
    payload["contracts"][0]["trade_date"] = "2015-02-13"
    with pytest.raises(ValueError, match="trade_date drift"):
        option_ts.validated_contract_rics(payload)


def test_instrument_limit_is_fail_closed():
    payload = {
        "schema_version": "1",
        "trade_date": "2015-02-12",
        "historical_symbol": "ACHC",
        "summary": {
            "historical_contract_set_ready_for_time_and_sales": True,
        },
        "contracts": [
            {
                "source_ric": f"ACHCC{i:08d}.U",
                "historical_symbol": "ACHC",
                "trade_date": "2015-02-12",
                "historical_date_evidence": True,
                "validation_status": "historical_chain_candidate",
            }
            for i in range(option_ts.MAX_LSEG_CONTRACTS_PER_EXTRACTION)
        ],
    }

    with pytest.raises(ValueError, match="30000-instrument"):
        option_ts.validated_contract_rics(payload)


def test_extract_is_resumable_and_bound_to_manifest_hash(tmp_path: Path):
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps(_manifest()), encoding="utf-8")
    output = tmp_path / "option.csv.gz"
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

    first = option_ts.extract_contract_time_and_sales(
        FakeClient(),
        contract_manifest_path=contract,
        output_path=output,
    )
    second = option_ts.extract_contract_time_and_sales(
        FakeClient(),
        contract_manifest_path=contract,
        output_path=output,
    )

    assert first["status"] == "downloaded_pending_content_validation"
    assert first["contract_count"] == 2
    assert first["validation_promoted"] is False
    assert first["g2_coverage_change"] == 0
    assert second["status"] == "skipped_existing_download"
    assert len(calls) == 1

    receipt = json.loads(
        Path(first["receipt_path"]).read_text(encoding="utf-8")
    )
    assert receipt["contract_manifest_sha256"] == option_ts.sha256_file(contract)
    assert receipt["contract_rics"] == [
        "ACHCC201505000.U",
        "ACHCO201505000.U",
    ]

    # Any change to the validated contract manifest invalidates resumability.
    changed = _manifest()
    changed["contracts"].append(
        {
            "source_ric": "ACHCC201507000.U",
            "historical_symbol": "ACHC",
            "trade_date": "2015-02-12",
            "historical_date_evidence": True,
            "validation_status": "historical_chain_candidate",
        }
    )
    contract.write_text(json.dumps(changed), encoding="utf-8")

    third = option_ts.extract_contract_time_and_sales(
        FakeClient(),
        contract_manifest_path=contract,
        output_path=output,
    )
    assert third["status"] == "downloaded_pending_content_validation"
    assert third["contract_count"] == 3
    assert len(calls) == 2


def test_missing_output_or_corrupt_receipt_forces_retry(tmp_path: Path):
    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps(_manifest()), encoding="utf-8")
    output = tmp_path / "option.csv.gz"
    calls = []

    class FakeClient:
        def extract_time_and_sales(self, rics, trade_date, output_path):
            calls.append(1)
            output_path.write_bytes(b"licensed-option-bytes")
            return {"job_id": "job"}

    first = option_ts.extract_contract_time_and_sales(
        FakeClient(),
        contract_manifest_path=contract,
        output_path=output,
    )
    Path(first["receipt_path"]).write_text("{", encoding="utf-8")

    retry = option_ts.extract_contract_time_and_sales(
        FakeClient(),
        contract_manifest_path=contract,
        output_path=output,
    )
    assert retry["status"] == "downloaded_pending_content_validation"
    assert len(calls) == 2
