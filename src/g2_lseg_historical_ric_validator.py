from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

import g2_lseg_datascope_execution_plan as execution
import g2_lseg_request_manifest as manifest

ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_text(path: Path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def read_rows(path: Path) -> list[dict[str, str]]:
    with _open_text(path) as handle:
        return list(csv.DictReader(handle))


def _date_from_datetime(value: object) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(ZoneInfo("America/New_York"))
    return parsed.date()


def row_trade_date(row: Mapping[str, object]) -> date | None:
    for key in ("Date-Time", "Date", "Date[G]", "Trade Date"):
        value = row.get(key)
        if value in (None, ""):
            continue
        if key == "Date-Time":
            parsed = _date_from_datetime(value)
            if parsed is not None:
                return parsed
            continue
        raw = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%Y%m%d"):
            try:
                return datetime.strptime(raw[:10], fmt).date()
            except ValueError:
                pass
    return None


def row_kind(row: Mapping[str, object]) -> str:
    raw = str(row.get("Type") or "").strip().lower()
    if raw == "trade":
        return "trade"
    if raw == "quote":
        return "quote"

    price = row.get("Price")
    volume = row.get("Volume")
    bid = row.get("Bid Price")
    ask = row.get("Ask Price")
    if price not in (None, "") and volume not in (None, ""):
        return "trade"
    if bid not in (None, "") or ask not in (None, ""):
        return "quote"
    return "other"


def _plan() -> dict:
    base = manifest.build_plan(
        manifest._read_csv(ROOT / manifest.DEFAULT_MAPPING),
        manifest._read_csv(ROOT / manifest.DEFAULT_SECONDARY),
        manifest._read_csv(ROOT / manifest.DEFAULT_EVENT_MAPPING),
        manifest._read_csv(ROOT / manifest.DEFAULT_CORE),
        manifest._read_csv(ROOT / manifest.DEFAULT_OPTIONS),
    )
    return execution.build_execution_plan(base)


def expected_symbol_dates(plan: dict, trade_date: str) -> list[dict[str, object]]:
    date.fromisoformat(trade_date)
    rows = [
        row
        for row in plan["equity_symbol_dates"]
        if str(row["trade_date"]) == trade_date
    ]
    if not rows:
        raise ValueError(f"{trade_date}: not in frozen G2 equity scope")
    return rows


def validate_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    plan: dict,
    trade_date: str,
) -> dict:
    requested_date = date.fromisoformat(trade_date)
    expected = expected_symbol_dates(plan, trade_date)

    candidate_to_symbols: dict[str, set[str]] = defaultdict(set)
    expected_by_symbol: dict[str, dict[str, object]] = {}
    for item in expected:
        symbol = str(item["historical_symbol"])
        expected_by_symbol[symbol] = item
        for ric in list(item["candidate_rics"]):
            candidate_to_symbols[str(ric)].add(symbol)

    observed: dict[str, Counter] = defaultdict(Counter)
    ignored_wrong_date = 0
    ignored_unknown_ric = 0
    unparseable_date_rows = 0

    for row in rows:
        ric = str(row.get("#RIC") or row.get("RIC") or "").strip()
        if not ric:
            continue
        parsed_date = row_trade_date(row)
        if parsed_date is None:
            unparseable_date_rows += 1
            continue
        if parsed_date != requested_date:
            ignored_wrong_date += 1
            continue
        if ric not in candidate_to_symbols:
            ignored_unknown_ric += 1
            continue
        observed[ric][row_kind(row)] += 1
        observed[ric]["all"] += 1

    results: list[dict[str, object]] = []
    for symbol in sorted(expected_by_symbol):
        item = expected_by_symbol[symbol]
        candidates = [str(x) for x in list(item["candidate_rics"])]
        seen = [ric for ric in candidates if observed[ric]["all"] > 0]

        if len(seen) == 1:
            selected = seen[0]
            status = "validated_single_candidate"
        elif len(seen) > 1:
            selected = ""
            status = "ambiguous_multiple_candidates_observed"
        else:
            selected = ""
            status = "no_candidate_observed"

        results.append(
            {
                "trade_date": trade_date,
                "historical_symbol": symbol,
                "mapping_class": str(item["mapping_class"]),
                "historical_validation_required": bool(
                    item["historical_validation_required"]
                ),
                "candidate_rics": candidates,
                "observed_candidate_rics": seen,
                "selected_ric": selected,
                "validation_status": status,
                "selected_trade_rows": (
                    observed[selected]["trade"] if selected else 0
                ),
                "selected_quote_rows": (
                    observed[selected]["quote"] if selected else 0
                ),
                "selected_other_rows": (
                    observed[selected]["other"] if selected else 0
                ),
                "trade_lane_observed": bool(
                    selected and observed[selected]["trade"] > 0
                ),
                "quote_lane_observed": bool(
                    selected and observed[selected]["quote"] > 0
                ),
            }
        )

    counts = Counter(row["validation_status"] for row in results)
    return {
        "schema_version": "1",
        "trade_date": trade_date,
        "purpose": (
            "Validate historical LSEG RIC candidates from an authorized Time & Sales "
            "extract without treating identifier validation as G2 market-data coverage."
        ),
        "summary": {
            "expected_historical_symbols": len(results),
            "validated_single_candidate": counts["validated_single_candidate"],
            "ambiguous_multiple_candidates_observed": counts[
                "ambiguous_multiple_candidates_observed"
            ],
            "no_candidate_observed": counts["no_candidate_observed"],
            "trade_lane_observed_symbols": sum(
                bool(row["trade_lane_observed"]) for row in results
            ),
            "quote_lane_observed_symbols": sum(
                bool(row["quote_lane_observed"]) for row in results
            ),
            "ignored_wrong_date_rows": ignored_wrong_date,
            "ignored_unknown_ric_rows": ignored_unknown_ric,
            "unparseable_date_rows": unparseable_date_rows,
            "g2_coverage_change": False,
        },
        "results": results,
    }


def validate_file(path: Path, *, trade_date: str, plan: dict | None = None) -> dict:
    resolved = path.expanduser().resolve()
    payload = validate_rows(
        read_rows(resolved),
        plan=_plan() if plan is None else plan,
        trade_date=trade_date,
    )
    payload["input_receipt"] = {
        "path_name": resolved.name,
        "size_bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }
    return payload


def _write_results(output_dir: Path, payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    public_summary = {
        key: value for key, value in payload.items() if key != "results"
    }
    (output_dir / "summary.json").write_text(
        json.dumps(public_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    fields = [
        "trade_date",
        "historical_symbol",
        "mapping_class",
        "historical_validation_required",
        "candidate_rics",
        "observed_candidate_rics",
        "selected_ric",
        "validation_status",
        "selected_trade_rows",
        "selected_quote_rows",
        "selected_other_rows",
        "trade_lane_observed",
        "quote_lane_observed",
    ]
    with (output_dir / "historical_ric_validation.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for raw in payload["results"]:
            row = dict(raw)
            row["candidate_rics"] = ";".join(row["candidate_rics"])
            row["observed_candidate_rics"] = ";".join(
                row["observed_candidate_rics"]
            )
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate date-specific LSEG RIC candidates from an authorized "
            "Tick History Time & Sales extract."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    payload = validate_file(args.input, trade_date=args.date)
    _write_results(args.output_dir, payload)
    print(json.dumps(payload["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
