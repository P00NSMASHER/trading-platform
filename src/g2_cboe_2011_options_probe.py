from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any

TOKEN_URL = "https://id.livevol.com/connect/token"
API_BASE = "https://api.livevol.com/v1/live/allaccess"

PROBE_DATE = "2011-03-21"
PROBE_UNDERLYING = "JNPR"

REFERENCE_POINTS = 1
TRADE_POINTS = 15
QUOTE_POINTS = 15
MAX_PROBE_REQUESTS = 3
MAX_PROBE_POINTS = REFERENCE_POINTS + TRADE_POINTS + QUOTE_POINTS

REFERENCE_REQUIRED_FIELDS = {"root", "expiry", "strike", "type"}
TRADE_REQUIRED_FIELDS = {
    "timestamp",
    "security",
    "root",
    "expiry",
    "strike",
    "option_type",
    "option_trade_price",
    "option_trade_size",
    "exchange_id",
    "condition_id",
    "seq_no",
}
QUOTE_REQUIRED_FIELDS = {
    "timestamp",
    "exchange_id",
    "condition_id",
    "seq_no",
    "nbbo_bid",
    "nbbo_ask",
    "nbbo_bid_size",
    "nbbo_ask_size",
}

REFERENCE_DOC = (
    "https://api.livevol.com/v1/docs/Help/Api"
    "?apiId=GET-allaccess-reference-options_date_symbol"
)
TRADE_DOC = (
    "https://api.livevol.com/v1/docs/Help/Api/"
    "GET-allaccess-time-and-sales-option-trades_symbol_root_expiry_strike_option_type_"
    "min_time_max_time_seq_no_exchange_id_condition_id_limit_min_size_max_size_min_price_"
    "max_price_date?apiGroupName=allaccess"
)
QUOTE_DOC = (
    "https://api.livevol.com/v1/docs/Help/Api/"
    "GET-allaccess-time-and-sales-quotes_start_sequence_number_exchange_id_condition_id_"
    "limit_order_by_time_min_time_max_time_date_symbol"
)


def _reference_url() -> str:
    query = urllib.parse.urlencode({"date": PROBE_DATE, "symbol": PROBE_UNDERLYING})
    return f"{API_BASE}/reference/options?{query}"


def _trade_url() -> str:
    query = urllib.parse.urlencode(
        {
            "symbol": PROBE_UNDERLYING,
            "root": "",
            "expiry": "",
            "strike": "",
            "option_type": "",
            "min_time": "00:00:00.000",
            "max_time": "23:59:59.999",
            "seq_no": 0,
            "exchange_id": "",
            "condition_id": "",
            "limit": 100,
            "min_size": "",
            "max_size": "",
            "min_price": "",
            "max_price": "",
            "date": PROBE_DATE,
        }
    )
    return f"{API_BASE}/time-and-sales/option-trades?{query}"


def _quote_url(security: str) -> str:
    security = security.strip()
    if not security:
        raise ValueError("security must be nonblank")
    query = urllib.parse.urlencode(
        {
            "start_sequence_number": 0,
            "exchange_id": "",
            "condition_id": "",
            "limit": 100,
            "order_by_time": "ASC",
            "min_time": "00:00:00.000",
            "max_time": "23:59:59.999",
            "date": PROBE_DATE,
            "symbol": security,
        }
    )
    return f"{API_BASE}/time-and-sales/quotes?{query}"


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
    raise ValueError("unexpected Cboe response shape")


def _assess_rows(
    name: str,
    payload: Any,
    required_fields: set[str],
) -> dict[str, Any]:
    rows = _extract_rows(payload)
    if not rows:
        return {
            "name": name,
            "row_count": 0,
            "required_fields": sorted(required_fields),
            "populated_required_fields": [],
            "unpopulated_required_fields": sorted(required_fields),
            "accepted": False,
            "reason": "historical response contained no rows",
        }

    populated = {
        field
        for field in required_fields
        if any(row.get(field) not in (None, "") for row in rows)
    }
    missing = required_fields - populated
    return {
        "name": name,
        "row_count": len(rows),
        "required_fields": sorted(required_fields),
        "populated_required_fields": sorted(populated),
        "unpopulated_required_fields": sorted(missing),
        "accepted": not missing,
        "reason": (
            "required historical fields populated"
            if not missing
            else "required historical fields missing or null"
        ),
    }


def _osi_symbol(row: dict[str, Any]) -> str:
    root = str(row.get("root") or "").strip().upper()
    expiry = str(row.get("expiry") or "").strip()
    option_type = str(row.get("type") or row.get("option_type") or "").strip().upper()
    strike = row.get("strike")

    if not root or len(expiry) != 10 or option_type not in {"C", "P"}:
        raise ValueError("reference row lacks root/expiry/type needed for OSI")
    try:
        year, month, day = expiry.split("-")
        scaled = Decimal(str(strike)) * Decimal("1000")
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise ValueError("invalid historical option reference row") from exc
    if scaled != scaled.to_integral_value():
        raise ValueError("strike cannot be represented in OSI thousandths")
    strike_int = int(scaled)
    if strike_int < 0 or strike_int > 99_999_999:
        raise ValueError("strike outside OSI range")
    return f"{root}{year[2:]}{month}{day}{option_type}{strike_int:08d}"


def _first_reference_security(payload: Any) -> str | None:
    for row in _extract_rows(payload):
        try:
            return _osi_symbol(row)
        except ValueError:
            continue
    return None


def _token(client_id: str, client_secret: str) -> str:
    credentials = base64.b64encode(
        f"{client_id}:{client_secret}".encode("utf-8")
    ).decode("ascii")
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
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Cboe token response did not contain access_token")
    return token


def _get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def dry_run_manifest() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "purpose": (
            "Bounded runtime probe for the unresolved 2011 Cboe OPRA discrepancy. "
            "Public All Access endpoint documentation advertises historical option trades "
            "and quotes from 2003, while written vendor guidance used by the canonical "
            "bulk planner places DataShop OPRA-related coverage at 2012+. This probe tests "
            "one frozen 2011 underlying/date without changing the canonical planning floor."
        ),
        "probe": {
            "date": PROBE_DATE,
            "underlying_symbol": PROBE_UNDERLYING,
        },
        "requests": [
            {
                "name": "historical_reference_options",
                "url": _reference_url(),
                "points": REFERENCE_POINTS,
                "required_fields": sorted(REFERENCE_REQUIRED_FIELDS),
            },
            {
                "name": "historical_option_trades",
                "url": _trade_url(),
                "points": TRADE_POINTS,
                "required_fields": sorted(TRADE_REQUIRED_FIELDS),
            },
            {
                "name": "historical_option_quotes",
                "url": "derived from first valid OSI contract returned by reference/options",
                "points": QUOTE_POINTS,
                "required_fields": sorted(QUOTE_REQUIRED_FIELDS),
            },
        ],
        "max_probe_requests": MAX_PROBE_REQUESTS,
        "max_probe_points": MAX_PROBE_POINTS,
        "execute_requires": [
            "CBOE_CLIENT_ID",
            "CBOE_CLIENT_SECRET",
            "--ack-trial-active",
        ],
        "docs": {
            "reference_options": REFERENCE_DOC,
            "option_trades": TRADE_DOC,
            "option_quotes": QUOTE_DOC,
        },
        "fail_closed": {
            "does_not_change_vendor_confirmed_2012_floor": True,
            "does_not_promote_g2_coverage": True,
            "does_not_establish_license_or_retention_rights": True,
            "does_not_prove_full_2011_date_or_contract_completeness": True,
        },
        "g2_coverage_change": 0,
    }


def execute_probe(client_id: str, client_secret: str) -> dict[str, Any]:
    token = _token(client_id, client_secret)
    assessments: list[dict[str, Any]] = []
    requests_executed = 0
    points_consumed = 0

    reference_payload = _get_json(_reference_url(), token)
    requests_executed += 1
    points_consumed += REFERENCE_POINTS
    reference_assessment = _assess_rows(
        "historical_reference_options",
        reference_payload,
        REFERENCE_REQUIRED_FIELDS,
    )
    assessments.append(reference_assessment)

    trade_payload = _get_json(_trade_url(), token)
    requests_executed += 1
    points_consumed += TRADE_POINTS
    trade_assessment = _assess_rows(
        "historical_option_trades",
        trade_payload,
        TRADE_REQUIRED_FIELDS,
    )
    assessments.append(trade_assessment)

    security = _first_reference_security(reference_payload)
    if reference_assessment["accepted"] and security:
        quote_payload = _get_json(_quote_url(security), token)
        requests_executed += 1
        points_consumed += QUOTE_POINTS
        assessments.append(
            _assess_rows(
                "historical_option_quotes",
                quote_payload,
                QUOTE_REQUIRED_FIELDS,
            )
        )
    else:
        assessments.append(
            {
                "name": "historical_option_quotes",
                "row_count": 0,
                "required_fields": sorted(QUOTE_REQUIRED_FIELDS),
                "populated_required_fields": [],
                "unpopulated_required_fields": sorted(QUOTE_REQUIRED_FIELDS),
                "accepted": False,
                "reason": (
                    "quote request not executed because reference/options did not return "
                    "an accepted contract that could be converted to OSI"
                ),
            }
        )

    accepted = all(item["accepted"] for item in assessments)
    return {
        "schema_version": "1",
        "probe": {
            "date": PROBE_DATE,
            "underlying_symbol": PROBE_UNDERLYING,
            "derived_option_security": security,
        },
        "requests_executed": requests_executed,
        "points_consumed": points_consumed,
        "max_probe_points": MAX_PROBE_POINTS,
        "accepted": accepted,
        "assessments": assessments,
        "interpretation": (
            "A pass proves only that this entitlement returns the required 2011 reference, "
            "trade, and NBBO quote fields for this sample. It does not change the canonical "
            "2012 vendor floor, establish retention/license rights, prove complete pagination "
            "or contract coverage, or promote any G2 row."
        ),
        "g2_coverage_change": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run or execute the bounded Cboe 2011 OPRA entitlement probe."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack-trial-active", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()

    if not args.execute:
        result = dry_run_manifest()
    else:
        if not args.ack_trial_active:
            raise SystemExit("--execute requires --ack-trial-active")
        client_id = os.environ.get("CBOE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("CBOE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise SystemExit("CBOE_CLIENT_ID and CBOE_CLIENT_SECRET are required")
        result = execute_probe(client_id, client_secret)

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
