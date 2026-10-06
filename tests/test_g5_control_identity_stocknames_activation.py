from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_control_identity_stocknames_activation as activation


IDENTITY_HEADER = (
    "historical_symbol,trade_date,canonical_g2_overlap,canonical_permno,"
    "samplefirms_permno,research_use_only\n"
)
EXPANDED_HEADER = (
    "request_id,permno,historical_symbol,trade_date,hint_source,"
    "identity_status,research_use_only\n"
)
STOCKNAMES_HEADER = "permno,ticker,namedt,nameenddt\n"


def _identity_queue(tmp_path: Path) -> Path:
    path = tmp_path / "identity_queue.csv"
    path.write_text(
        IDENTITY_HEADER
        + "AAA,2015-01-02,CANONICAL_G2_UNVERIFIED,11111,,1\n"
        + "BBB,2015-01-03,NONE,,22222,1\n",
        encoding="utf-8",
    )
    return path


def _expanded_queue(tmp_path: Path, *, include_bbb: bool = True) -> Path:
    path = tmp_path / "expanded.csv"
    body = (
        "G5SID-A,11111,AAA,2015-01-02,CANONICAL_G2_PERMNO,"
        "OVERLAPS_CANONICAL_G2_IDENTITY_QUEUE,1\n"
    )
    if include_bbb:
        body += (
            "G5SID-B,22222,BBB,2015-01-03,SAMPLEFIRMS_PERMNO,"
            "PUBLIC_EXACT_MAPPING_AVAILABLE_REQUIRES_ADMISSION,1\n"
        )
    path.write_text(EXPANDED_HEADER + body, encoding="utf-8")
    return path


def _stocknames(tmp_path: Path, *, include_bbb: bool = True) -> Path:
    path = tmp_path / "stocknames.csv"
    body = "11111,AAA,2015-01-01,2015-01-31\n"
    if include_bbb:
        body += "22222,BBB,2015-01-01,2015-01-31\n"
    path.write_text(STOCKNAMES_HEADER + body, encoding="utf-8")
    return path


def test_complete_authorized_stocknames_activation_routes_g2_and_g5_evidence(
    tmp_path: Path,
):
    out = tmp_path / "out"
    summary = activation.build(
        identity_queue_path=_identity_queue(tmp_path),
        expanded_stocknames_queue_path=_expanded_queue(tmp_path),
        stocknames_path=_stocknames(tmp_path),
        authorization_reference="AUTHORIZED-TEST",
        output_dir=out,
    )

    assert summary["counts"] == {
        "identity_queue_count": 2,
        "expanded_stocknames_request_count": 2,
        "stocknames_source_row_count": 2,
        "adapter_evidence_row_count": 2,
        "adapter_unresolved_request_count": 0,
        "g5_only_staged_verified_count": 1,
        "g5_only_remaining_count": 0,
        "canonical_g2_forward_evidence_row_count": 1,
    }
    assert summary["all_routable_dates_evidence_ready"] is True
    assert summary["g5_only_identity_staging_complete"] is True
    assert summary["overall_g5_identity_ready_claimed"] is False
    assert summary["data_fetch_performed"] is False
    assert summary["purchase_performed"] is False
    assert summary["canonical_g2_write_performed"] is False
    assert summary["canonical_g5_write_performed"] is False
    assert summary["coverage_promoted"] is False
    assert summary["release_claimed"] is False

    evidence = list(
        csv.DictReader(
            (
                out
                / "normalized/g5_control_identity_stocknames_evidence.csv"
            ).open(encoding="utf-8")
        )
    )
    assert [(row["historical_symbol"], row["valid_from"]) for row in evidence] == [
        ("AAA", "2015-01-02"),
        ("BBB", "2015-01-03"),
    ]

    staged = list(
        csv.DictReader(
            (
                out
                / "staging/g5_control_identity_staged_verified.csv"
            ).open(encoding="utf-8")
        )
    )
    forwarded = list(
        csv.DictReader(
            (
                out
                / "staging/g5_control_identity_g2_forward_evidence.csv"
            ).open(encoding="utf-8")
        )
    )
    assert [(row["historical_symbol"], row["trade_date"]) for row in staged] == [
        ("BBB", "2015-01-03")
    ]
    assert [row["historical_symbol"] for row in forwarded] == ["AAA"]


def test_partial_authorized_stocknames_history_stays_fail_closed(tmp_path: Path):
    summary = activation.build(
        identity_queue_path=_identity_queue(tmp_path),
        expanded_stocknames_queue_path=_expanded_queue(tmp_path),
        stocknames_path=_stocknames(tmp_path, include_bbb=False),
        authorization_reference="AUTHORIZED-TEST",
        output_dir=tmp_path / "out",
    )

    assert summary["counts"]["adapter_evidence_row_count"] == 1
    assert summary["counts"]["adapter_unresolved_request_count"] == 1
    assert summary["counts"]["canonical_g2_forward_evidence_row_count"] == 1
    assert summary["counts"]["g5_only_staged_verified_count"] == 0
    assert summary["counts"]["g5_only_remaining_count"] == 1
    assert summary["all_routable_dates_evidence_ready"] is False
    assert summary["g5_only_identity_staging_complete"] is False
    assert summary["overall_g5_identity_ready_claimed"] is False
    assert summary["coverage_promoted"] is False


def test_expanded_queue_must_exactly_match_identity_scope(tmp_path: Path):
    with pytest.raises(
        activation.G5StocknamesActivationError,
        match="does not exactly match",
    ):
        activation.build(
            identity_queue_path=_identity_queue(tmp_path),
            expanded_stocknames_queue_path=_expanded_queue(
                tmp_path,
                include_bbb=False,
            ),
            stocknames_path=tmp_path / "unused.csv",
            authorization_reference="AUTHORIZED-TEST",
            output_dir=tmp_path / "out",
        )
