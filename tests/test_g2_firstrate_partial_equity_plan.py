from pathlib import Path

import g2_firstrate_partial_equity_plan as planner


ROOT = Path(__file__).resolve().parents[1]
TRADE = ROOT / "data/processed/g2_vendor_requests/tickdata_equity_trades.csv"
QUOTE = ROOT / "data/processed/g2_vendor_requests/tickdata_equity_nbbo_quotes.csv"
SNAPSHOT = ROOT / "data/processed/g2_vendor_requests/firstrate_public_sample_snapshot.json"


def test_firstrate_partial_equity_plan_matches_public_snapshot():
    result = planner.build_plan(
        planner._read_csv(TRADE),
        planner._read_csv(QUOTE),
        planner._read_json(SNAPSHOT),
    )

    assert result["status"] == "PARTIAL_CANDIDATE_ONLY"
    assert result["required_equity_source_date_rows"] == 828
    assert result["required_equity_symbol_date_pairs_per_record_kind"] == 3828
    assert result["direct_present_unique_symbols"] == 106
    assert result["direct_absent_unique_symbols"] == 40
    assert result["direct_symbol_date_pairs_per_record_kind"] == 2750
    assert result["missing_symbol_date_pairs_per_record_kind"] == 1078
    assert result["direct_record_kind_symbol_date_pairs"] == 5500
    assert result["missing_record_kind_symbol_date_pairs"] == 2156
    assert result["direct_pair_fraction"] == 2750 / 3828
    assert result["dates_with_any_direct_symbols"] == 363
    assert result["fully_direct_dates"] == 118
    assert result["dates_with_no_direct_symbols"] == 51
    assert result["fully_direct_source_date_rows"] == 236
    assert result["public_sample_schema_supports_required_quote_sizes"] is True
    assert result["delisted_tickers_supported_by_tick_service"] is False
    assert result["pricing_structure_fully_resolved"] is False


def test_firstrate_plan_stays_fail_closed_on_missing_symbols():
    result = planner.build_plan(
        planner._read_csv(TRADE),
        planner._read_csv(QUOTE),
        planner._read_json(SNAPSHOT),
    )

    assert result["policy"] == {
        "alias_inference_not_counted": True,
        "missing_symbols_require_another_authorized_source": True,
        "partial_files_do_not_count_as_complete_source_dates_by_themselves": True,
        "license_and_production_validation_required": True,
    }
    assert sum(row["missing_symbol_count"] for row in result["per_date"]) == 1078
    assert sum(row["direct_present_symbol_count"] for row in result["per_date"]) == 2750
