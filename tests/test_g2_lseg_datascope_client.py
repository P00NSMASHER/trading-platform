import io
import json
from pathlib import Path

import pytest

import g2_lseg_datascope_client as client


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"", *, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


def _json_response(payload, *, status=200, headers=None):
    return FakeResponse(
        json.dumps(payload).encode("utf-8"),
        status=status,
        headers=headers,
    )


def test_authentication_payload_is_minimal_and_rejects_missing_credentials():
    assert client.authentication_payload("user", "pass") == {
        "Credentials": {"Username": "user", "Password": "pass"}
    }
    with pytest.raises(ValueError):
        client.authentication_payload("", "pass")


def test_time_and_sales_payload_matches_historical_g2_contract():
    payload = client.time_and_sales_payload(["JNPR.O", "VMW.N"], "2011-03-21")
    request = payload["ExtractionRequest"]

    assert request["@odata.type"].endswith("TickHistoryTimeAndSalesExtractionRequest")
    assert request["ContentFieldNames"] == client.execution.TIME_AND_SALES_FIELDS
    assert request["IdentifierList"]["InstrumentIdentifiers"] == [
        {"Identifier": "JNPR.O", "IdentifierType": "Ric"},
        {"Identifier": "VMW.N", "IdentifierType": "Ric"},
    ]
    assert request["IdentifierList"]["ValidationOptions"]["AllowHistoricalInstruments"] is True
    assert request["Condition"]["QueryStartDate"] == "2011-03-21T00:00:00.000000000"
    assert request["Condition"]["QueryEndDate"] == "2011-03-21T23:59:59.999999999"


def test_option_search_payload_uses_one_exact_underlying_ric():
    payload = client.futures_options_search_payload("JNPR.O", "2011-03-21")
    search = payload["SearchRequest"]

    assert search["UnderlyingRic"] == "JNPR.O"
    assert search["FuturesAndOptionsType"] == "Options"
    assert search["ExpirationDate"]["Value"] == "2011-03-21"


def test_historical_chain_payload_is_date_scoped():
    payload = client.historical_chain_payload("0#JNPR*.U", "2011-03-21")
    request = payload["Request"]

    assert request["ChainRics"] == ["0#JNPR*.U"]
    assert request["Range"] == {
        "Start": "2011-03-21T00:00:00.000Z",
        "End": "2011-03-21T23:59:59.999Z",
    }


def test_private_output_enforcement_accepts_ignored_paths_and_external_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    allowed = repo / "data/private/lseg/day.csv.gz"
    assert client.ensure_private_output_path(allowed, repo_root=repo) == allowed.resolve()

    external = tmp_path / "licensed-out/day.csv.gz"
    assert client.ensure_private_output_path(external, repo_root=repo) == external.resolve()

    with pytest.raises(ValueError, match="ignored/private"):
        client.ensure_private_output_path(repo / "data/processed/day.csv.gz", repo_root=repo)


def test_authenticate_uses_injected_transport_without_leaking_credentials():
    requests = []

    def opener(request, timeout):
        requests.append(request)
        return _json_response({"value": "private-test-token"})

    ds = client.DataScopeClient(
        "alice",
        "secret",
        base_url="https://example.invalid/RestApi/v1",
        opener=opener,
        poll_seconds=0,
    )
    token = ds.authenticate()

    assert token == "private-test-token"
    assert ds.token == "private-test-token"
    assert len(requests) == 1
    assert requests[0].full_url.endswith("/Authentication/RequestToken")
    body = json.loads(requests[0].data.decode("utf-8"))
    assert body == {"Credentials": {"Username": "alice", "Password": "secret"}}


def test_submit_time_and_sales_handles_async_202_then_200():
    calls = []
    responses = [
        _json_response({"value": "token"}),
        _json_response(
            {},
            status=202,
            headers={"Location": "https://example.invalid/jobs/abc"},
        ),
        _json_response(
            {"JobId": "job-123", "Notes": ["ok"]},
            status=200,
        ),
    ]

    def opener(request, timeout):
        calls.append((request.method, request.full_url))
        return responses.pop(0)

    ds = client.DataScopeClient(
        "alice",
        "secret",
        base_url="https://example.invalid/RestApi/v1",
        opener=opener,
        sleeper=lambda _: None,
        poll_seconds=0,
    )
    job_id, notes = ds.submit_time_and_sales(["JNPR.O"], "2011-03-21")

    assert job_id == "job-123"
    assert notes == ["ok"]
    assert calls[0][1].endswith("/Authentication/RequestToken")
    assert calls[1][1].endswith("/Extractions/ExtractRaw")
    assert calls[2] == ("GET", "https://example.invalid/jobs/abc")


def test_futures_options_search_follows_paging():
    responses = [
        _json_response({"value": "token"}),
        _json_response(
            {
                "value": [{"Identifier": "OPT1"}],
                "@odata.nextlink": "https://example.invalid/page/2",
            }
        ),
        _json_response({"value": [{"Identifier": "OPT2"}]}),
    ]

    def opener(request, timeout):
        return responses.pop(0)

    ds = client.DataScopeClient(
        "alice",
        "secret",
        base_url="https://example.invalid/RestApi/v1",
        opener=opener,
        sleeper=lambda _: None,
        poll_seconds=0,
    )
    result = ds.futures_options_search("JNPR.O", "2011-03-21")
    assert result == [{"Identifier": "OPT1"}, {"Identifier": "OPT2"}]


def test_download_job_writes_only_to_private_destination(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(client, "ROOT", repo)

    responses = [
        _json_response({"value": "token"}),
        FakeResponse(
            b"licensed-bytes",
            status=200,
            headers={"Content-Type": "text/csv", "Content-Encoding": "gzip"},
        ),
    ]

    def opener(request, timeout):
        return responses.pop(0)

    ds = client.DataScopeClient(
        "alice",
        "secret",
        base_url="https://example.invalid/RestApi/v1",
        opener=opener,
        poll_seconds=0,
    )

    # Pass an external path because ensure_private_output_path's default root is
    # defined at function declaration; separate enforcement behavior is tested above.
    destination = tmp_path / "external-private" / "day.csv.gz"
    receipt = ds.download_job("job-123", destination)

    assert destination.read_bytes() == b"licensed-bytes"
    assert receipt["job_id"] == "job-123"
    assert receipt["size_bytes"] == len(b"licensed-bytes")



def test_validation_batch_plan_is_exact_bounded_and_fail_closed():
    batch = client.build_validation_batch("equity", start=0, limit=3)

    assert batch["queue_size"] == 946
    assert batch["selected_count"] == 3
    assert batch["next_start"] == 3
    assert batch["network_execution_enabled"] is False
    assert all(row["historical_validation_required"] is True for row in batch["tasks"])

    option = client.build_validation_batch("option", start=945, limit=3)
    assert option["queue_size"] == 946
    assert option["selected_count"] == 1
    assert option["next_start"] == 946

    with pytest.raises(ValueError):
        client.build_validation_batch("bad-lane")
    with pytest.raises(ValueError):
        client.build_validation_batch("equity", start=-1)
    with pytest.raises(ValueError):
        client.build_validation_batch("equity", limit=0)


def test_execute_equity_validation_batch_is_resumable(tmp_path, monkeypatch):
    calls = []

    monkeypatch.setattr(
        client.historical_ric_validator,
        "validate_file",
        lambda path, trade_date: {
            "schema_version": "1",
            "input_receipt": {"path_name": Path(path).name},
            "results": [
                {
                    "trade_date": trade_date,
                    "historical_symbol": "JNPR",
                    "validation_status": "validated_single_candidate",
                    "selected_ric": "JNPR.O",
                }
            ],
        },
    )

    class FakeClient:
        def extract_time_and_sales(self, candidate_rics, trade_date, output_path):
            calls.append((candidate_rics, trade_date, output_path))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"licensed-test-bytes")
            return {
                "job_id": "job-1",
                "output_path": str(output_path),
                "size_bytes": len(b"licensed-test-bytes"),
            }

    batch = {
        "lane": "equity",
        "tasks": [
            {
                "trade_date": "2011-03-21",
                "historical_symbol": "JNPR",
                "candidate_rics": ["JNPR.O"],
            }
        ],
    }
    output_dir = tmp_path / "external-validation"
    first = client.execute_validation_batch(FakeClient(), batch, output_dir)
    second = client.execute_validation_batch(FakeClient(), batch, output_dir)

    assert first["network_tasks_completed"] == 1
    assert first["skipped_existing_outputs"] == 0
    assert first["validation_promotions"] == 0
    assert first["g2_coverage_change"] == 0
    assert first["receipts"][0]["identifier_validation_status"] == (
        "validated_single_candidate"
    )
    assert Path(first["receipts"][0]["identifier_validation_path"]).exists()
    assert second["network_tasks_completed"] == 0
    assert second["skipped_existing_outputs"] == 1
    assert len(calls) == 1
    receipt_path = output_dir / "2011-03-21_JNPR.receipt.json"
    assert receipt_path.exists()

    # A receipt from a different candidate-RIC set must be retried.
    receipt_path.write_text(
        json.dumps(
            {
                "trade_date": "2011-03-21",
                "historical_symbol": "JNPR",
                "candidate_rics": ["JNPR.OQ"],
            }
        ),
        encoding="utf-8",
    )
    candidate_changed = client.execute_validation_batch(
        FakeClient(), batch, output_dir
    )
    assert candidate_changed["network_tasks_completed"] == 1
    assert candidate_changed["skipped_existing_outputs"] == 0
    assert len(calls) == 2

    # A leftover raw file without a completion receipt must be retried, not skipped.
    receipt_path.unlink()
    third = client.execute_validation_batch(FakeClient(), batch, output_dir)
    assert third["network_tasks_completed"] == 1
    assert third["skipped_existing_outputs"] == 0
    assert len(calls) == 3


def test_option_chain_ric_derives_public_datascope_chain_shape():
    assert client.option_chain_ric("JNPR.O") == "0#JNPR*.U"
    assert client.option_chain_ric("ALSN.N") == "0#ALSN*.U"
    assert client.option_chain_ric("GORO.A") == "0#GORO*.U"
    assert client.option_chain_ric("0#SPX*.U") == "0#SPX*.U"
    with pytest.raises(ValueError):
        client.option_chain_ric("")


def test_execute_option_validation_batch_writes_search_and_historical_chain(tmp_path):
    search_calls = []
    chain_calls = []

    class FakeClient:
        def futures_options_search(self, ric, trade_date):
            search_calls.append((ric, trade_date))
            return [{"Identifier": f"{ric}-OPT"}]

        def historical_chain_resolution(self, chain_ric, trade_date):
            chain_calls.append((chain_ric, trade_date))
            return {
                "value": [
                    {
                        "Identifier": f"{chain_ric}-HIST",
                    }
                ]
            }

    batch = {
        "lane": "option",
        "tasks": [
            {
                "trade_date": "2011-03-21",
                "historical_symbol": "JNPR",
                "candidate_rics": ["JNPR.O", "JNPR.OQ"],
            }
        ],
    }
    output_dir = tmp_path / "external-option-validation"
    result = client.execute_validation_batch(FakeClient(), batch, output_dir)

    assert result["network_tasks_completed"] == 1
    assert result["validation_promotions"] == 0
    assert result["g2_coverage_change"] == 0
    assert result["receipts"][0]["search_discovered_contract_count"] == 2
    assert result["receipts"][0]["historical_chain_query_count"] == 1
    assert search_calls == [
        ("JNPR.O", "2011-03-21"),
        ("JNPR.OQ", "2011-03-21"),
    ]
    assert chain_calls == [
        ("0#JNPR*.U", "2011-03-21"),
    ]

    payload_path = output_dir / "2011-03-21_JNPR.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2"
    assert payload["historical_chain_resolution_completed"] is True
    assert len(payload["discoveries"]) == 2
    assert payload["discoveries"][0]["option_chain_ric"] == "0#JNPR*.U"
    assert "historical_chain_result" in payload["discoveries"][0]

    second = client.execute_validation_batch(FakeClient(), batch, output_dir)
    assert second["network_tasks_completed"] == 0
    assert second["skipped_existing_outputs"] == 1
    assert len(search_calls) == 2
    assert len(chain_calls) == 1

    # A legacy search-only result with matching task identity is still incomplete.
    payload_path.write_text(
        json.dumps(
            {
                "trade_date": "2011-03-21",
                "historical_symbol": "JNPR",
                "candidate_rics": ["JNPR.O", "JNPR.OQ"],
                "discoveries": [],
            }
        ),
        encoding="utf-8",
    )
    legacy = client.execute_validation_batch(FakeClient(), batch, output_dir)
    assert legacy["network_tasks_completed"] == 1
    assert legacy["skipped_existing_outputs"] == 0
    assert len(search_calls) == 4
    assert len(chain_calls) == 2

    # Corrupt/incomplete JSON is also not accepted as a completion marker.
    payload_path.write_text("{", encoding="utf-8")
    third = client.execute_validation_batch(FakeClient(), batch, output_dir)
    assert third["network_tasks_completed"] == 1
    assert len(search_calls) == 6
    assert len(chain_calls) == 3

def test_live_validation_batch_hard_caps_network_tasks(tmp_path):
    class FakeClient:
        pass

    batch = {
        "lane": "equity",
        "tasks": [
            {
                "trade_date": "2011-03-21",
                "historical_symbol": f"S{i}",
                "candidate_rics": [f"S{i}.N"],
            }
            for i in range(client.MAX_LIVE_VALIDATION_TASKS + 1)
        ],
    }

    with pytest.raises(ValueError, match="capped"):
        client.execute_validation_batch(
            FakeClient(),
            batch,
            tmp_path / "external-validation",
        )
