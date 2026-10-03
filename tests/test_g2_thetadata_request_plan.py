from pathlib import Path
import csv
import json

import g2_thetadata_request_plan as plan


ROOT = Path(__file__).resolve().parents[1]
OPTION_PARTITION = ROOT / "data/processed/g2_vendor_requests/cheap_route_partitions/thetadata_options.csv"
EQUITY_PARTITION = ROOT / "data/processed/g2_vendor_requests/cheap_route_partitions/thetadata_equity.csv"
COMMITTED_DIR = ROOT / "data/processed/g2_vendor_requests/thetadata_requests"


def test_thetadata_request_plan_matches_written_vendor_counts(tmp_path: Path):
    payload = plan.write_plan(OPTION_PARTITION, EQUITY_PARTITION, tmp_path)

    assert payload["option_requests"] == {
        "trade_requests": 3014,
        "quote_requests": 3014,
        "total_requests": 6028,
        "source_partition": str(OPTION_PARTITION),
        "output_file": "thetadata_option_requests.csv",
    }
    assert payload["stock_requests"] == {
        "trade_requests": 1430,
        "quote_requests": 1430,
        "total_requests": 2860,
        "source_partition": str(EQUITY_PARTITION),
        "output_file": "thetadata_stock_requests.csv",
    }
    assert payload["total_requests"] == 8888
    assert payload["execution"]["network_execution_enabled"] is False
    assert payload["subscription"]["subscription_authorized"] is False
    assert payload["subscription"]["purchase_authority"] is False
    assert payload["guardrails"]["network_execution_requires_explicit_user_authorization"] is True

    option_rows = list(csv.DictReader((tmp_path / "thetadata_option_requests.csv").open()))
    stock_rows = list(csv.DictReader((tmp_path / "thetadata_stock_requests.csv").open()))
    assert len(option_rows) == 6028
    assert len(stock_rows) == 2860

    assert sum(r["record_kind"] == "option_trade" for r in option_rows) == 3014
    assert sum(r["record_kind"] == "option_quote" for r in option_rows) == 3014
    assert sum(r["record_kind"] == "equity_trade" for r in stock_rows) == 1430
    assert sum(r["record_kind"] == "equity_quote" for r in stock_rows) == 1430

    assert all(r["request_status"] == "DRY_RUN_ONLY_NOT_AUTHORIZED" for r in option_rows + stock_rows)
    assert all(r["endpoint"] in {"option/history/trade", "option/history/quote"} for r in option_rows)
    assert all(r["endpoint"] in {"stock/history/trade", "stock/history/quote"} for r in stock_rows)

    option_quotes = [r for r in option_rows if r["record_kind"] == "option_quote"]
    stock_quotes = [r for r in stock_rows if r["record_kind"] == "equity_quote"]
    assert all(r["interval"] == "tick" for r in option_quotes)
    assert all("expiration=*" in r["contract_scope"] for r in option_quotes)
    assert all(r["interval"] == "tick" and r["venue"] == "utp_cta" for r in stock_quotes)


def test_committed_thetadata_request_manifests_match_generator(tmp_path: Path):
    payload = plan.write_plan(OPTION_PARTITION, EQUITY_PARTITION, tmp_path)

    for filename in ("thetadata_option_requests.csv", "thetadata_stock_requests.csv"):
        assert (tmp_path / filename).read_bytes() == (COMMITTED_DIR / filename).read_bytes()

    assert json.loads((tmp_path / "thetadata_request_summary.json").read_text()) == json.loads(
        (COMMITTED_DIR / "thetadata_request_summary.json").read_text()
    )
    assert payload == json.loads((COMMITTED_DIR / "thetadata_request_summary.json").read_text())
