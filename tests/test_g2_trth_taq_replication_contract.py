import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "data/processed/g2_vendor_requests/trth_primary_taq_replication_contract.json"


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_trth_is_recorded_as_the_paper_primary_source_not_taq():
    payload = _contract()
    hierarchy = payload["source_hierarchy"]
    assert hierarchy["paper_used_taq"] is False
    assert "Tick History" in hierarchy["paper_primary_source"]
    assert hierarchy["taq_role"].startswith("Replication substitute")


def test_taq_quote_lane_remains_fail_closed_until_nbbo_is_proven():
    payload = _contract()
    assert payload["nbbo"]["g2_requirement"].startswith(
        "Any TAQ fallback used for the equity_quote lane"
    )
    assert payload["implementation_policy"]["taq_quote_lane_fail_closed_until_nbbo_proven"] is True


def test_after_hours_trade_conditions_match_companion_repository():
    payload = _contract()
    trades = payload["taq_after_hours_modifications"]["trades"]
    assert trades["exclude_conditions_under_tr_scon"] == ["L", "P", "U", "Z", "4"]
    assert trades["identify_after_hours_condition"] == "T"


def test_after_hours_quotes_preserve_liquidity_withdrawal_information():
    quotes = _contract()["taq_after_hours_modifications"]["quotes"]
    assert quotes["add_valid_qu_cond"] == ["C"]
    assert quotes["preserve_empty_quotes"] is True
    assert quotes["delete_crossed_markets"] is False
    assert quotes["delete_abnormal_spreads"] is False
    assert quotes["delete_withdrawn_quotes"] is False
