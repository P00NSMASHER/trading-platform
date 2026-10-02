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

EQUITY_SAMPLE_DATE = "2011-03-21"
EQUITY_SAMPLE_SYMBOL = "JNPR"
OPTION_SAMPLE_DATE = "2012-01-03"
OPTION_SAMPLE_SYMBOL = "AF"

POINTS_PER_HISTORICAL_REQUEST = 15
MAX_PROBE_REQUESTS = 3
MAX_PROBE_POINTS = MAX_PROBE_REQUESTS * POINTS_PER_HISTORICAL_REQUEST

EQUITY_REQUIRED_FIELDS = {
    "timestamp",
    "underlying_trade_price",
    "underlying_trade_size",
    "bid",
    "ask",
    "bid_size",
    "ask_size",
}
OPTION_TRADE_REQUIRED_FIELDS = {
    "timestamp",
    "security",
    "root",
    "expiry",
    "strike",
    "option_type",
    "option_trade_price",
    "option_trade_size",
}
OPTION_QUOTE_REQUIRED_FIELDS = {
    "timestamp",
    "nbbo_bid",
    "nbbo_ask",
    "nbbo_bid_size",
    "nbbo_ask_size",
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
            "date": EQUITY_SAMPLE_DATE,
            "symbol": EQUITY_SAMPLE_SYMBOL,
        }
    )
    option_params = urllib.parse.urlencode(
        {
            "symbol": OPTION_SAMPLE_SYMBOL,
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
            "date": OPTION_SAMPLE_DATE,
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
            required_fields=frozenset(OPTION_TRADE_REQUIRED_FIELDS),
        ),
    ]


def build_option_quote_request(option_security: str) -> ProbeRequest:
    security = option_security.strip()
    if not security:
        raise ValueError("option_security must be nonblank")
    quote_params = urllib.parse.urlencode(
        {
            "start_sequence_number": 0,
            "exchange_id": "",
            "condition_id": "",
            "limit": 100,
            "order_by_time": "ASC",
            "min_time": "09:30:00.000",
            "max_time": "16:00:00.000",
            "date": OPTION_SAMPLE_DATE,
            "symbol": security,
        }
    )
    return ProbeRequest(
        name="option_quotes",
        url=f"{API_BASE}/time-and-sales/quotes?{quote_params}",
        required_fields=frozenset(OPTION_QUOTE_REQUIRED_FIELDS),
    )


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


def assess_probe_response(
    name: str,
    payload: Any,
    required_fields: set[str] | frozenset[str],
) -> dict:
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
        "reason": (
            "required historical fields populated"
            if accepted
            else "required historical fields missing or null"
        ),
    }


def _first_option_security(payload: Any) -> str | None:
    for row in _extract_rows(payload):
        security = str(row.get("security", "")).strip()
        if security:
            return security
    return None


def _blocked_quote_assessment(reason: str) -> dict:
    return {
        "name": "option_quotes",
        "row_count": 0,
        "required_fields": sorted(OPTION_QUOTE_REQUIRED_FIELDS),
        "observed_required_fields": [],
        "missing_required_fields": sorted(OPTION_QUOTE_REQUIRED_FIELDS),
        "accepted": False,
        "reason": reason,
    }


def dry_run_manifest() -> dict:
    requests = build_probe_requests()
    return {
        "schema_version": "2",
        "purpose": (
            "Three-request maximum Cboe All Access historical acceptance probe for G2. "
            "It separately tests 2011 equity TAQ, 2012 option trades, and one strict "
            "historical option-quote stream derived from an OSI contract returned by the "
            "option-trade response. Dry-run by default; no subscription signup, purchase, "
            "or bulk acquisition."
        ),
        "equity_sample": {
            "date": EQUITY_SAMPLE_DATE,
            "symbol": EQUITY_SAMPLE_SYMBOL,
        },
        "option_sample": {
            "date": OPTION_SAMPLE_DATE,
            "underlying_symbol": OPTION_SAMPLE_SYMBOL,
        },
        "historical_points_per_request": POINTS_PER_HISTORICAL_REQUEST,
        "max_probe_requests": MAX_PROBE_REQUESTS,
        "max_probe_points": MAX_PROBE_POINTS,
        "requests": [
            {"name": r.name, "url": r.url, "required_fields": sorted(r.required_fields)}
            for r in requests
        ],
        "derived_quote_request": {
            "name": "option_quotes",
            "date": OPTION_SAMPLE_DATE,
            "symbol_source": "first nonblank security returned by option_trades",
            "endpoint": "time-and-sales/quotes",
            "limit": 100,
            "required_fields": sorted(OPTION_QUOTE_REQUIRED_FIELDS),
        },
        "execute_requires": ["CBOE_CLIENT_ID", "CBOE_CLIENT_SECRET"],
        "acceptance_rule": (
            "2011 equity TAQ, 2012 option trades, and the derived historical option quote "
            "response must each contain rows with every required probe field populated"
        ),
        "scope_limit": (
            "A pass proves only sample historical field availability. It does not establish "
            "license terms, full-date coverage, contract enumeration completeness, pagination "
            "completeness, rate-limit feasibility, or G2 coverage."
        ),
    }


def execute_probe(client_id: str, client_secret: str) -> dict:
    access_token = _token(client_id, client_secret)
    assessments = []
    requests_executed = 0

    initial_requests = build_probe_requests()

    equity_payload = _get_json(initial_requests[0].url, access_token)
    requests_executed += 1
    assessments.append(
        assess_probe_response(
            initial_requests[0].name,
            equity_payload,
            initial_requests[0].required_fields,
        )
    )

    option_trade_payload = _get_json(initial_requests[1].url, access_token)
    requests_executed += 1
    option_trade_assessment = assess_probe_response(
        initial_requests[1].name,
        option_trade_payload,
        initial_requests[1].required_fields,
    )
    assessments.append(option_trade_assessment)

    option_security = _first_option_security(option_trade_payload)
    if option_trade_assessment["accepted"] and option_security:
        quote_request = build_option_quote_request(option_security)
        quote_payload = _get_json(quote_request.url, access_token)
        requests_executed += 1
        assessments.append(
            assess_probe_response(
                quote_request.name,
                quote_payload,
                quote_request.required_fields,
            )
        )
    else:
        assessments.append(
            _blocked_quote_assessment(
                "option quote request not executed because the historical option-trade "
                "sample did not produce an accepted row with a nonblank OSI security"
            )
        )

    accepted = all(item["accepted"] for item in assessments)
    return {
        "schema_version": "2",
        "equity_sample": {
            "date": EQUITY_SAMPLE_DATE,
            "symbol": EQUITY_SAMPLE_SYMBOL,
        },
        "option_sample": {
            "date": OPTION_SAMPLE_DATE,
            "underlying_symbol": OPTION_SAMPLE_SYMBOL,
            "derived_option_security": option_security,
        },
        "requests_executed": requests_executed,
        "points_consumed": requests_executed * POINTS_PER_HISTORICAL_REQUEST,
        "max_probe_points": MAX_PROBE_POINTS,
        "accepted": accepted,
        "assessments": assessments,
        "note": (
            "Passing this probe proves only historical field availability for the samples. "
            "It does not establish subscription/license terms, full-date coverage, contract "
            "enumeration, pagination completeness, rate-limit feasibility, or G2 coverage."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run or describe the minimal Cboe All Access G2 acceptance probe."
    )
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
