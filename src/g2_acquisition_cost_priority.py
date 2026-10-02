from __future__ import annotations

import argparse
import json
from pathlib import Path

import g2_tickapi_cost_estimator as tickapi

DEFAULT_VENDOR_DIR = Path("data/processed/g2_vendor_requests")
PRICING_AS_OF = "2026-10-02"
TICKDATA_DATASTORE_URL = "https://www.tickdata.com/tickdatastore"
TICKDATA_FEE_ESTIMATE_URL = "https://www.tickdata.com/fee-estimate"
TICKDATA_NEW_CLIENT_MINIMUM_USD = 1000.0


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build(vendor_dir: Path) -> dict:
    summary = _read_json(vendor_dir / "vendor_request_summary.json")
    trial = _read_json(vendor_dir / "cboe_trial_capacity_plan.json")
    tickapi_estimate = tickapi.estimate(
        tickapi._read(vendor_dir / "tickdata_equity_trades.csv"),
        tickapi._read(vendor_dir / "tickdata_equity_nbbo_quotes.csv"),
    )

    if summary["champion_minimum_source_date_rows"] != 1242:
        raise ValueError("vendor summary does not match champion-minimum scope")
    if trial["required_source_date_rows"] != 83 or trial["coverage_claimed"] is not False:
        raise ValueError("Cboe trial plan is inconsistent or claims coverage")

    tickapi_floor = tickapi_estimate["estimated_first_year_minimum_combined_requests_usd"]

    return {
        "schema_version": "1",
        "purpose": (
            "Planning-only cheap-first acquisition sequence for G2_CHAMPION_MINIMUM. "
            "It does not authorize purchase, trial activation, download, or G2 coverage."
        ),
        "pricing_as_of": PRICING_AS_OF,
        "champion_minimum_source_date_rows": 1242,
        "canonical_full_g2_source_date_rows": 1656,
        "known_public_cost_floors": {
            "tickdata_datastore_new_client_minimum_usd": TICKDATA_NEW_CLIENT_MINIMUM_USD,
            "tickdata_datastore_source": TICKDATA_DATASTORE_URL,
            "tickdata_fee_estimate_source": TICKDATA_FEE_ESTIMATE_URL,
            "tickapi_estimated_first_year_minimum_usd": tickapi_floor,
        },
        "priority": [
            {
                "rank": 1,
                "route": "cboe_free_trial_capacity",
                "scope_source_date_rows_upper_bound": trial[
                    "optimistic_complete_source_date_rows"
                ],
                "scope_symbol_date_pairs_upper_bound": trial[
                    "optimistic_complete_underlying_date_pairs"
                ],
                "cost_status": "POTENTIALLY_ZERO_TRIAL_AWAITING_VENDOR_CONFIRMATION",
                "blocking_state": "AWAITING_VENDOR_CONFIRMATION",
                "automatic_activation_permitted": False,
                "note": (
                    "Use only if Cboe confirms historical Option Trades are available on the "
                    "14-day trial and explicit user authorization is given. Pagination can reduce "
                    "the optimistic 81-row capacity."
                ),
            },
            {
                "rank": 2,
                "route": "databento_opra_cost_probe",
                "scope_source_date_rows": 226,
                "scope_symbol_date_pairs": 2875,
                "cost_status": "UNKNOWN_UNTIL_DATABENTO_API_KEY_CONFIGURED",
                "automatic_purchase_permitted": False,
                "note": (
                    "Run metadata.get_cost only. The existing workflow performs no download or "
                    "purchase and fails closed when the API key is absent."
                ),
            },
            {
                "rank": 3,
                "route": "tickdata_one_time_datastore_equities",
                "scope_source_date_rows": 828,
                "scope_symbol_date_pairs": 7656,
                "public_new_client_minimum_order_usd": TICKDATA_NEW_CLIENT_MINIMUM_USD,
                "exact_quote_status": "PENDING_EXTERNAL",
                "automatic_purchase_permitted": False,
                "note": (
                    "Price the one-time Data Store subset before considering TickAPI. The public "
                    "new-client minimum is materially below the current TickAPI first-year floor."
                ),
            },
            {
                "rank": 4,
                "route": "lseg_2011_opra_tick_history",
                "scope_source_date_rows": 105,
                "scope_symbol_date_pairs": 464,
                "exact_quote_status": "PENDING_EXTERNAL",
                "automatic_purchase_permitted": False,
            },
            {
                "rank": 5,
                "route": "cboe_paid_remainder_or_fallback",
                "scope_source_date_rows_if_trial_capacity_holds": trial[
                    "remaining_source_date_rows"
                ],
                "scope_symbol_date_pairs_if_trial_capacity_holds": trial[
                    "remaining_underlying_date_pairs"
                ],
                "scope_source_date_rows_if_trial_unavailable": trial[
                    "required_source_date_rows"
                ],
                "exact_quote_status": "PENDING_EXTERNAL",
                "automatic_purchase_permitted": False,
            },
        ],
        "decision_rules": {
            "candidate_source_is_not_coverage": True,
            "do_not_activate_trials_automatically": True,
            "do_not_purchase_automatically": True,
            "prefer_one_time_tickdata_store_quote_before_tickapi_subscription": (
                TICKDATA_NEW_CLIENT_MINIMUM_USD < tickapi_floor
            ),
            "no_total_cost_claim_until_external_quotes_and_databento_cost_probe_exist": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build planning-only cheap-first G2 acquisition sequence."
    )
    parser.add_argument("--vendor-dir", type=Path, default=DEFAULT_VENDOR_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = build(args.vendor_dir)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
