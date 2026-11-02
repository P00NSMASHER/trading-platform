from pathlib import Path

import g2_lseg_datascope_execution_plan as execution
import g2_lseg_request_manifest as manifest


ROOT = Path(__file__).resolve().parents[1]


def _base_plan():
    return manifest.build_plan(
        manifest._read_csv(ROOT / "data/processed/g2_vendor_requests/lseg_equity_ric_mapping.csv"),
        manifest._read_csv(ROOT / "data/processed/g2_vendor_requests/lseg_secondary_ric_candidates.csv"),
        manifest._read_csv(ROOT / "data/processed/g2_vendor_requests/lseg_event_permno_ric_mapping.csv"),
        manifest._read_csv(ROOT / "data/processed/real_data_release_sprint/g2_core_source_date_requirements.csv"),
        manifest._read_csv(ROOT / "data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv"),
    )


def _plan():
    return execution.build_execution_plan(_base_plan())


def test_collapses_frozen_trade_quote_requirements_without_losing_symbol_dates():
    plan = _plan()
    summary = plan["summary"]

    assert summary["frozen_source_dates"] == 414
    assert summary["equity_source_date_rows"] == 828
    assert summary["option_source_date_rows"] == 828
    assert summary["original_symbol_kind_date_requests"] == 15312

    assert summary["equity_unique_symbol_dates"] == 3828
    assert summary["option_unique_underlying_dates"] == 3828
    assert summary["equity_time_and_sales_date_batches"] == 414
    assert summary["option_underlying_discovery_tasks"] == 3828
    assert summary["option_time_and_sales_date_batches_after_discovery_max"] == 414

    # 44 root-only + 902 secondary unique symbol-dates per lane.
    assert summary["historical_validation_required_equity_symbol_dates"] == 946
    assert summary["historical_validation_required_option_underlying_dates"] == 946

    assert len(plan["equity_historical_validation_queue"]) == 946
    assert len(plan["option_historical_validation_queue"]) == 946
    assert all(
        row["historical_validation_required"] is True
        for row in plan["equity_historical_validation_queue"]
    )
    assert all(
        row["historical_validation_required"] is True
        for row in plan["option_historical_validation_queue"]
    )
    assert len({
        (row["trade_date"], row["historical_symbol"])
        for row in plan["equity_historical_validation_queue"]
    }) == 946
    assert len({
        (row["trade_date"], row["historical_symbol"])
        for row in plan["option_historical_validation_queue"]
    }) == 946


def test_each_collapsed_symbol_date_preserves_both_required_record_kinds():
    plan = _plan()

    assert all(
        row["record_kinds"] == ["equity_quote", "equity_trade"]
        for row in plan["equity_symbol_dates"]
    )
    assert all(
        row["record_kinds"] == ["option_quote", "option_trade"]
        for row in plan["option_underlying_dates"]
    )


def test_equity_batches_use_single_time_and_sales_request_contract_per_date():
    plan = _plan()
    first = plan["equity_date_batches"][0]

    assert first["trade_date"] == "2011-03-21"
    assert first["historical_symbols"] == ["JNPR", "VMW"]
    assert first["report_type"] == "TickHistoryTimeAndSales"
    assert first["content_fields"] == execution.TIME_AND_SALES_FIELDS
    assert first["identifier_validation"]["AllowHistoricalInstruments"] is True
    assert first["condition"]["QueryStartDate"] == "2011-03-21T00:00:00.000000000"
    assert first["condition"]["QueryEndDate"] == "2011-03-21T23:59:59.999999999"


def test_option_discovery_emits_exact_per_candidate_underlying_search_requests():
    plan = _plan()
    first = plan["option_discovery_tasks"][0]

    assert first["trade_date"] == "2011-03-21"
    methods = {item["method"]: item for item in first["discovery_methods"]}
    search = methods["futures_and_options_search"]

    requests = search["requests"]
    assert requests
    assert all(
        "UnderlyingRic" in request["SearchRequest"]
        and "UnderlyingRicCandidates" not in request["SearchRequest"]
        for request in requests
    )
    assert all(
        request["SearchRequest"]["ExpirationDate"] == {
            "ComparisonOperator": "GreaterThanEquals",
            "Value": "2011-03-21",
        }
        for request in requests
    )


def test_historical_chain_discovery_stays_date_scoped_and_candidate_only():
    plan = _plan()
    task = next(
        row for row in plan["option_discovery_tasks"]
        if row["historical_symbol"] == "ACHC"
    )
    methods = {item["method"]: item for item in task["discovery_methods"]}
    historical = methods["historical_chain_resolution"]

    assert historical["endpoint"] == "/RestApi/v1/Search/HistoricalChainResolution"
    assert historical["range"]["Start"].startswith(task["trade_date"])
    assert historical["range"]["End"].startswith(task["trade_date"])
    assert historical["chain_pattern_candidates"]
    assert task["historical_validation_required"] is True


def test_execution_plan_is_credential_free_and_private_output_fail_closed():
    plan = _plan()

    assert "No network call" in plan["purpose"]
    assert "credential read" in plan["purpose"]
    assert (
        plan["private_output_policy"]["raw_licensed_rows"]
        == "write only to an ignored/private local destination"
    )
    assert "SHA-256 receipts" in plan["private_output_policy"]["public_repository"]
