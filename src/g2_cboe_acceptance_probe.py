from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

TOKEN_URL = "https://id.livevol.com/connect/token"
API_BASE = "https://api.livevol.com/v1/live/allaccess"
SAMPLE_DATE = "2011-03-21"
SAMPLE_SYMBOL = "JNPR"
POINTS_PER_HISTORICAL_REQUEST = 15
TOTAL_PROBE_POINTS = 2 * POINTS_PER_HISTORICAL_REQUEST

EQUITY_REQUIRED_FIELDS = {
    "timestamp",
    "underlying_trade_price",
    "underlying_trade_size",
    "bid",
    "ask",
    "bid_size",
    "ask_size",
}
OPTION_REQUIRED_FIELDS = {
    "timestamp",
    "security",
    "root",
    "expiry",
    "strike",
    "option_type",
    "option_trade_price",
    "option_trade_size",
}


@dataclass(frozen=True)
class ProbeRequest:
    name: str
    url: str
    required_fields: frozenset[str]


def build_probe_requests() -> list[ProbeRequest]:
    equity_params = urllib.parse.urlencode(
        {
            "condition_id": "",
            "quote_condition_id": "",
            "trade_condition_id": "",
            "mode": "ALL_QUOTES",
            "start_sequence_number": 0,
            "exchange_id": "",
            "limit": 100,
            "order_by_time": "ASC",
            "min_time": "09:30:00.000",
            "max_time": "16:00:00.000",
            "date": SAMPLE_DATE,
            "symbol": SAMPLE_SYMBOL,
        }
    )
    option_params = urllib.parse.urlencode(
        {
            "symbol": SAMPLE_SYMBOL,
            "root": "",
            "expiry": "",
            "strike": "",
            "option_type": "",
            "min_time": "09:30:00.000",
            "max_time": "16:00:00.000",
            "seq_no": 0,
            "exchange_id": "",
            "condition_id": "",
            "limit": 100,
            "min_size": "",
            "max_size": "",
            "min_price": "",
            "max_price": "",
            "date": SAMPLE_DATE,
        }
    )
    return [
        ProbeRequest(
            name="equity_trades_and_quotes",
            url=f"{API_BASE}/time-and-sales/trades-and-quotes?{equity_params}",
            required_fields=frozenset(EQUITY_REQUIRED_FIELDS),
        ),
        ProbeRequest(
            name="option_trades",
            url=f"{API_BASE}/time-and-sales/option-trades?{option_params}",
            required_fields=frozenset(OPTION_REQUIRED_FIELDS),
        ),
    ]


def _token(client_id: str, client_secret: str) -> str:
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("ascii"),
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = str(payload.get("access_token", "")).strip()
    if not token:
        raise RuntimeError("Cboe token response did not include access_token")
    return token


def _get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    raise ValueError("unexpected Cboe response shape")


def assess_probe_response(name: str, payload: Any, required_fields: set[str] | frozenset[str]) -> dict:
    rows = _extract_rows(payload)
    if not rows:
        return {
            "name": name,
            "row_count": 0,
            "required_fields": sorted(required_fields),
            "observed_required_fields": [],
            "missing_required_fields": sorted(required_fields),
            "accepted": False,
            "reason": "historical response contained no rows",
        }

    observed = set().union(*(row.keys() for row in rows))
    missing = set(required_fields) - observed
    populated = {
        field
        for field in required_fields
        if any(row.get(field) not in (None, "") for row in rows)
    }
    missing_populated = set(required_fields) - populated
    accepted = not missing and not missing_populated
    return {
        "name": name,
        "row_count": len(rows),
        "required_fields": sorted(required_fields),
        "observed_required_fields": sorted(set(required_fields) & observed),
        "populated_required_fields": sorted(populated),
        "missing_required_fields": sorted(missing),
        "unpopulated_required_fields": sorted(missing_populated),
        "accepted": accepted,
        "reason": "required historical fields populated" if accepted else "required historical fields missing or null",
    }


def dry_run_manifest() -> dict:
    requests = build_probe_requests()
    return {
        "schema_version": "1",
        "purpose": (
            "Two-request Cboe All Access historical acceptance probe for G2_CHAMPION_MINIMUM. "
            "Dry-run by default; no subscription signup, purchase, or bulk acquisition."
        ),
        "sample_date": SAMPLE_DATE,
        "sample_symbol": SAMPLE_SYMBOL,
        "historical_points_per_request": POINTS_PER_HISTORICAL_REQUEST,
        "total_probe_points": TOTAL_PROBE_POINTS,
        "requests": [
            {"name": r.name, "url": r.url, "required_fields": sorted(r.required_fields)}
            for r in requests
        ],
        "execute_requires": ["CBOE_CLIENT_ID", "CBOE_CLIENT_SECRET"],
        "acceptance_rule": "both historical responses contain rows and every required canonical input field is populated",
    }


def execute_probe(client_id: str, client_secret: str) -> dict:
    access_token = _token(client_id, client_secret)
    assessments = []
    for request in build_probe_requests():
        payload = _get_json(request.url, access_token)
        assessments.append(
            assess_probe_response(request.name, payload, request.required_fields)
        )
    accepted = all(item["accepted"] for item in assessments)
    return {
        "schema_version": "1",
        "sample_date": SAMPLE_DATE,
        "sample_symbol": SAMPLE_SYMBOL,
        "total_probe_points": TOTAL_PROBE_POINTS,
        "accepted": accepted,
        "assessments": assessments,
        "note": (
            "Passing this probe proves only historical field availability for the sample. "
            "It does not establish subscription license terms, pagination completeness, or G2 coverage."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or describe the minimal Cboe All Access G2 acceptance probe.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()

    if args.execute:
        client_id = os.environ.get("CBOE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("CBOE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise SystemExit("CBOE_CLIENT_ID and CBOE_CLIENT_SECRET are required for --execute")
        result = execute_probe(client_id, client_secret)
    else:
        result = dry_run_manifest()

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        from pathlib import Path

        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
