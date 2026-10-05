from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_external_metadata_adapter as adapter


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_file(tmp_path: Path) -> Path:
    path = tmp_path / "candidates.csv"
    path.write_text(
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc\n"
        "2015-02-17,C1,2015-02-17T19:19:00Z\n"
        "2015-02-17,C2,2015-02-17T19:19:00Z\n",
        encoding="utf-8",
    )
    return path


def _normalize(tmp_path: Path, *, lane: str, body: str):
    candidates = _candidate_file(tmp_path)
    source = tmp_path / f"{lane}.csv"
    source.write_text(body, encoding="utf-8")
    return adapter.normalize(
        lane=lane,
        candidate_path=candidates,
        source_path=source,
        expected_source_sha256=_sha(source),
        authorization_reference="AUTHORIZED-G5-TEST",
        source_name=f"test-{lane}",
    )


def test_classification_aliases_normalize_pre_cutoff(tmp_path: Path):
    rows, summary = _normalize(
        tmp_path,
        lane="classification",
        body=(
            "date,ticker,effective_timestamp,gsector,index_membership\n"
            "2015-02-17,C1,2015-02-17T18:00:00Z,45,SP500\n"
        ),
    )

    assert rows == [{
        "event_date": "2015-02-17",
        "symbol": "C1",
        "effective_ts_utc": "2015-02-17T18:00:00Z",
        "sector": "45",
        "index_bucket": "SP500",
        "institutional_ownership": "",
        "analyst_coverage": "",
        "borrow_cost": "",
        "source_name": "test-classification",
        "authorization_reference": "AUTHORIZED-G5-TEST",
        "research_use_only": "1",
    }]
    assert summary["covered_candidate_symbol_dates"] == 1
    assert summary["accepted_field_counts"] == {
        "index_bucket": 1,
        "sector": 1,
    }
    assert summary["g5_dates_resolved_change"] == 0
    assert summary["eligible_g5_evidence"] is False
    assert summary["release_claimed"] is False


@pytest.mark.parametrize(
    ("lane", "source_field", "canonical_field", "value"),
    [
        ("ownership", "IO", "institutional_ownership", "0.6125"),
        ("analyst", "numest", "analyst_coverage", "14"),
        ("borrow", "DCBS", "borrow_cost", "3"),
    ],
)
def test_numeric_alias_lanes_normalize(
    tmp_path: Path,
    lane: str,
    source_field: str,
    canonical_field: str,
    value: str,
):
    rows, summary = _normalize(
        tmp_path,
        lane=lane,
        body=(
            f"event_date,symbol,effective_ts_utc,{source_field}\n"
            f"2015-02-17,C1,2015-02-17T18:00:00Z,{value}\n"
        ),
    )

    assert rows[0][canonical_field] == value
    assert summary["accepted_field_counts"] == {canonical_field: 1}


def test_after_cutoff_row_fails_closed(tmp_path: Path):
    with pytest.raises(adapter.G5ExternalMetadataError, match="after the event cutoff"):
        _normalize(
            tmp_path,
            lane="analyst",
            body=(
                "event_date,symbol,effective_ts_utc,numest\n"
                "2015-02-17,C1,2015-02-17T20:00:00Z,10\n"
            ),
        )


def test_unknown_candidate_fails_closed(tmp_path: Path):
    with pytest.raises(adapter.G5ExternalMetadataError, match="not in the primary candidate queue"):
        _normalize(
            tmp_path,
            lane="borrow",
            body=(
                "event_date,symbol,effective_ts_utc,DCBS\n"
                "2015-02-17,NOTQUEUED,2015-02-17T18:00:00Z,2\n"
            ),
        )


def test_source_hash_mismatch_fails_closed(tmp_path: Path):
    candidates = _candidate_file(tmp_path)
    source = tmp_path / "ownership.csv"
    source.write_text(
        "event_date,symbol,effective_ts_utc,IO\n"
        "2015-02-17,C1,2015-02-17T18:00:00Z,0.5\n",
        encoding="utf-8",
    )

    with pytest.raises(adapter.G5ExternalMetadataError, match="SHA-256 mismatch"):
        adapter.normalize(
            lane="ownership",
            candidate_path=candidates,
            source_path=source,
            expected_source_sha256="0" * 64,
            authorization_reference="AUTHORIZED-G5-TEST",
            source_name="test-ownership",
        )


@pytest.mark.parametrize("column", ["Hacked", "Actual", "Soft", "post_event_return"])
def test_retrospective_or_post_event_columns_are_rejected(
    tmp_path: Path,
    column: str,
):
    with pytest.raises(
        adapter.G5ExternalMetadataError,
        match="prohibited retrospective/post-event columns",
    ):
        _normalize(
            tmp_path,
            lane="analyst",
            body=(
                f"event_date,symbol,effective_ts_utc,numest,{column}\n"
                "2015-02-17,C1,2015-02-17T18:00:00Z,12,0\n"
            ),
        )


def test_equal_timestamp_conflicting_value_fails_closed(tmp_path: Path):
    with pytest.raises(adapter.G5ExternalMetadataError, match="conflicting analyst_coverage"):
        _normalize(
            tmp_path,
            lane="analyst",
            body=(
                "event_date,symbol,effective_ts_utc,numest\n"
                "2015-02-17,C1,2015-02-17T18:00:00Z,10\n"
                "2015-02-17,C1,2015-02-17T18:00:00Z,11\n"
            ),
        )


def test_write_outputs_preserves_non_evidence_status(tmp_path: Path):
    rows, summary = _normalize(
        tmp_path,
        lane="borrow",
        body=(
            "event_date,symbol,effective_ts_utc,DCBS\n"
            "2015-02-17,C1,2015-02-17T18:00:00Z,4\n"
        ),
    )
    output = tmp_path / "normalized.csv"
    receipt = tmp_path / "summary.json"

    adapter.write_outputs(
        rows,
        summary,
        output_path=output,
        summary_path=receipt,
    )

    written = list(csv.DictReader(output.open(encoding="utf-8")))
    saved = json.loads(receipt.read_text(encoding="utf-8"))
    assert written[0]["borrow_cost"] == "4"
    assert saved["g5_dates_resolved_change"] == 0
    assert saved["eligible_g5_evidence"] is False
    assert saved["release_claimed"] is False
