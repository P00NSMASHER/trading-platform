import csv
from pathlib import Path

import g2_vendor_delivery_preflight as preflight


REQUEST_FIELDS = [
    "trade_date",
    "record_kind",
    "historical_symbols",
    "unique_symbol_count",
    "symbol_date_pair_count",
    "route",
]

INVENTORY_FIELDS = [
    "path",
    "relative_path",
    "size_bytes",
    "sha256",
    "file_kind",
    "readable_header",
    "detected_trade_date",
    "candidate_record_kind",
    "candidate_source_family",
    "candidate_format_version",
    "confidence",
    "status",
    "reason",
    "header_fields",
    "proposed_column_map",
    "research_use_only",
]


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _request(day: str) -> dict:
    return {
        "trade_date": day,
        "record_kind": "option_trade",
        "historical_symbols": "AAA;BBB",
        "unique_symbol_count": "2",
        "symbol_date_pair_count": "2",
        "route": "candidate_databento_opra_trades",
    }


def _inventory(day: str, *, status: str, sha: str, family: str = "generic_authorized_market_data") -> dict:
    return {
        "path": f"/drop/databento_opra_trades_{day.replace('-', '')}.csv",
        "relative_path": f"databento_opra_trades_{day.replace('-', '')}.csv",
        "size_bytes": "100",
        "sha256": sha,
        "file_kind": "delimited_text",
        "readable_header": "1",
        "detected_trade_date": day,
        "candidate_record_kind": "option_trade",
        "candidate_source_family": family,
        "candidate_format_version": "",
        "confidence": "high",
        "status": status,
        "reason": "fixture",
        "header_fields": "",
        "proposed_column_map": "{}",
        "research_use_only": "1",
    }


def test_delivery_preflight_stays_blocked_on_missing_schema_and_unexpected_rows(tmp_path: Path):
    request = tmp_path / "request.csv"
    inventory = tmp_path / "inventory.csv"
    _write_csv(request, REQUEST_FIELDS, [_request("2015-04-01"), _request("2015-04-02"), _request("2015-04-03")])
    _write_csv(
        inventory,
        INVENTORY_FIELDS,
        [
            _inventory(
                "2015-04-01",
                status="PENDING_AUTHORIZATION_AND_REVIEW",
                sha="a" * 64,
            ),
            _inventory(
                "2015-04-02",
                status="PENDING_SCHEMA_MAPPING",
                sha="b" * 64,
            ),
            _inventory(
                "2015-04-04",
                status="PENDING_AUTHORIZATION_AND_REVIEW",
                sha="c" * 64,
            ),
        ],
    )

    result = preflight.preflight(request, inventory)

    assert result["requested_source_date_rows"] == 3
    assert result["requested_symbol_date_pairs"] == 6
    assert result["present_pending_authorization_rows"] == 1
    assert result["present_schema_blocked_rows"] == 1
    assert result["missing_delivery_rows"] == 1
    assert result["unexpected_delivery_dates"] == ["2015-04-04"]
    assert result["ready_for_entitlement_review"] is False
    assert result["coverage_policy"]["g2_coverage_counted"] is False
    assert result["coverage_policy"]["required_symbol_content_validated"] is False


def test_delivery_preflight_can_be_ready_for_review_without_counting_coverage(tmp_path: Path):
    request = tmp_path / "request.csv"
    inventory = tmp_path / "inventory.csv"
    _write_csv(request, REQUEST_FIELDS, [_request("2015-04-01"), _request("2015-04-02")])
    _write_csv(
        inventory,
        INVENTORY_FIELDS,
        [
            _inventory(
                "2015-04-01",
                status="PENDING_AUTHORIZATION_AND_REVIEW",
                sha="a" * 64,
            ),
            _inventory(
                "2015-04-02",
                status="PENDING_AUTHORIZATION_AND_REVIEW",
                sha="b" * 64,
            ),
        ],
    )

    result = preflight.preflight(request, inventory)

    assert result["present_pending_authorization_rows"] == 2
    assert result["present_schema_blocked_rows"] == 0
    assert result["missing_delivery_rows"] == 0
    assert result["unexpected_delivery_dates"] == []
    assert result["ready_for_entitlement_review"] is True
    assert result["coverage_policy"] == {
        "authorization_validated": False,
        "license_validated": False,
        "required_symbol_content_validated": False,
        "g2_coverage_counted": False,
        "file_presence_alone_is_never_coverage": True,
    }


def test_wrong_vendor_family_does_not_satisfy_request(tmp_path: Path):
    request = tmp_path / "request.csv"
    inventory = tmp_path / "inventory.csv"
    _write_csv(request, REQUEST_FIELDS, [_request("2015-04-01")])
    _write_csv(
        inventory,
        INVENTORY_FIELDS,
        [
            _inventory(
                "2015-04-01",
                status="PENDING_AUTHORIZATION_AND_REVIEW",
                sha="a" * 64,
                family="cboe_option_trades",
            )
        ],
    )

    result = preflight.preflight(request, inventory)
    assert result["missing_delivery_rows"] == 1
    assert result["ready_for_entitlement_review"] is False


def test_full_replication_option_quote_routes_are_supported(tmp_path: Path):
    for index, route in enumerate(
        (
            "candidate_lseg_opra_tick_history_option_quotes",
            "candidate_thetadata_options_pro_option_quotes",
        )
    ):
        request = tmp_path / f"request_{index}.csv"
        inventory = tmp_path / f"inventory_{index}.csv"
        _write_csv(
            request,
            REQUEST_FIELDS,
            [{
                "trade_date": "2015-03-20",
                "record_kind": "option_quote",
                "historical_symbols": "AAA;BBB",
                "unique_symbol_count": "2",
                "symbol_date_pair_count": "2",
                "route": route,
            }],
        )
        _write_csv(
            inventory,
            INVENTORY_FIELDS,
            [{
                "path": f"/drop/option_quotes_{index}.csv",
                "relative_path": f"option_quotes_{index}.csv",
                "size_bytes": "100",
                "sha256": "d" * 64,
                "file_kind": "delimited_text",
                "readable_header": "1",
                "detected_trade_date": "2015-03-20",
                "candidate_record_kind": "option_quote",
                "candidate_source_family": "generic_authorized_market_data",
                "candidate_format_version": "",
                "confidence": "high",
                "status": "PENDING_AUTHORIZATION_AND_REVIEW",
                "reason": "fixture",
                "header_fields": "",
                "proposed_column_map": "{}",
                "research_use_only": "1",
            }],
        )

        result = preflight.preflight(request, inventory)

        assert result["route"] == route
        assert result["expected_record_kind"] == "option_quote"
        assert result["expected_source_family"] == "generic_authorized_market_data"
        assert result["requested_source_date_rows"] == 1
        assert result["requested_symbol_date_pairs"] == 2
        assert result["present_pending_authorization_rows"] == 1
        assert result["ready_for_entitlement_review"] is True
        assert result["coverage_policy"]["g2_coverage_counted"] is False
