from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"
)
TOKEN_URL = "https://id.livevol.com/connect/token"
API_BASE = "https://api.livevol.com/v1/live/allaccess"
CBOE_EARLIEST_VENDOR_CONFIRMED_OPRA_DATE = "2012-01-01"
PAGE_LIMIT = 10_000
MAX_PAGES_PER_STREAM = 10_000
MAX_RETRIES = 5

PRIVATE_REPO_PREFIXES = (
    Path("data/private"),
    Path("data/licensed"),
    Path("data/vendor"),
    Path("data/incoming"),
    Path("data/staging"),
    Path("private_runtime"),
)

REFERENCE_OPTIONS_DOC = (
    "https://api.livevol.com/v1/docs/Help/Api"
    "?apiId=GET-allaccess-reference-options_date_symbol"
)
OPTION_TRADES_DOC = (
    "https://api.livevol.com/v1/docs/Help/Api/"
    "GET-allaccess-time-and-sales-option-trades_symbol_root_expiry_strike_option_type_"
    "min_time_max_time_seq_no_exchange_id_condition_id_limit_min_size_max_size_min_price_"
    "max_price_date?apiGroupName=allaccess"
)
OPTION_QUOTES_DOC = (
    "https://api.livevol.com/v1/docs/Help/Api/"
    "GET-allaccess-time-and-sales-quotes_start_sequence_number_exchange_id_condition_id_"
    "limit_order_by_time_min_time_max_time_date_symbol"
)


@dataclass(frozen=True)
class TrialTask:
    trade_date: str
    historical_symbol: str


def _read_requirements(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("requirements file is empty")
    required = {
        "record_kind",
        "trade_date",
        "historical_symbols",
        "unique_symbol_count",
        "symbol_date_pair_count",
    }
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"requirements file missing columns: {sorted(missing)}")
    return rows


def build_trial_tasks(rows: list[dict[str, str]]) -> list[TrialTask]:
    by_kind: dict[str, dict[str, set[str]]] = {
        "option_trade": {},
        "option_quote": {},
    }
    source_date_counts = {"option_trade": 0, "option_quote": 0}

    for row in rows:
        kind = row["record_kind"]
        if kind not in by_kind:
            continue
        source_date_counts[kind] += 1
        symbols = {s for s in row["historical_symbols"].split(";") if s}
        expected = int(row["unique_symbol_count"])
        if len(symbols) != expected:
            raise ValueError(f"{row['trade_date']}: unique_symbol_count mismatch")
        by_kind[kind][row["trade_date"]] = symbols

    if source_date_counts != {"option_trade": 414, "option_quote": 414}:
        raise ValueError(
            "expected canonical 414 option_trade and 414 option_quote source-date rows"
        )

    eligible_dates = sorted(
        d
        for d in by_kind["option_trade"]
        if d >= CBOE_EARLIEST_VENDOR_CONFIRMED_OPRA_DATE
    )
    if len(eligible_dates) != 309:
        raise ValueError(f"expected 309 Cboe-eligible dates, found {len(eligible_dates)}")

    tasks: list[TrialTask] = []
    for trade_date in eligible_dates:
        trade_symbols = by_kind["option_trade"][trade_date]
        quote_symbols = by_kind["option_quote"].get(trade_date)
        if quote_symbols != trade_symbols:
            raise ValueError(
                f"{trade_date}: option_trade/option_quote historical symbol sets differ"
            )
        for symbol in sorted(trade_symbols):
            tasks.append(TrialTask(trade_date, symbol))

    if len(tasks) != 3364:
        raise ValueError(f"expected 3364 Cboe-eligible symbol-date tasks, found {len(tasks)}")
    return tasks


def build_dry_run_manifest(tasks: list[TrialTask]) -> dict[str, Any]:
    dates = sorted({task.trade_date for task in tasks})
    symbols = sorted({task.historical_symbol for task in tasks})
    return {
        "schema_version": "1",
        "purpose": (
            "Pre-trial execution manifest for full 2012-2015 Cboe OPRA option-trade "
            "and tick-quote acquisition. Dry-run only; no account activation and no API calls."
        ),
        "vendor_confirmed_opra_floor": CBOE_EARLIEST_VENDOR_CONFIRMED_OPRA_DATE,
        "source_date_rows_targeted": {
            "option_trade": len(dates),
            "option_quote": len(dates),
        },
        "eligible_dates": len(dates),
        "underlying_date_tasks": len(tasks),
        "unique_historical_underlyings": len(symbols),
        "first_date": dates[0],
        "last_date": dates[-1],
        "page_limit": PAGE_LIMIT,
        "contract_enumeration": {
            "endpoint": "reference/options",
            "reason": (
                "Enumerate the full historical option chain for each underlying/date so "
                "quote acquisition is not limited to contracts that happened to trade."
            ),
        },
        "trade_stream": {
            "endpoint": "time-and-sales/option-trades",
            "pagination_parameter": "seq_no",
            "pagination_rule": "next cursor = max returned seq_no + 1",
        },
        "quote_stream": {
            "endpoint": "time-and-sales/quotes",
            "symbol": "OSI contract from reference/options",
            "pagination_parameter": "start_sequence_number",
            "pagination_rule": "next cursor = max returned seq_no + 1",
        },
        "resumability": {
            "per_underlying_date_receipt": True,
            "sha256_for_contracts_trades_quotes": True,
            "completed_receipt_revalidated_before_skip": True,
        },
        "runtime_safety": {
            "execute_requires_credentials": ["CBOE_CLIENT_ID", "CBOE_CLIENT_SECRET"],
            "execute_requires_explicit_ack": "--ack-trial-active",
            "execute_requires_retention_ack": "--ack-retention-authorized",
            "retention_authority": {
                "required": True,
                "state": "PENDING_WRITTEN_VENDOR_CONFIRMATION",
                "definition": (
                    "Written Cboe Order Form or vendor permission allowing retained "
                    "internal research use after trial termination."
                ),
            },
            "private_output_required": True,
            "retry_429_and_5xx": True,
            "no_coverage_promotion": True,
        },
        "docs": {
            "reference_options": REFERENCE_OPTIONS_DOC,
            "option_trades": OPTION_TRADES_DOC,
            "option_quotes": OPTION_QUOTES_DOC,
        },
        "coverage_claimed": False,
    }


def osi_symbol(root: str, expiry: str, option_type: str, strike: Any) -> str:
    root_clean = str(root).strip().upper()
    option_type_clean = str(option_type).strip().upper()
    if not root_clean:
        raise ValueError("option root must be nonblank")
    if option_type_clean not in {"C", "P"}:
        raise ValueError("option_type must be C or P")
    expiry_date = date.fromisoformat(str(expiry))
    try:
        scaled = Decimal(str(strike)) * Decimal("1000")
    except InvalidOperation as exc:
        raise ValueError("invalid option strike") from exc
    if scaled != scaled.to_integral_value():
        raise ValueError("strike cannot be represented in OSI thousandths")
    strike_int = int(scaled)
    if strike_int < 0 or strike_int > 99_999_999:
        raise ValueError("strike outside OSI eight-digit range")
    return (
        f"{root_clean}{expiry_date.strftime('%y%m%d')}{option_type_clean}"
        f"{strike_int:08d}"
    )


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    raise ValueError("unexpected Cboe response shape")


def _next_cursor(rows: list[dict[str, Any]], current: int) -> int:
    seqs: list[int] = []
    for row in rows:
        value = row.get("seq_no")
        if value is None:
            raise ValueError("full Cboe page is missing seq_no")
        seqs.append(int(value))
    next_value = max(seqs) + 1
    if next_value <= current:
        raise ValueError("Cboe pagination cursor did not advance")
    return next_value


def collect_paginated(
    url_for_cursor: Callable[[int], str],
    getter: Callable[[str], Any],
    *,
    limit: int = PAGE_LIMIT,
    max_pages: int = MAX_PAGES_PER_STREAM,
) -> tuple[list[dict[str, Any]], int]:
    if limit <= 0 or limit > PAGE_LIMIT:
        raise ValueError("invalid page limit")
    cursor = 0
    all_rows: list[dict[str, Any]] = []
    pages = 0

    while True:
        if pages >= max_pages:
            raise RuntimeError("Cboe pagination exceeded max_pages fail-safe")
        rows = _extract_rows(getter(url_for_cursor(cursor)))
        pages += 1
        all_rows.extend(rows)
        if len(rows) < limit:
            return all_rows, pages
        cursor = _next_cursor(rows, cursor)


def _reference_options_url(task: TrialTask) -> str:
    query = urllib.parse.urlencode(
        {"date": task.trade_date, "symbol": task.historical_symbol}
    )
    return f"{API_BASE}/reference/options?{query}"


def _option_trades_url(task: TrialTask, cursor: int) -> str:
    query = urllib.parse.urlencode(
        {
            "symbol": task.historical_symbol,
            "root": "",
            "expiry": "",
            "strike": "",
            "option_type": "",
            "min_time": "00:00:00.000",
            "max_time": "23:59:59.999",
            "seq_no": cursor,
            "exchange_id": "",
            "condition_id": "",
            "limit": PAGE_LIMIT,
            "min_size": "",
            "max_size": "",
            "min_price": "",
            "max_price": "",
            "date": task.trade_date,
        }
    )
    return f"{API_BASE}/time-and-sales/option-trades?{query}"


def _option_quotes_url(task: TrialTask, security: str, cursor: int) -> str:
    query = urllib.parse.urlencode(
        {
            "start_sequence_number": cursor,
            "exchange_id": "",
            "condition_id": "",
            "limit": PAGE_LIMIT,
            "order_by_time": "ASC",
            "min_time": "00:00:00.000",
            "max_time": "23:59:59.999",
            "date": task.trade_date,
            "symbol": security,
        }
    )
    return f"{API_BASE}/time-and-sales/quotes?{query}"


def _contracts_from_reference(payload: Any) -> list[str]:
    rows = _extract_rows(payload)
    contracts = {
        osi_symbol(
            str(row.get("root") or ""),
            str(row.get("expiry") or ""),
            str(row.get("type") or row.get("option_type") or ""),
            row.get("strike"),
        )
        for row in rows
    }
    if not contracts:
        raise ValueError("historical reference/options returned no contracts")
    return sorted(contracts)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl_gz(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            for row in rows:
                line = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                gz.write(line.encode("utf-8"))


def ensure_private_output_path(path: Path, *, repo_root: Path | None = None) -> Path:
    resolved = path.expanduser().resolve()
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    root = repo_root.resolve()
    if not resolved.is_relative_to(root):
        return resolved
    relative = resolved.relative_to(root)
    if any(relative == prefix or prefix in relative.parents for prefix in PRIVATE_REPO_PREFIXES):
        return resolved
    raise ValueError(
        "licensed Cboe output inside this repository must be under an ignored/private "
        "path such as data/private/ or private_runtime/"
    )


def _task_dir(output_root: Path, task: TrialTask) -> Path:
    return output_root / task.trade_date / task.historical_symbol


def _receipt_valid(task_dir: Path, task: TrialTask) -> bool:
    receipt_path = task_dir / "receipt.json"
    if not receipt_path.exists():
        return False
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if (
        receipt.get("status") != "downloaded_pending_content_validation"
        or receipt.get("trade_date") != task.trade_date
        or receipt.get("historical_symbol") != task.historical_symbol
        or receipt.get("g2_coverage_change") != 0
    ):
        return False
    files = dict(receipt.get("files") or {})
    for name in ("contracts.json", "option_trades.jsonl.gz", "option_quotes.jsonl.gz"):
        path = task_dir / name
        expected = str((files.get(name) or {}).get("sha256") or "")
        if not path.exists() or not expected or _sha256_file(path) != expected:
            return False
    return True


class CboeClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        opener: Callable = urllib.request.urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("Cboe client id/secret are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self._open = opener
        self._sleep = sleeper
        self._token: str | None = None

    def token(self) -> str:
        if self._token:
            return self._token
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode("utf-8")
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
        with self._open(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("Cboe token response did not contain access_token")
        self._token = token
        return token

    def get_json(self, url: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {self.token()}",
                    "Accept": "application/json",
                },
                method="GET",
            )
            try:
                with self._open(request, timeout=90) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504}:
                    detail = exc.read().decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"Cboe request failed HTTP {exc.code}: {detail[:500]}"
                    ) from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = float(retry_after) if retry_after else min(2**attempt, 30)
                self._sleep(delay)
            except urllib.error.URLError as exc:
                last_error = exc
                self._sleep(min(2**attempt, 30))
        raise RuntimeError("Cboe request failed after bounded retries") from last_error


def download_task(
    client: CboeClient,
    task: TrialTask,
    output_root: Path,
) -> dict[str, Any]:
    output_root = ensure_private_output_path(output_root)
    task_dir = _task_dir(output_root, task)
    if _receipt_valid(task_dir, task):
        return {
            "status": "skipped_existing_valid_receipt",
            "trade_date": task.trade_date,
            "historical_symbol": task.historical_symbol,
            "g2_coverage_change": 0,
        }

    contracts_payload = client.get_json(_reference_options_url(task))
    contracts = _contracts_from_reference(contracts_payload)

    trade_rows, trade_pages = collect_paginated(
        lambda cursor: _option_trades_url(task, cursor),
        client.get_json,
    )

    quote_rows: list[dict[str, Any]] = []
    quote_pages = 0
    for security in contracts:
        rows, pages = collect_paginated(
            lambda cursor, security=security: _option_quotes_url(task, security, cursor),
            client.get_json,
        )
        for row in rows:
            row = dict(row)
            row.setdefault("security", security)
            quote_rows.append(row)
        quote_pages += pages

    task_dir.mkdir(parents=True, exist_ok=True)
    contracts_path = task_dir / "contracts.json"
    trades_path = task_dir / "option_trades.jsonl.gz"
    quotes_path = task_dir / "option_quotes.jsonl.gz"

    _write_json(
        contracts_path,
        {
            "trade_date": task.trade_date,
            "historical_symbol": task.historical_symbol,
            "contracts": contracts,
        },
    )
    _write_jsonl_gz(trades_path, trade_rows)
    _write_jsonl_gz(quotes_path, quote_rows)

    files = {
        path.name: {
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in (contracts_path, trades_path, quotes_path)
    }
    receipt = {
        "schema_version": "1",
        "status": "downloaded_pending_content_validation",
        "trade_date": task.trade_date,
        "historical_symbol": task.historical_symbol,
        "contract_count": len(contracts),
        "option_trade_rows": len(trade_rows),
        "option_quote_rows": len(quote_rows),
        "option_trade_pages": trade_pages,
        "option_quote_pages": quote_pages,
        "files": files,
        "content_validation_completed": False,
        "validation_promoted": False,
        "g2_coverage_change": 0,
    }
    _write_json(task_dir / "receipt.json", receipt)
    return receipt


def execute_slice(
    client: CboeClient,
    tasks: list[TrialTask],
    output_root: Path,
    *,
    start: int,
    limit: int,
) -> dict[str, Any]:
    if start < 0:
        raise ValueError("start must be non-negative")
    if limit <= 0:
        raise ValueError("limit must be positive")
    selected = tasks[start : start + limit]
    receipts = [download_task(client, task, output_root) for task in selected]
    return {
        "schema_version": "1",
        "selected_start": start,
        "selected_limit": limit,
        "tasks_selected": len(selected),
        "tasks_total": len(tasks),
        "receipts": receipts,
        "validation_promoted": False,
        "g2_coverage_change": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or execute a bounded Cboe All Access 2012-2015 OPRA trial slice. "
            "Dry-run is the default and makes no network requests."
        )
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack-trial-active", action="store_true")
    parser.add_argument("--ack-retention-authorized", action="store_true")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--manifest-output", type=Path)
    args = parser.parse_args()

    tasks = build_trial_tasks(_read_requirements(args.requirements))

    if not args.execute:
        result = build_dry_run_manifest(tasks)
    else:
        if not args.ack_trial_active:
            raise SystemExit("--execute requires --ack-trial-active")
        if not args.ack_retention_authorized:
            raise SystemExit(
                "--execute requires --ack-retention-authorized after written Cboe "
                "retention authority is confirmed"
            )
        if args.output_root is None:
            raise SystemExit("--execute requires --output-root")
        client_id = os.environ.get("CBOE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("CBOE_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise SystemExit("CBOE_CLIENT_ID and CBOE_CLIENT_SECRET are required")
        client = CboeClient(client_id, client_secret)
        result = execute_slice(
            client,
            tasks,
            args.output_root,
            start=args.start,
            limit=args.limit,
        )

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.manifest_output:
        args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
