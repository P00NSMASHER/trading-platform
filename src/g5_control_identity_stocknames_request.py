from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path


SCHEMA_VERSION = "1"

REQUEST_FIELDS = [
    "permno",
    "historical_symbol",
    "request_count",
    "first_required_date",
    "last_required_date",
    "required_dates",
    "hint_sources",
    "research_use_only",
]


@dataclass(frozen=True)
class StocknamesRequest:
    permno: str
    historical_symbol: str
    request_count: int
    first_required_date: str
    last_required_date: str
    required_dates: str
    hint_sources: str
    research_use_only: int = 1


class G5StocknamesRequestError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(key): str(value or "").strip() for key, value in row.items()}
            for row in reader
        ]
    return fields, rows


def _parse_date(value: str, *, label: str) -> str:
    raw = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise G5StocknamesRequestError(
            f"{label} must be a valid YYYY-MM-DD date"
        ) from exc


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_request_rows(
    fields: list[str],
    rows: list[dict[str, str]],
) -> list[StocknamesRequest]:
    required = {
        "request_id",
        "permno",
        "historical_symbol",
        "trade_date",
        "hint_source",
        "identity_status",
        "research_use_only",
    }
    missing = required.difference(fields)
    if missing:
        raise G5StocknamesRequestError(
            f"expanded Stocknames queue missing columns: {sorted(missing)}"
        )
    if not rows:
        raise G5StocknamesRequestError("expanded Stocknames queue is empty")

    grouped: dict[tuple[str, str], dict[str, set[str]]] = {}
    seen_request_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    symbol_to_permnos: dict[str, set[str]] = {}

    for row_no, row in enumerate(rows, 2):
        request_id = row["request_id"]
        permno = row["permno"]
        symbol = row["historical_symbol"].upper()
        trade_date = _parse_date(
            row["trade_date"],
            label=f"expanded Stocknames row {row_no} trade_date",
        )
        hint_source = row["hint_source"]

        if not request_id or request_id in seen_request_ids:
            raise G5StocknamesRequestError(
                f"expanded Stocknames row {row_no}: request_id must be unique and nonblank"
            )
        seen_request_ids.add(request_id)
        if not permno.isdigit() or int(permno) <= 0:
            raise G5StocknamesRequestError(
                f"expanded Stocknames row {row_no}: PERMNO must be positive digits"
            )
        if not symbol or not hint_source:
            raise G5StocknamesRequestError(
                f"expanded Stocknames row {row_no}: historical_symbol and hint_source are required"
            )
        if row["research_use_only"] != "1":
            raise G5StocknamesRequestError(
                f"expanded Stocknames row {row_no}: research_use_only must equal 1"
            )

        pair = (symbol, trade_date)
        if pair in seen_pairs:
            raise G5StocknamesRequestError(
                f"duplicate expanded Stocknames symbol-date: {symbol}|{trade_date}"
            )
        seen_pairs.add(pair)

        symbol_to_permnos.setdefault(symbol, set()).add(permno)
        bucket = grouped.setdefault(
            (permno, symbol),
            {"dates": set(), "hint_sources": set()},
        )
        bucket["dates"].add(trade_date)
        bucket["hint_sources"].add(hint_source)

    collisions = {
        symbol: sorted(permnos)
        for symbol, permnos in symbol_to_permnos.items()
        if len(permnos) > 1
    }
    if collisions:
        raise G5StocknamesRequestError(
            f"historical symbols map to multiple PERMNO acquisition leads: {collisions}"
        )

    requests: list[StocknamesRequest] = []
    for (permno, symbol), bucket in sorted(
        grouped.items(),
        key=lambda item: (item[0][1], int(item[0][0])),
    ):
        dates = sorted(bucket["dates"])
        requests.append(
            StocknamesRequest(
                permno=permno,
                historical_symbol=symbol,
                request_count=len(dates),
                first_required_date=dates[0],
                last_required_date=dates[-1],
                required_dates=";".join(dates),
                hint_sources=";".join(sorted(bucket["hint_sources"])),
            )
        )

    if sum(row.request_count for row in requests) != len(rows):
        raise G5StocknamesRequestError(
            "grouped Stocknames request count does not reconcile to input queue"
        )
    return requests


def render_sql(requests: list[StocknamesRequest]) -> str:
    if not requests:
        raise G5StocknamesRequestError("cannot render Stocknames SQL for empty request")

    values = []
    for row in requests:
        values.append(
            "    ("
            + ", ".join(
                [
                    row.permno,
                    _sql_quote(row.historical_symbol),
                    f"DATE {_sql_quote(row.first_required_date)}",
                    f"DATE {_sql_quote(row.last_required_date)}",
                ]
            )
            + ")"
        )

    return (
        "-- Exact authorized Stocknames acquisition request for routable G5 control identity dates.\n"
        "-- PERMNO values are acquisition leads only; returned dated name history must still\n"
        "-- validate each required symbol/date before any identity evidence can be staged.\n"
        "-- No authentication, entitlement bypass, purchase, or licensed payload is included.\n"
        "WITH requested(permno, historical_symbol, min_required_date, max_required_date) AS (\n"
        "  VALUES\n"
        + ",\n".join(values)
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


def build(
    *,
    expanded_queue_path: Path,
    output_dir: Path,
) -> dict:
    fields, rows = _read_csv(expanded_queue_path)
    requests = build_request_rows(fields, rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    request_path = output_dir / "g5_control_identity_stocknames_request.csv"
    sql_path = output_dir / "g5_control_identity_stocknames_request.sql"
    summary_path = output_dir / "g5_control_identity_stocknames_request_summary.json"

    with request_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUEST_FIELDS)
        writer.writeheader()
        for row in requests:
            writer.writerow(asdict(row))

    sql_path.write_text(render_sql(requests), encoding="utf-8")

    all_dates = [
        trade_date
        for row in requests
        for trade_date in row.required_dates.split(";")
        if trade_date
    ]
    hint_sources = sorted(
        {
            source
            for row in requests
            for source in row.hint_sources.split(";")
            if source
        }
    )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Freeze the minimum authorized CRSP-style Stocknames acquisition request "
            "for every G5 control identity date that already has a reconciled PERMNO "
            "acquisition lead. The request is planning only and does not treat a lead "
            "or a returned row as identity evidence without exact dated validation."
        ),
        "research_use_only": True,
        "state": {
            "date_level_request_count": len(rows),
            "grouped_permno_symbol_request_count": len(requests),
            "unique_permno_count": len({row.permno for row in requests}),
            "unique_historical_symbol_count": len(
                {row.historical_symbol for row in requests}
            ),
            "first_required_date": min(all_dates),
            "last_required_date": max(all_dates),
            "hint_sources": hint_sources,
        },
        "inputs": {
            "expanded_queue_path": str(expanded_queue_path),
            "expanded_queue_sha256": _sha256(expanded_queue_path),
        },
        "outputs": {
            "request_csv": str(request_path),
            "request_sql": str(sql_path),
            "summary": str(summary_path),
        },
        "authorization_policy": {
            "requires_authorized_stocknames_or_equivalent_security_master": True,
            "authentication_or_entitlement_bypass_prohibited": True,
            "unverified_mirror_may_not_close_identity": True,
            "permno_leads_are_identity_evidence": False,
            "returned_stocknames_rows_are_automatically_identity_evidence": False,
            "exact_requested_date_and_historical_symbol_validation_required": True,
            "current_ticker_substitution_prohibited": True,
        },
        "data_fetch_performed": False,
        "purchase_performed": False,
        "g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the exact authorized Stocknames request for G5 control identity "
            "dates already carrying reconciled PERMNO acquisition leads."
        )
    )
    parser.add_argument("--expanded-queue", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        expanded_queue_path=args.expanded_queue,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
