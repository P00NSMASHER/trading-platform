from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DATASET = "OPRA.PILLAR"
HISTORICAL_START = date(2013, 4, 1)
NY = ZoneInfo("America/New_York")
DEFAULT_REQUIREMENTS = Path(
    "data/processed/real_data_release_sprint/g2_champion_minimum_source_date_requirements.csv"
)
COST_URL = "https://hist.databento.com/v0/metadata.get_cost"


def load_requirements(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {
        "record_kind",
        "trade_date",
        "historical_symbols",
        "unique_symbol_count",
        "symbol_date_pair_count",
    }
    if not rows:
        raise ValueError("requirements file is empty")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"requirements file missing columns: {missing}")
    return rows


def _day_bounds(day: date) -> tuple[str, str]:
    start = datetime(day.year, day.month, day.day, tzinfo=NY)
    end_day = day + timedelta(days=1)
    end = datetime(end_day.year, end_day.month, end_day.day, tzinfo=NY)
    return start.isoformat(), end.isoformat()


def build_probe_manifest(rows: list[dict[str, str]]) -> dict:
    option_rows = [row for row in rows if row["record_kind"] in {"option_trade", "option_quote"}]
    if not option_rows:
        raise ValueError("requirements contain no option_trade/option_quote rows")

    grouped: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in option_rows:
        grouped[row["trade_date"]][row["record_kind"]] = row

    eligible = []
    ineligible = []
    for day_text in sorted(grouped):
        day = date.fromisoformat(day_text)
        kinds = grouped[day_text]
        trade = kinds.get("option_trade")
        quote = kinds.get("option_quote")
        if trade is None:
            raise ValueError(f"{day_text}: expected option_trade requirement")
        if quote is not None and trade["historical_symbols"] != quote["historical_symbols"]:
            raise ValueError(f"{day_text}: option trade/quote symbol sets differ")

        symbols = [s for s in trade["historical_symbols"].split(";") if s]
        parent_symbols = [f"{symbol}.OPT" for symbol in symbols]
        start, end = _day_bounds(day)
        row = {
            "trade_date": day_text,
            "historical_symbols": symbols,
            "parent_symbols": parent_symbols,
            "symbol_date_pair_count": int(trade["symbol_date_pair_count"]),
            "requests": {
                "option_trade": {
                    "dataset": DATASET,
                    "schema": "trades",
                    "stype_in": "parent",
                    "symbols": parent_symbols,
                    "start": start,
                    "end": end,
                    "g2_status": "candidate_direct_coverage",
                    "reason": (
                        "Databento OPRA trades are available from 2013-04-01; "
                        "production G2 still must validate authorization, date, symbols, and rows."
                    ),
                },
                "option_quote_trial": {
                    "dataset": DATASET,
                    "schema": "cbbo-1m",
                    "stype_in": "parent",
                    "symbols": parent_symbols,
                    "start": start,
                    "end": end,
                    "g2_status": "fidelity_review_required_not_counted",
                    "reason": (
                        "CBBO-1m is minute-sampled NBBO, not historical tick-by-tick quote updates. "
                        "Do not count it as strict G2 option-quote coverage without an explicit "
                        "fidelity review and contract decision."
                    ),
                },
            },
        }
        if day >= HISTORICAL_START:
            eligible.append(row)
        else:
            ineligible.append(row)

    return {
        "schema_version": "1",
        "purpose": (
            "Deterministic, no-purchase Databento OPRA cost-probe plan for frozen G2 option "
            "requirements. This manifest does not claim G2 coverage."
        ),
        "dataset": DATASET,
        "databento_historical_start": HISTORICAL_START.isoformat(),
        "total_required_option_dates": len(grouped),
        "eligible_option_dates": len(eligible),
        "ineligible_pre_databento_dates": len(ineligible),
        "eligible_underlying_date_pairs": sum(r["symbol_date_pair_count"] for r in eligible),
        "candidate_direct_g2_rows": len(eligible),
        "champion_minimum_total_rows": 1242 if len(rows) == 1242 else None,
        "candidate_champion_minimum_rows": len(eligible) if len(rows) == 1242 else None,
        "remaining_champion_minimum_rows_after_all_eligible_option_trades": (
            1242 - len(eligible) if len(rows) == 1242 else None
        ),
        "candidate_champion_minimum_fraction": (
            len(eligible) / 1242 if len(rows) == 1242 else None
        ),
        "quote_trial_rows_not_counted": len(eligible),
        "eligible": eligible,
        "ineligible_dates": [r["trade_date"] for r in ineligible],
    }


def _estimate_cost(api_key: str, request_spec: dict) -> float:
    params = {
        "dataset": request_spec["dataset"],
        "schema": request_spec["schema"],
        "stype_in": request_spec["stype_in"],
        "symbols": ",".join(request_spec["symbols"]),
        "start": request_spec["start"],
        "end": request_spec["end"],
    }
    url = COST_URL + "?" + urllib.parse.urlencode(params)
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = response.read().decode("utf-8").strip()
    return float(json.loads(payload))


def add_cost_estimates(
    manifest: dict,
    *,
    api_key: str,
    include_quote_trial: bool = False,
    budget_usd: float = 125.0,
) -> dict:
    total_trade = 0.0
    total_quote = 0.0
    ranked = []

    for row in manifest["eligible"]:
        trade_req = row["requests"]["option_trade"]
        trade_cost = _estimate_cost(api_key, trade_req)
        trade_req["estimated_cost_usd"] = trade_cost
        total_trade += trade_cost
        ranked.append((trade_cost, row["trade_date"], "option_trade"))

        if include_quote_trial:
            quote_req = row["requests"]["option_quote_trial"]
            quote_cost = _estimate_cost(api_key, quote_req)
            quote_req["estimated_cost_usd"] = quote_cost
            total_quote += quote_cost

    spent = 0.0
    selected_dates = []
    for cost, trade_date, _ in sorted(ranked):
        if spent + cost > budget_usd:
            continue
        selected_dates.append(trade_date)
        spent += cost

    manifest["cost_estimate"] = {
        "budget_usd": budget_usd,
        "trade_total_usd": total_trade,
        "quote_trial_total_usd": total_quote if include_quote_trial else None,
        "cheapest_first_trade_dates_within_budget": selected_dates,
        "cheapest_first_trade_rows_within_budget": len(selected_dates),
        "estimated_budget_used_usd": spent,
        "note": (
            "Cost estimates are Databento metadata estimates only. No data is downloaded or purchased "
            "by this command. Actual billing is based on bytes sent."
        ),
    }
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build or cost a Databento OPRA probe plan for frozen G2 option requirements."
    )
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--estimate-costs", action="store_true")
    parser.add_argument("--include-quote-trial", action="store_true")
    parser.add_argument("--budget-usd", type=float, default=125.0)
    args = parser.parse_args()

    manifest = build_probe_manifest(load_requirements(args.requirements))
    if args.estimate_costs:
        api_key = os.environ.get("DATABENTO_API_KEY", "").strip()
        if not api_key:
            raise SystemExit("DATABENTO_API_KEY is required for --estimate-costs")
        manifest = add_cost_estimates(
            manifest,
            api_key=api_key,
            include_quote_trial=args.include_quote_trial,
            budget_usd=args.budget_usd,
        )

    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
