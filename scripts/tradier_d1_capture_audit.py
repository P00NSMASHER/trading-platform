"""Independent, read-only audit of existing private Tradier D1 capture receipts.

A delayed GitHub diagnostic does not establish that the Cloudflare collector failed.
No brokerage calls, D1 writes, quote-level reads, or new scheduled jobs.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]
# PK observed_minute bounds the read to one regular session. No raw quotes.
QUERY = (
    "SELECT observed_minute, state, underlyings_expected, underlyings_valid, "
    "options_planned, options_valid, options_aligned, quotes_accepted, coverage_state "
    "FROM collector_runs_v18 WHERE observed_minute >= ? AND observed_minute < ? "
    "ORDER BY observed_minute ASC LIMIT 391"
)
MAX_RESPONSE_BYTES = 1_000_000
GITHUB_DIAGNOSTICS = ("not_checked", "success", "delayed_postmarket", "failure")


class AuditError(Exception):
    """Sanitized error: no credentials, provider payloads, or private quotes."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def d1_bound_iso(value: datetime) -> str:
    """D1 stores .000Z; textual range comparisons need identical precision."""
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def aware_datetime(text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise AuditError("invalid_aware_timestamp") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise AuditError("timestamp_requires_explicit_timezone")
    return value.astimezone(timezone.utc)


def regular_window(session_date: date, as_of: datetime) -> tuple[datetime, datetime]:
    if session_date.weekday() >= 5:
        raise AuditError("weekend_not_a_regular_session")
    open_time = datetime.combine(session_date, time(9, 30), ET).astimezone(timezone.utc)
    close_time = datetime.combine(session_date, time(16, 0), ET).astimezone(timezone.utc)
    cutoff = (as_of.astimezone(timezone.utc) - timedelta(minutes=2)).replace(second=0, microsecond=0)
    return open_time, max(open_time, min(close_time, cutoff))


def expected_minutes(start: datetime, end: datetime) -> list[str]:
    return [utc_iso(start + timedelta(minutes=i)) for i in range(int((end-start).total_seconds() // 60))]


def complete_capture(row: dict) -> bool:
    def integer(name: str) -> int | None:
        v = row.get(name)
        return v if type(v) is int and v >= 0 else None
    underlyings_expected = integer("underlyings_expected")
    underlyings_valid = integer("underlyings_valid")
    options_planned = integer("options_planned")
    options_valid = integer("options_valid")
    options_aligned = integer("options_aligned")
    accepted = integer("quotes_accepted")
    return (
        row.get("coverage_state") == "complete_verified_option_snapshot"
        and isinstance(row.get("state"), str)
        and row["state"].startswith("captured_")
        and underlyings_expected is not None and underlyings_expected > 0
        and underlyings_valid == underlyings_expected
        and options_planned is not None and options_planned > 0
        and options_valid == options_planned
        and options_aligned == options_planned
        and accepted == underlyings_valid + options_valid
    )


def assess(records: list[dict], session_date: date, as_of: datetime,
           *, github_diagnostic: str = "not_checked", origin: str = "offline_fixture") -> dict:
    if github_diagnostic not in GITHUB_DIAGNOSTICS:
        raise AuditError("invalid_github_diagnostic")
    start, end = regular_window(session_date, as_of)
    slots = expected_minutes(start, end)
    expected = set(slots)
    seen: dict[str, dict] = {}
    invalid = 0
    if not isinstance(records, list):
        raise AuditError("invalid_D1_result")
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("observed_minute"), str):
            invalid += 1
            continue
        try:
            raw = aware_datetime(row["observed_minute"])
            key = utc_iso(raw)
        except AuditError:
            invalid += 1
            continue
        if raw.second != 0 or raw.microsecond != 0 or key not in expected or key in seen:
            invalid += 1
            continue
        seen[key] = row
    complete = sum(complete_capture(row) for row in seen.values())
    missing = len(expected) - len(seen)
    partial = len(seen) - complete
    if invalid:
        status = "INVALID_EVIDENCE"
    elif not expected:
        status = "SESSION_NOT_DUE"
    elif missing == 0 and partial == 0:
        status = "COMPLETE_CAPTURE_OBSERVED"
    elif len(seen) == 0:
        status = "NO_CAPTURE_RECORDS"
    else:
        status = "INCOMPLETE_CAPTURE_OBSERVED"
    return {
        "schema_version": "1",
        "source": "collector_runs_v18",
        "evidence_origin": origin,
        "session_date_et": session_date.isoformat(),
        "as_of_utc": utc_iso(as_of),
        "window_start_utc": utc_iso(start),
        "window_end_exclusive_utc": utc_iso(end),
        "expected_minutes": len(slots),
        "observed_minutes": len(seen),
        "complete_minutes": complete,
        "partial_minutes": partial,
        "missing_minutes": missing,
        "invalid_rows": invalid,
        "capture_status": status,
        "github_diagnostic": github_diagnostic,
        "github_diagnostic_changes_capture_status": False,
        "market_calendar_caveat": "regular_weekday_window_only; holidays/early_closes_not_verified",
        "provider_connectivity_now": "UNVERIFIED",
        "profitable_strategy": "UNVERIFIED",
    }


def parse_d1_response(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise AuditError("D1_query_unverified")
    blocks = payload.get("result")
    if not isinstance(blocks, list) or len(blocks) != 1:
        raise AuditError("invalid_D1_response_shape")
    block = blocks[0]
    if (not isinstance(block, dict) or block.get("success") is False
            or not isinstance(block.get("results"), list)):
        raise AuditError("invalid_D1_result")
    return block["results"]


def cloudflare_rows(start: datetime, end: datetime, *, account: str, database: str,
                    token: str, opener=None) -> list[dict]:
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account):
        raise AuditError("invalid_Cloudflare_account_id")
    if not re.fullmatch(r"[a-fA-F0-9-]{36}", database):
        raise AuditError("invalid_D1_database_id")
    if not token:
        raise AuditError("Cloudflare_API_token_not_configured")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{database}/query"
    request = Request(url, data=json.dumps({"sql": QUERY, "params": [d1_bound_iso(start), d1_bound_iso(end)]}).encode("utf-8"),
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
    try:
        transport = opener if opener is not None else build_opener(NoRedirect())
        with transport.open(request, timeout=15) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise AuditError(f"Cloudflare_D1_HTTP_{exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise AuditError("Cloudflare_D1_transport_unavailable") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise AuditError("D1_response_too_large")
    try:
        return parse_d1_response(json.loads(raw))
    except (ValueError, UnicodeError):
        raise AuditError("malformed_D1_response") from None


def default_database_id() -> str:
    try:
        config = json.loads((ROOT / "workers/wrangler.tradier.json").read_text(encoding="utf-8"))
        bindings = [b for b in config["d1_databases"] if b.get("binding") == "DB"]
        if len(bindings) != 1:
            raise ValueError("ambiguous binding")
        return bindings[0]["database_id"]
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        raise AuditError("configured_D1_database_id_unavailable") from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only D1 market-session capture auditor")
    parser.add_argument("--session-date", required=True, help="NY market date YYYY-MM-DD")
    parser.add_argument("--as-of", help="Explicit timezone-aware timestamp for replay")
    parser.add_argument("--github-diagnostic", choices=GITHUB_DIAGNOSTICS, default="not_checked")
    parser.add_argument("--fixture-json", type=Path, help="Offline D1 response JSON; never proof of live access")
    args = parser.parse_args(argv)
    origin = "offline_fixture" if args.fixture_json else "cloudflare_d1_api"
    try:
        session_date = date.fromisoformat(args.session_date)
        as_of = aware_datetime(args.as_of) if args.as_of else datetime.now(timezone.utc)
        start, end = regular_window(session_date, as_of)
        if args.fixture_json:
            data = args.fixture_json.read_bytes()
            if len(data) > MAX_RESPONSE_BYTES:
                raise AuditError("D1_response_too_large")
            rows = parse_d1_response(json.loads(data))
        elif start == end:
            rows = []
        else:
            rows = cloudflare_rows(start, end,
                account=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
                database=os.environ.get("TRADIER_D1_DATABASE_ID") or default_database_id(),
                token=os.environ.get("CLOUDFLARE_API_TOKEN", ""))
        report = assess(rows, session_date, as_of, github_diagnostic=args.github_diagnostic, origin=origin)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["capture_status"] == "COMPLETE_CAPTURE_OBSERVED" else 2
    except (AuditError, OSError, ValueError, json.JSONDecodeError) as exc:
        code = str(exc) if isinstance(exc, AuditError) else "invalid_input_or_response"
        print(json.dumps({"schema_version":"1", "capture_status":"UNVERIFIED",
                          "evidence_origin":origin,"github_diagnostic":args.github_diagnostic,
                          "github_diagnostic_changes_capture_status":False,
                          "provider_connectivity_now":"UNVERIFIED","error_code":code}, sort_keys=True))
        return 3


if __name__ == "__main__":
    sys.exit(main())
