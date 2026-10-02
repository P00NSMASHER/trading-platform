import json
from pathlib import Path

import g2_equity_route_break_even as plan


ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "data/processed/g2_vendor_requests/equity_route_break_even.json"


def test_equity_route_break_even_is_fail_closed():
    payload = plan.build_break_even()

    assert payload["scope"]["full_tickdata"] == {
        "unique_symbols": 146,
        "symbol_years": 193,
    }
    assert payload["scope"]["combined_route_tickdata_residual"] == {
        "unique_symbols": 61,
        "symbol_years": 82,
    }
    assert payload["scope"]["firstrate_additional_tickers"] == 31

    prices = payload["public_price_inputs"]
    assert prices["firstrate_10_plus_price_per_ticker_usd"] == 19.95
    assert prices["firstrate_31_ticker_indicative_cost_usd"] == 618.45
    assert prices["theta_stocks_incremental_bundle_cost_usd"] is None
    assert prices["tickdata_full_data_store_quote_usd"] is None
    assert prices["tickdata_residual_data_store_quote_usd"] is None

    tickapi = payload["tickapi_comparison"]
    assert tickapi["full_scope_first_year_usd"] == 3821.00
    assert tickapi["residual_first_year_usd"] == 3338.66
    assert tickapi["residual_plus_firstrate_before_theta_usd"] == 3957.11
    assert tickapi["combined_minus_full_before_theta_usd"] == 136.11
    assert tickapi["combined_route_can_beat_full_tickapi_with_nonnegative_theta_cost"] is False
    assert tickapi["decision"] == "REJECT_COMBINED_ROUTE_FOR_TICKAPI_COST_OPTIMIZATION"

    store = payload["data_store_break_even"]
    assert store["new_client_combined_known_floor_before_theta_delivery_tax_usd"] == 1618.45
    assert store["returning_client_combined_known_floor_before_theta_delivery_tax_usd"] == 1118.45
    assert store["status"] == "AWAIT_EXACT_TICKDATA_AND_THETADATA_QUOTES"

    assert payload["policy"]["do_not_switch_route_automatically"] is True
    assert payload["policy"]["do_not_purchase_automatically"] is True
    assert payload["policy"]["validated_g2_coverage_unchanged"] is True


def test_committed_equity_route_break_even_matches_generator():
    assert json.loads(COMMITTED.read_text(encoding="utf-8")) == plan.build_break_even()
