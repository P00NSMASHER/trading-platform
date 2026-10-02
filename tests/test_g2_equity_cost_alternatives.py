from pathlib import Path
import json

import g2_equity_cost_alternatives as alternatives


ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "data/processed/g2_vendor_requests/equity_cost_alternatives.json"


def test_equity_cost_alternatives_preserve_license_gates():
    payload = alternatives.build_alternatives()

    assert payload["equity_scope"] == {
        "source_date_rows": 828,
        "trade_rows": 414,
        "quote_rows": 414,
        "record_kind_symbol_date_pairs": 7656,
        "historical_range": ["2011-03-21", "2015-05-20"],
    }

    by_vendor = {item["vendor"]: item for item in payload["alternatives"]}

    assert by_vendor["Tick Data"]["estimated_first_year_minimum_usd"] == 3821.00
    assert by_vendor["Tick Data"]["route_status"] == "CURRENT_PREFERRED_CANDIDATE"

    assert by_vendor["Massive Stocks Advanced"]["public_monthly_price_usd"] == 199.00
    assert by_vendor["Massive Stocks Advanced"]["coverage_fit"] == "FULL_SCOPE_TECHNICAL_FIT"
    assert by_vendor["Massive Stocks Advanced"]["license_fit"] == "WRITTEN_TERMS_CLEARANCE_REQUIRED"

    assert by_vendor["Massive Stocks Business"]["public_monthly_price_usd"] == 2499.00
    assert by_vendor["Massive Stocks Business"]["license_fit"] == "ORDER_TERMS_AND_RETENTION_REVIEW_REQUIRED"

    assert by_vendor["FirstRate Data TickHistory"]["coverage_fit"] == "INCOMPLETE_FROZEN_SYMBOL_UNIVERSE"
    assert by_vendor["FirstRate Data TickHistory"]["license_fit"] == "RESEARCH_FRIENDLY"

    assert payload["policy"] == {
        "do_not_replace_preferred_route_without_license_clearance": True,
        "candidate_is_not_coverage": True,
        "do_not_purchase_automatically": True,
    }


def test_committed_equity_cost_alternatives_match_generator():
    assert json.loads(COMMITTED.read_text(encoding="utf-8")) == alternatives.build_alternatives()
