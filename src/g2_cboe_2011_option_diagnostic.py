from __future__ import annotations

import argparse
import json
import os
import urllib.parse
from typing import Any

import g2_cboe_acceptance_probe as base

SAMPLE_DATE = "2011-03-21"
SAMPLE_UNDERLYING = "JNPR"
PAGE_LIMIT = 100


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


def dry_run_manifest() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "purpose": (
            "Diagnostic-only 2011 Cboe All Access probe used to reconcile current API "
            "documentation with the vendor-confirmed 2012 OPRA planning floor."
        ),
        "sample_date": SAMPLE_DATE,
        "sample_underlying": SAMPLE_UNDERLYING,
        "option_trade_request": option_trade_url(),
        "derived_quote_request": {
            "endpoint": "time-and-sales/quotes",
            "date": SAMPLE_DATE,
            "symbol_source": "first nonblank security returned by option-trades",
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
    trade_payload = base._get_json(option_trade_url(), token)
    trade_assessment = base.assess_probe_response(
        "2011_option_trades",
        trade_payload,
        base.OPTION_TRADE_REQUIRED_FIELDS,
    )
    requests_executed = 1
    security = base._first_option_security(trade_payload)

    if trade_assessment["accepted"] and security:
        quote_payload = base._get_json(option_quote_url(security), token)
        quote_assessment = base.assess_probe_response(
            "2011_option_quotes",
            quote_payload,
            base.OPTION_QUOTE_REQUIRED_FIELDS,
        )
        requests_executed += 1
    else:
        quote_assessment = {
            "name": "2011_option_quotes",
            "row_count": 0,
            "accepted": False,
            "reason": (
                "quote request not executed because 2011 option-trades did not return "
                "an accepted row with a nonblank OSI security"
            ),
        }

    return {
        "schema_version": "1",
        "sample_date": SAMPLE_DATE,
        "sample_underlying": SAMPLE_UNDERLYING,
        "derived_option_security": security,
        "requests_executed": requests_executed,
        "trade_assessment": trade_assessment,
        "quote_assessment": quote_assessment,
        "diagnostic_passed": trade_assessment["accepted"] and quote_assessment["accepted"],
        "diagnostic_only": True,
        "changes_vendor_confirmed_floor": False,
        "coverage_claimed": False,
        "g2_coverage_change": 0,
        "note": (
            "A pass proves only that this 2011 sample is reachable with the active "
            "entitlement. It does not prove retention rights, full 2011 coverage, "
            "pagination completeness, or canonical G2 coverage."
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
