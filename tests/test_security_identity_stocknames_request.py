from __future__ import annotations

import copy
import csv
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import security_identity_stocknames_request as request


CSV_PATH = ROOT / request.DEFAULT_REQUEST_CSV
SQL_PATH = ROOT / request.DEFAULT_REQUEST_SQL
SUMMARY_PATH = ROOT / request.DEFAULT_REQUEST_SUMMARY


def test_committed_stocknames_request_outputs_reproduce_byte_for_byte():
    csv_text, sql_text, summary_text = request.build_from_path(
        ROOT / request.DEFAULT_ACQUISITION_SUMMARY
    )
    assert csv_text == CSV_PATH.read_text(encoding="utf-8")
    assert sql_text == SQL_PATH.read_text(encoding="utf-8")
    assert summary_text == SUMMARY_PATH.read_text(encoding="utf-8")


def test_request_scope_is_exactly_146_permnos_and_3654_dates():
    rows = list(csv.DictReader(io.StringIO(CSV_PATH.read_text(encoding="utf-8"))))
    assert len(rows) == 146
    assert len({row["permno"] for row in rows}) == 146
    assert len({row["historical_symbol"] for row in rows}) == 146
    assert sum(int(row["request_count"]) for row in rows) == 3654
    assert min(row["first_required_date"] for row in rows) == "2011-03-21"
    assert max(row["last_required_date"] for row in rows) == "2015-05-19"


def test_sql_is_dated_permno_history_request_not_symbol_only_shortcut():
    sql = SQL_PATH.read_text(encoding="utf-8")
    assert "FROM crsp.stocknames AS n" in sql
    assert "ON n.permno = r.permno" in sql
    assert "n.namedt <= r.max_required_date" in sql
    assert "COALESCE(n.nameenddt, DATE '9999-12-31')" in sql
    assert "CURRENT_DATE" not in sql
    assert "n.ticker = r.historical_symbol" not in sql
    assert sql.count("DATE '") == 146 * 2 + 1


def test_summary_locks_authorization_and_no_bypass_policy():
    payload = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    state = payload["state"]
    policy = payload["authorization_policy"]
    assert state["unresolved_permno_date_requests"] == 3654
    assert state["unique_permno_count"] == 146
    assert state["first_required_date"] == "2011-03-21"
    assert state["last_required_date"] == "2015-05-19"
    assert policy["requires_authorized_source"] is True
    assert policy["public_or_unverified_mirror_may_not_close_gate"] is True
    assert policy["current_ticker_substitution_prohibited"] is True
    assert policy["authentication_or_entitlement_bypass_prohibited"] is True


def test_request_builder_rejects_count_drift_and_duplicate_permnos():
    payload = request.load_acquisition_summary(
        ROOT / request.DEFAULT_ACQUISITION_SUMMARY
    )
    bad_count = copy.deepcopy(payload)
    bad_count["securities"][0]["request_count"] += 1
    with pytest.raises(request.StocknamesRequestError, match="request_count sum mismatch"):
        request.build_request(bad_count)

    duplicate = copy.deepcopy(payload)
    duplicate["securities"][1]["permno"] = duplicate["securities"][0]["permno"]
    with pytest.raises(request.StocknamesRequestError, match="duplicate PERMNO"):
        request.build_request(duplicate)


def test_request_builder_rejects_ready_or_empty_state():
    payload = request.load_acquisition_summary(
        ROOT / request.DEFAULT_ACQUISITION_SUMMARY
    )
    ready = copy.deepcopy(payload)
    ready["state"]["ready_for_non_synthetic_market_join"] = True
    with pytest.raises(request.StocknamesRequestError, match="non-ready unresolved"):
        request.build_request(ready)

    empty = copy.deepcopy(payload)
    empty["securities"] = []
    with pytest.raises(request.StocknamesRequestError):
        request.build_request(empty)
