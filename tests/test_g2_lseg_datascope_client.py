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
