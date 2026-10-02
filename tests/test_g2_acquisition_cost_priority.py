from pathlib import Path

import g2_acquisition_cost_priority as priority


ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "data/processed/g2_vendor_requests"


def test_cheap_first_acquisition_priority_matches_current_scope():
    payload = priority.build(VENDOR_DIR)

    assert payload["champion_minimum_source_date_rows"] == 1242
    assert payload["canonical_full_g2_source_date_rows"] == 1656

    costs = payload["known_public_cost_floors"]
    assert costs["tickdata_datastore_new_client_minimum_usd"] == 1000.0
    assert costs["tickapi_estimated_first_year_minimum_usd"] == 3821.0

    routes = {item["route"]: item for item in payload["priority"]}
    assert routes["cboe_free_trial_capacity"]["rank"] == 1
    assert routes["cboe_free_trial_capacity"]["scope_source_date_rows_upper_bound"] == 81
    assert routes["cboe_free_trial_capacity"]["scope_symbol_date_pairs_upper_bound"] == 445
    assert routes["cboe_free_trial_capacity"]["automatic_activation_permitted"] is False

    assert routes["databento_opra_cost_probe"]["rank"] == 2
    assert routes["databento_opra_cost_probe"]["scope_source_date_rows"] == 226
    assert routes["databento_opra_cost_probe"]["scope_symbol_date_pairs"] == 2875
    assert routes["databento_opra_cost_probe"]["automatic_purchase_permitted"] is False

    assert routes["tickdata_one_time_datastore_equities"]["rank"] == 3
    assert routes["tickdata_one_time_datastore_equities"]["scope_source_date_rows"] == 828
    assert routes["tickdata_one_time_datastore_equities"]["scope_symbol_date_pairs"] == 7656

    assert routes["lseg_2011_opra_tick_history"]["rank"] == 4
    assert routes["lseg_2011_opra_tick_history"]["scope_source_date_rows"] == 105

    assert routes["cboe_paid_remainder_or_fallback"]["rank"] == 5
    assert routes["cboe_paid_remainder_or_fallback"][
        "scope_source_date_rows_if_trial_capacity_holds"
    ] == 2
    assert routes["cboe_paid_remainder_or_fallback"][
        "scope_symbol_date_pairs_if_trial_capacity_holds"
    ] == 44
    assert routes["cboe_paid_remainder_or_fallback"][
        "scope_source_date_rows_if_trial_unavailable"
    ] == 83

    assert payload["decision_rules"] == {
        "candidate_source_is_not_coverage": True,
        "do_not_activate_trials_automatically": True,
        "do_not_purchase_automatically": True,
        "prefer_one_time_tickdata_store_quote_before_tickapi_subscription": True,
        "no_total_cost_claim_until_external_quotes_and_databento_cost_probe_exist": True,
    }


def test_committed_acquisition_cost_priority_matches_generator():
    import json

    generated = priority.build(VENDOR_DIR)
    committed = json.loads(
        (VENDOR_DIR / "acquisition_cost_priority.json").read_text(encoding="utf-8")
    )
    assert generated == committed
