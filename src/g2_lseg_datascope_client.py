from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import g2_lseg_datascope_execution_plan as execution
import g2_lseg_request_manifest as manifest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://selectapi.datascope.lseg.com/RestApi/v1"
USERNAME_ENV = "LSEG_DATASCOPE_USERNAME"
PASSWORD_ENV = "LSEG_DATASCOPE_PASSWORD"

PRIVATE_REPO_PREFIXES = (
    Path("data/private"),
    Path("data/licensed"),
    Path("data/vendor"),
    Path("data/incoming"),
    Path("data/staging"),
    Path("private_runtime"),
)


def authentication_payload(username: str, password: str) -> dict:
    if not username or not password:
        raise ValueError("LSEG username/password must both be non-empty")
    return {"Credentials": {"Username": username, "Password": password}}


def time_and_sales_payload(candidate_rics: list[str], trade_date: str) -> dict:
    if not candidate_rics:
        raise ValueError("at least one candidate RIC is required")
    date.fromisoformat(trade_date)
    return {
        "ExtractionRequest": {
            "@odata.type": (
                "#DataScope.Select.Api.Extractions.ExtractionRequests."
                "TickHistoryTimeAndSalesExtractionRequest"
            ),
            "ContentFieldNames": execution.TIME_AND_SALES_FIELDS,
            "IdentifierList": {
                "@odata.type": (
                    "#DataScope.Select.Api.Extractions.ExtractionRequests."
                    "InstrumentIdentifierList"
                ),
                "InstrumentIdentifiers": [
                    {"Identifier": ric, "IdentifierType": "Ric"}
                    for ric in candidate_rics
                ],
                "ValidationOptions": {"AllowHistoricalInstruments": True},
                "UseUserPreferencesForValidationOptions": False,
            },
            "Condition": {
                "ApplyCorrectionsAndCancellations": False,
                "DisplaySourceRIC": False,
                "DateRangeTimeZone": "Local Exchange Time Zone",
                "QueryStartDate": f"{trade_date}T00:00:00.000000000",
                "QueryEndDate": f"{trade_date}T23:59:59.999999999",
                "ReportDateRangeType": "Range",
                "TimeRangeMode": "Inclusive",
                "SortBy": "SingleByTimestamp",
                "MessageTimeStampIn": "LocalExchangeTime",
            },
        }
    }


def futures_options_search_payload(underlying_ric: str, trade_date: str) -> dict:
    if not underlying_ric:
        raise ValueError("underlying RIC is required")
    date.fromisoformat(trade_date)
    return {
        "SearchRequest": {
            "FuturesAndOptionsType": "Options",
            "UnderlyingRic": underlying_ric,
            "ExpirationDate": {
                "@odata.type": "#DataScope.Select.Api.Search.DateValueComparison",
                "ComparisonOperator": "GreaterThanEquals",
                "Value": trade_date,
            },
        }
    }


def historical_chain_payload(chain_ric: str, trade_date: str) -> dict:
    if not chain_ric:
        raise ValueError("chain RIC is required")
    date.fromisoformat(trade_date)
    return {
        "Request": {
            "ChainRics": [chain_ric],
            "Range": {
                "Start": f"{trade_date}T00:00:00.000Z",
                "End": f"{trade_date}T23:59:59.999Z",
            },
        }
    }


def ensure_private_output_path(path: Path, *, repo_root: Path = ROOT) -> Path:
    resolved = path.expanduser().resolve()
    root = repo_root.resolve()

    if not resolved.is_relative_to(root):
        return resolved

    relative = resolved.relative_to(root)
    if any(relative == prefix or prefix in relative.parents for prefix in PRIVATE_REPO_PREFIXES):
        return resolved

    raise ValueError(
        "licensed LSEG output inside this repository must be under an ignored/private "
        "path such as data/private/ or private_runtime/"
    )


class DataScopeClient:
    def __init__(
        self,
        username: str,
        password: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        opener: Callable = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
        poll_seconds: float = 10.0,
    ) -> None:
        if not username or not password:
            raise ValueError("LSEG credentials must be supplied")
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self._open = opener
        self._sleep = sleeper
        self.poll_seconds = poll_seconds
        self.token: str | None = None

    def _request(
        self,
        url_or_path: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        token_required: bool = True,
        accept_gzip: bool = False,
    ):
        url = (
            url_or_path
            if url_or_path.startswith(("http://", "https://"))
            else f"{self.base_url}/{url_or_path.lstrip('/')}"
        )
        headers = {
            "Prefer": "respond-async",
            "Content-Type": "application/json",
        }
        if accept_gzip:
            headers["Accept-Encoding"] = "gzip"
        if token_required:
            if not self.token:
                self.authenticate()
            headers["Authorization"] = f"Token {self.token}"

        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(url, data=data, headers=headers, method=method)
        try:
            return self._open(request, timeout=60)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"LSEG DataScope request failed: HTTP {exc.code}: {detail[:1000]}"
            ) from exc

    @staticmethod
    def _status(response) -> int:
        if hasattr(response, "status"):
            return int(response.status)
        return int(response.getcode())

    @staticmethod
    def _json(response) -> dict:
        raw = response.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def authenticate(self) -> str:
        response = self._request(
            "/Authentication/RequestToken",
            method="POST",
            payload=authentication_payload(self.username, self.password),
            token_required=False,
        )
        body = self._json(response)
        token = str(body.get("value") or "")
        if not token:
            raise RuntimeError("LSEG authentication response did not contain a token")
        self.token = token
        return token

    def futures_options_search(
        self,
        underlying_ric: str,
        trade_date: str,
    ) -> list[dict]:
        payload = futures_options_search_payload(underlying_ric, trade_date)
        response = self._request(
            "/Search/FuturesAndOptionsSearch",
            method="POST",
            payload=payload,
        )
        body = self._json(response)
        values = list(body.get("value") or [])
        next_link = body.get("@odata.nextlink") or body.get("@odata.nextLink")

        while next_link:
            response = self._request(
                str(next_link),
                method="POST",
                payload=payload,
            )
            body = self._json(response)
            values.extend(body.get("value") or [])
            next_link = body.get("@odata.nextlink") or body.get("@odata.nextLink")
        return values

    def historical_chain_resolution(
        self,
        chain_ric: str,
        trade_date: str,
    ) -> dict:
        response = self._request(
            "/Search/HistoricalChainResolution",
            method="POST",
            payload=historical_chain_payload(chain_ric, trade_date),
        )
        return self._json(response)

    def submit_time_and_sales(
        self,
        candidate_rics: list[str],
        trade_date: str,
    ) -> tuple[str, list[str]]:
        response = self._request(
            "/Extractions/ExtractRaw",
            method="POST",
            payload=time_and_sales_payload(candidate_rics, trade_date),
        )
        status = self._status(response)
        location = response.headers.get("Location") or response.headers.get("location")
        body = self._json(response)

        if status == 200:
            job_id = str(body.get("JobId") or "")
            if not job_id:
                raise RuntimeError("completed extraction response did not contain JobId")
            return job_id, list(body.get("Notes") or [])

        if status != 202 or not location:
            raise RuntimeError(
                f"unexpected LSEG extraction response status={status} location={location!r}"
            )

        while True:
            self._sleep(self.poll_seconds)
            poll = self._request(str(location), method="GET")
            poll_status = self._status(poll)
            poll_body = self._json(poll)
            if poll_status == 202:
                continue
            if poll_status != 200:
                raise RuntimeError(f"unexpected LSEG poll status={poll_status}")
            job_id = str(poll_body.get("JobId") or "")
            if not job_id:
                raise RuntimeError("completed extraction poll did not contain JobId")
            return job_id, list(poll_body.get("Notes") or [])

    def download_job(self, job_id: str, output_path: Path) -> dict:
        if not job_id:
            raise ValueError("job_id is required")
        destination = ensure_private_output_path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        response = self._request(
            f"/Extractions/RawExtractionResults('{job_id}')/$value",
            method="GET",
            accept_gzip=True,
        )
        with destination.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=1024 * 1024)

        return {
            "job_id": job_id,
            "output_path": str(destination),
            "size_bytes": destination.stat().st_size,
            "content_type": response.headers.get("Content-Type"),
            "content_encoding": response.headers.get("Content-Encoding"),
        }

    def extract_time_and_sales(
        self,
        candidate_rics: list[str],
        trade_date: str,
        output_path: Path,
    ) -> dict:
        job_id, notes = self.submit_time_and_sales(candidate_rics, trade_date)
        receipt = self.download_job(job_id, output_path)
        receipt["trade_date"] = trade_date
        receipt["candidate_rics"] = list(candidate_rics)
        receipt["notes"] = notes
        return receipt


def _execution_plan() -> dict:
    base = manifest.build_plan(
        manifest._read_csv(ROOT / manifest.DEFAULT_MAPPING),
        manifest._read_csv(ROOT / manifest.DEFAULT_SECONDARY),
        manifest._read_csv(ROOT / manifest.DEFAULT_EVENT_MAPPING),
        manifest._read_csv(ROOT / manifest.DEFAULT_CORE),
        manifest._read_csv(ROOT / manifest.DEFAULT_OPTIONS),
    )
    return execution.build_execution_plan(base)


def _credentials_from_environment() -> tuple[str, str]:
    username = os.environ.get(USERNAME_ENV, "")
    password = os.environ.get(PASSWORD_ENV, "")
    if not username or not password:
        raise RuntimeError(
            f"set {USERNAME_ENV} and {PASSWORD_ENV} in the local/private environment; "
            "do not commit credentials to the repository"
        )
    return username, password


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Execute licensed LSEG DataScope requests into a private/local output path."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    equity = sub.add_parser("equity-day")
    equity.add_argument("--date", required=True)
    equity.add_argument("--output", type=Path, required=True)

    search = sub.add_parser("option-search")
    search.add_argument("--underlying-ric", required=True)
    search.add_argument("--date", required=True)
    search.add_argument("--output", type=Path, required=True)

    chain = sub.add_parser("historical-chain")
    chain.add_argument("--chain-ric", required=True)
    chain.add_argument("--date", required=True)
    chain.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    username, password = _credentials_from_environment()
    client = DataScopeClient(username, password)

    if args.command == "equity-day":
        plan = _execution_plan()
        batch = next(
            (row for row in plan["equity_date_batches"] if row["trade_date"] == args.date),
            None,
        )
        if batch is None:
            raise SystemExit(f"date {args.date} is not in the frozen G2 equity scope")
        receipt = client.extract_time_and_sales(
            list(batch["candidate_rics"]),
            args.date,
            args.output,
        )
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return

    destination = ensure_private_output_path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if args.command == "option-search":
        result = client.futures_options_search(args.underlying_ric, args.date)
    else:
        result = client.historical_chain_resolution(args.chain_ric, args.date)

    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output_path": str(destination)}, sort_keys=True))


if __name__ == "__main__":
    main()
