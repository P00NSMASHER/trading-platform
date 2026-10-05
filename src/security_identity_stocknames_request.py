from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path


SCHEMA_VERSION = "1"
DEFAULT_ACQUISITION_SUMMARY = Path(
    "data/processed/security_identity_real/security_identity_acquisition_summary.json"
)
DEFAULT_REQUEST_CSV = Path(
    "data/processed/security_identity_real/security_identity_stocknames_request.csv"
)
DEFAULT_REQUEST_SQL = Path(
    "data/processed/security_identity_real/security_identity_stocknames_request.sql"
)
DEFAULT_REQUEST_SUMMARY = Path(
    "data/processed/security_identity_real/security_identity_stocknames_request_summary.json"
)

REQUEST_FIELDS = [
    "permno",
    "gvkey",
    "historical_symbol",
    "request_count",
    "first_required_date",
    "last_required_date",
    "event_count",
    "event_ids",
]


class StocknamesRequestError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_acquisition_summary(path: Path = DEFAULT_ACQUISITION_SUMMARY) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1":
        raise StocknamesRequestError("acquisition summary schema_version must equal '1'")
    state = payload.get("state") or {}
    securities = payload.get("securities")
    if not isinstance(securities, list) or not securities:
        raise StocknamesRequestError("acquisition summary securities are empty")
    unresolved = int(state.get("unique_permno_date_requests", -1))
    unique_permnos = int(state.get("unique_permno_count", -1))
    ready = bool(state.get("ready_for_non_synthetic_market_join"))
    if unresolved <= 0 or unique_permnos <= 0 or ready:
        raise StocknamesRequestError(
            "stocknames acquisition request requires a non-ready unresolved identity state"
        )
    if unique_permnos != len(securities):
        raise StocknamesRequestError(
            "unique_permno_count does not match securities length"
        )
    return payload


def _normalize_security(raw: dict, index: int) -> dict[str, object]:
    permno = str(raw.get("permno") or "").strip()
    gvkey = str(raw.get("gvkey") or "").strip()
    symbol = str(raw.get("historical_symbol") or "").strip().upper()
    request_count = int(raw.get("request_count", 0) or 0)
    first_required_date = str(raw.get("first_required_date") or "").strip()
    last_required_date = str(raw.get("last_required_date") or "").strip()
    event_ids = list(raw.get("event_ids") or [])
    event_count = int(raw.get("event_count", 0) or 0)

    if not permno.isdigit() or int(permno) <= 0:
        raise StocknamesRequestError(f"security {index}: PERMNO must be positive digits")
    if not gvkey or not symbol:
        raise StocknamesRequestError(
            f"security {index}: GVKEY and historical_symbol are required"
        )
    if request_count <= 0 or event_count <= 0 or event_count != len(event_ids):
        raise StocknamesRequestError(
            f"security {index}: request_count/event_count/event_ids are inconsistent"
        )
    try:
        first = date.fromisoformat(first_required_date)
        last = date.fromisoformat(last_required_date)
    except ValueError as exc:
        raise StocknamesRequestError(
            f"security {index}: required-date bounds must be YYYY-MM-DD"
        ) from exc
    if last < first:
        raise StocknamesRequestError(
            f"security {index}: last_required_date precedes first_required_date"
        )
    if not all(str(event_id).strip() for event_id in event_ids):
        raise StocknamesRequestError(f"security {index}: event_ids contain blanks")

    return {
        "permno": permno,
        "gvkey": gvkey,
        "historical_symbol": symbol,
        "request_count": request_count,
        "first_required_date": first.isoformat(),
        "last_required_date": last.isoformat(),
        "event_count": event_count,
        "event_ids": sorted(str(event_id).strip() for event_id in event_ids),
    }


def build_request(summary: dict, *, source_sha256: str | None = None) -> tuple[list[dict[str, object]], dict]:
    state = summary.get("state") or {}
    raw_securities = summary.get("securities") or []
    securities = [
        _normalize_security(raw, index)
        for index, raw in enumerate(raw_securities, 1)
    ]
    securities.sort(key=lambda row: int(str(row["permno"])))

    permnos = [str(row["permno"]) for row in securities]
    symbols = [str(row["historical_symbol"]) for row in securities]
    if len(set(permnos)) != len(permnos):
        raise StocknamesRequestError("duplicate PERMNO in acquisition summary")
    if len(set(symbols)) != len(symbols):
        raise StocknamesRequestError("duplicate historical_symbol in acquisition summary")

    unresolved = int(state.get("unique_permno_date_requests", -1))
    summed = sum(int(row["request_count"]) for row in securities)
    if summed != unresolved:
        raise StocknamesRequestError(
            f"request_count sum mismatch: state={unresolved} computed={summed}"
        )
    unique_permnos = int(state.get("unique_permno_count", -1))
    if unique_permnos != len(securities):
        raise StocknamesRequestError(
            f"unique_permno_count mismatch: state={unique_permnos} computed={len(securities)}"
        )

    first_required_date = min(str(row["first_required_date"]) for row in securities)
    last_required_date = max(str(row["last_required_date"]) for row in securities)
    request_summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Minimum authorized CRSP-style stocknames acquisition plan for the unresolved "
            "G2 stable-security-identity gate."
        ),
        "research_use_only": True,
        "source_acquisition_summary": str(DEFAULT_ACQUISITION_SUMMARY),
        "source_acquisition_summary_sha256": source_sha256,
        "state": {
            "unresolved_permno_date_requests": unresolved,
            "unique_permno_count": len(securities),
            "first_required_date": first_required_date,
            "last_required_date": last_required_date,
            "expected_adapter_input_minimum_fields": [
                "permno",
                "ticker",
                "namedt",
                "nameenddt_or_nameendt",
            ],
        },
        "authorization_policy": {
            "requires_authorized_source": True,
            "acceptable_examples": [
                "CRSP/WRDS stocknames history",
                "equivalent licensed dated stable-ID security master",
            ],
            "public_or_unverified_mirror_may_not_close_gate": True,
            "current_ticker_substitution_prohibited": True,
            "authentication_or_entitlement_bypass_prohibited": True,
        },
    }
    return securities, request_summary


def render_csv(securities: list[dict[str, object]]) -> str:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=REQUEST_FIELDS, lineterminator="\n")
    writer.writeheader()
    for raw in securities:
        row = dict(raw)
        row["event_ids"] = ";".join(row["event_ids"])
        writer.writerow(row)
    return out.getvalue()


def _sql_quote(value: str) -> str:
    return value.replace("'", "''")


def render_sql(securities: list[dict[str, object]]) -> str:
    value_rows = []
    for row in securities:
        value_rows.append(
            "    ("
            + str(int(str(row["permno"])))
            + ", '"
            + _sql_quote(str(row["historical_symbol"]))
            + "', DATE '"
            + str(row["first_required_date"])
            + "', DATE '"
            + str(row["last_required_date"])
            + "')"
        )
    values = ",\n".join(value_rows)
    return (
        "-- Exact licensed-source request for the G2 stable-security-identity gate.\n"
        "-- Requires authorized access to CRSP/WRDS (or an equivalent licensed stable-ID master).\n"
        "-- This query contains no licensed data and does not bypass authentication or entitlement.\n"
        "WITH requested(permno, historical_symbol, min_required_date, max_required_date) AS (\n"
        "  VALUES\n"
        + values
        + "\n)\n"
        "SELECT\n"
        "  n.permno,\n"
        "  n.ticker,\n"
        "  n.comnam,\n"
        "  n.ncusip,\n"
        "  n.cusip,\n"
        "  n.shrcd,\n"
        "  n.exchcd,\n"
        "  n.namedt,\n"
        "  n.nameenddt\n"
        "FROM crsp.stocknames AS n\n"
        "JOIN requested AS r\n"
        "  ON n.permno = r.permno\n"
        "WHERE n.namedt <= r.max_required_date\n"
        "  AND COALESCE(n.nameenddt, DATE '9999-12-31') >= r.min_required_date\n"
        "ORDER BY n.permno, n.namedt, n.nameenddt, n.ticker;\n"
    )


def render_summary(summary: dict) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"


def build_from_path(
    summary_path: Path = DEFAULT_ACQUISITION_SUMMARY,
) -> tuple[str, str, str]:
    payload = load_acquisition_summary(summary_path)
    securities, request_summary = build_request(
        payload,
        source_sha256=_sha256(summary_path),
    )
    return (
        render_csv(securities),
        render_sql(securities),
        render_summary(request_summary),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the minimum authorized dated stocknames request needed to close "
            "the G2 stable-security-identity gate."
        )
    )
    parser.add_argument(
        "--acquisition-summary",
        type=Path,
        default=DEFAULT_ACQUISITION_SUMMARY,
    )
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_REQUEST_CSV)
    parser.add_argument("--sql-output", type=Path, default=DEFAULT_REQUEST_SQL)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_REQUEST_SUMMARY)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    csv_text, sql_text, summary_text = build_from_path(args.acquisition_summary)
    if args.check:
        ok = (
            args.csv_output.exists()
            and args.sql_output.exists()
            and args.summary_output.exists()
            and args.csv_output.read_text(encoding="utf-8") == csv_text
            and args.sql_output.read_text(encoding="utf-8") == sql_text
            and args.summary_output.read_text(encoding="utf-8") == summary_text
        )
        return 0 if ok else 2

    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    args.sql_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.write_text(csv_text, encoding="utf-8")
    args.sql_output.write_text(sql_text, encoding="utf-8")
    args.summary_output.write_text(summary_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
