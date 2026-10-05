from __future__ import annotations

import argparse
import json
import os
import urllib.parse
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import g2_cboe_acceptance_probe as base

SAMPLE_DATE = "2011-03-21"
SAMPLE_UNDERLYING = "JNPR"
PAGE_LIMIT = 100
MAX_REQUESTS = 3
REFERENCE_POINTS = 1
HISTORICAL_TIME_AND_SALES_POINTS = 15
MAX_POINTS = REFERENCE_POINTS + (2 * HISTORICAL_TIME_AND_SALES_POINTS)
REFERENCE_REQUIRED_FIELDS = {"root", "expiry", "strike", "type"}


def reference_options_url() -> str:
    params = urllib.parse.urlencode(
        {"date": SAMPLE_DATE, "symbol": SAMPLE_UNDERLYING}
    )
    return f"{base.API_BASE}/reference/options?{params}"


def option_trade_url() -> str:
    params = urllib.parse.urlencode(
        {
            "symbol": SAMPLE_UNDERLYING,
            "root": "",
            "expiry": "",
            "strike": "",
            "option_type": "",
            "min_time": "00:00:00.000",
            "max_time": "23:59:59.999",
            "seq_no": 0,
            "exchange_id": "",
            "condition_id": "",
            "limit": PAGE_LIMIT,
            "min_size": "",
            "max_size": "",
            "min_price": "",
            "max_price": "",
            "date": SAMPLE_DATE,
        }
    )
    return f"{base.API_BASE}/time-and-sales/option-trades?{params}"


def option_quote_url(security: str) -> str:
    security = security.strip()
    if not security:
        raise ValueError("security must be nonblank")
    params = urllib.parse.urlencode(
        {
            "start_sequence_number": 0,
            "exchange_id": "",
            "condition_id": "",
            "limit": PAGE_LIMIT,
            "order_by_time": "ASC",
            "min_time": "00:00:00.000",
            "max_time": "23:59:59.999",
            "date": SAMPLE_DATE,
            "symbol": security,
        }
    )
    return f"{base.API_BASE}/time-and-sales/quotes?{params}"


def _osi_from_reference_row(row: dict[str, Any]) -> str | None:
    root = str(row.get("root") or "").strip().upper()
    expiry = str(row.get("expiry") or "").strip()
    option_type = str(row.get("type") or row.get("option_type") or "").strip().upper()
    strike = row.get("strike")
    if not root or not expiry or option_type not in {"C", "P"} or strike in (None, ""):
        return None
    try:
        expiry_date = date.fromisoformat(expiry)
        scaled = Decimal(str(strike)) * Decimal("1000")
    except (ValueError, InvalidOperation):
        return None
    if scaled != scaled.to_integral_value():
        return None
    strike_int = int(scaled)
    if strike_int < 0 or strike_int > 99_999_999:
        return None
    return (
        f"{root}{expiry_date.strftime('%y%m%d')}{option_type}"
        f"{strike_int:08d}"
    )


def _first_reference_security(payload: Any) -> str | None:
    for row in base._extract_rows(payload):
        security = _osi_from_reference_row(row)
        if security:
            return security
    return None


def _blocked_quote_assessment(reason: str) -> dict[str, Any]:
    return {
        "name": "2011_option_quotes",
        "row_count": 0,
        "required_fields": sorted(base.OPTION_QUOTE_REQUIRED_FIELDS),
        "observed_required_fields": [],
        "missing_required_fields": sorted(base.OPTION_QUOTE_REQUIRED_FIELDS),
        "accepted": False,
        "reason": reason,
    }


def dry_run_manifest() -> dict[str, Any]:
    return {
        "schema_version": "2",
        "purpose": (
            "Diagnostic-only 2011 Cboe All Access probe used to reconcile current API "
            "documentation with the vendor-confirmed 2012 OPRA planning floor."
        ),
        "sample_date": SAMPLE_DATE,
        "sample_underlying": SAMPLE_UNDERLYING,
        "reference_options_request": reference_options_url(),
        "option_trade_request": option_trade_url(),
        "derived_quote_request": {
            "endpoint": "time-and-sales/quotes",
            "date": SAMPLE_DATE,
            "symbol_source": (
                "first valid OSI contract from reference/options, falling back to "
                "the first nonblank security returned by option-trades"
            ),
        },
        "max_requests": MAX_REQUESTS,
        "max_points": MAX_POINTS,
        "point_model": {
            "reference/options": REFERENCE_POINTS,
            "historical_option_trades": HISTORICAL_TIME_AND_SALES_POINTS,
            "historical_option_quotes": HISTORICAL_TIME_AND_SALES_POINTS,
        },
        "execute_requires": [
            "CBOE_CLIENT_ID",
            "CBOE_CLIENT_SECRET",
            "--ack-trial-active",
        ],
        "diagnostic_only": True,
        "changes_vendor_confirmed_floor": False,
        "coverage_claimed": False,
        "g2_coverage_change": 0,
    }


def execute_diagnostic(client_id: str, client_secret: str) -> dict[str, Any]:
    token = base._token(client_id, client_secret)

    reference_payload = base._get_json(reference_options_url(), token)
    reference_assessment = base.assess_probe_response(
        "2011_option_reference",
        reference_payload,
        REFERENCE_REQUIRED_FIELDS,
    )

    trade_payload = base._get_json(option_trade_url(), token)
    trade_assessment = base.assess_probe_response(
        "2011_option_trades",
        trade_payload,
        base.OPTION_TRADE_REQUIRED_FIELDS,
    )
    requests_executed = 2
    points_executed = REFERENCE_POINTS + HISTORICAL_TIME_AND_SALES_POINTS

    security = _first_reference_security(reference_payload)
    security_source = "reference/options" if security else None
    if not security:
        security = base._first_option_security(trade_payload)
        if security:
            security_source = "option-trades"

    if security:
        quote_payload = base._get_json(option_quote_url(security), token)
        quote_assessment = base.assess_probe_response(
            "2011_option_quotes",
            quote_payload,
            base.OPTION_QUOTE_REQUIRED_FIELDS,
        )
        requests_executed += 1
        points_executed += HISTORICAL_TIME_AND_SALES_POINTS
    else:
        quote_assessment = _blocked_quote_assessment(
            "quote request not executed because neither 2011 reference/options nor "
            "2011 option-trades produced an OSI option security"
        )

    if requests_executed > MAX_REQUESTS:
        raise RuntimeError("2011 diagnostic exceeded bounded request limit")
    if points_executed > MAX_POINTS:
        raise RuntimeError("2011 diagnostic exceeded bounded point limit")

    diagnostic_passed = (
        reference_assessment["accepted"]
        and trade_assessment["accepted"]
        and quote_assessment["accepted"]
    )
    return {
        "schema_version": "2",
        "sample_date": SAMPLE_DATE,
        "sample_underlying": SAMPLE_UNDERLYING,
        "derived_option_security": security,
        "derived_option_security_source": security_source,
        "requests_executed": requests_executed,
        "points_executed": points_executed,
        "max_points": MAX_POINTS,
        "reference_assessment": reference_assessment,
        "trade_assessment": trade_assessment,
        "quote_assessment": quote_assessment,
        "diagnostic_passed": diagnostic_passed,
        "diagnostic_only": True,
        "changes_vendor_confirmed_floor": False,
        "coverage_claimed": False,
        "g2_coverage_change": 0,
        "note": (
            "A pass proves only that this 2011 sample is reachable with the active "
            "entitlement, including dated contract enumeration plus strict trade/NBBO "
            "fields. It does not prove retention rights, full 2011 coverage, pagination "
            "completeness, or canonical G2 coverage."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Describe or execute a bounded diagnostic-only Cboe 2011 OPRA probe."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack-trial-active", action="store_true")
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
        result = execute_diagnostic(client_id, client_secret)

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
