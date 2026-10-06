from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_external_metadata_adapter as adapter
import g5_sec_sic_classification as sec


def _targets(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "targets.csv"
    path.write_text(
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc,"
        "research_use_only\n" + body,
        encoding="utf-8",
    )
    return path


def _cik_map(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "cik.csv"
    path.write_text(
        "historical_symbol,cik,valid_from,valid_through\n" + body,
        encoding="utf-8",
    )
    return path


def _submission(accessions, filing_dates, forms, files=None):
    return {
        "filings": {
            "recent": {
                "accessionNumber": accessions,
                "filingDate": filing_dates,
                "form": forms,
            },
            "files": files or [],
        }
    }


def _filing_text(*, accepted: str, sic: str) -> str:
    return (
        "<ACCEPTANCE-DATETIME>" + accepted + "\n"
        "COMPANY CONFORMED NAME: TEST CORP\n"
        "STANDARD INDUSTRIAL CLASSIFICATION: SERVICES [" + sic + "]\n"
    )


def test_pre_cutoff_sec_sic_is_namespaced_and_adapter_compatible(tmp_path: Path):
    targets = _targets(
        tmp_path,
        "2015-01-05,AAA,2015-01-05T18:00:00Z,1\n",
    )
    cik_map = _cik_map(
        tmp_path,
        "AAA,12345,2010-01-01,2020-12-31\n",
    )

    accession = "0000012345-15-000001"
    submissions = _submission(
        [accession],
        ["2015-01-05"],
        ["10-Q"],
    )

    def fetch_json(url: str):
        assert url.endswith("CIK0000012345.json")
        return submissions

    def fetch_text(url: str):
        assert accession.replace("-", "") in url
        return _filing_text(accepted="20150105170000", sic="7370")

    out = tmp_path / "out"
    summary = sec.build(
        targets_path=targets,
        cik_map_path=cik_map,
        output_dir=out,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    )

    assert summary["resolved_sector_target_count"] == 1
    assert summary["unresolved_target_count"] == 0
    assert summary["canonical_g5_dates_resolved_change"] == 0
    rows = list(
        csv.DictReader(
            (out / "g5_sec_sic_classification_source.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert rows[0]["sector"] == "SEC_SIC_DIVISION_I"
    assert rows[0]["sic_code"] == "7370"
    assert rows[0]["effective_ts_utc"] == "2015-01-05T17:00:00Z"

    normalized, receipt = adapter.normalize(
        lane="classification",
        candidate_path=targets,
        source_path=out / "g5_sec_sic_classification_source.csv",
        expected_source_sha256=sec._sha256(
            out / "g5_sec_sic_classification_source.csv"
        ),
        authorization_reference="PUBLIC_SEC_EDGAR",
        source_name="SEC_EDGAR_ARCHIVAL_SIC",
    )
    assert len(normalized) == 1
    assert normalized[0]["sector"] == "SEC_SIC_DIVISION_I"
    assert normalized[0]["index_bucket"] == ""
    assert receipt["accepted_field_counts"] == {"sector": 1}
    assert receipt["eligible_g5_evidence"] is False


def test_same_day_post_cutoff_filing_is_rejected_for_earlier_filing(tmp_path: Path):
    targets = _targets(
        tmp_path,
        "2015-01-05,AAA,2015-01-05T18:00:00Z,1\n",
    )
    cik_map = _cik_map(tmp_path, "AAA,12345,,\n")
    newer = "0000012345-15-000002"
    older = "0000012345-15-000001"

    def fetch_json(_url: str):
        return _submission(
            [newer, older],
            ["2015-01-05", "2015-01-02"],
            ["8-K", "10-Q"],
        )

    def fetch_text(url: str):
        if newer.replace("-", "") in url:
            return _filing_text(accepted="20150105210000", sic="7370")
        return _filing_text(accepted="20150102150000", sic="7370")

    out = tmp_path / "out"
    sec.build(
        targets_path=targets,
        cik_map_path=cik_map,
        output_dir=out,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    )
    rows = list(
        csv.DictReader(
            (out / "g5_sec_sic_classification_source.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert rows[0]["accession_number"] == older
    assert rows[0]["effective_ts_utc"] == "2015-01-02T15:00:00Z"


def test_additional_submission_files_are_searched(tmp_path: Path):
    targets = _targets(
        tmp_path,
        "2011-04-27,AAA,2011-04-27T19:00:00Z,1\n",
    )
    cik_map = _cik_map(tmp_path, "AAA,12345,,\n")
    old_accession = "0000012345-11-000001"

    def fetch_json(url: str):
        if url.endswith("CIK0000012345.json"):
            return _submission(
                [],
                [],
                [],
                files=[{"name": "CIK0000012345-submissions-001.json"}],
            )
        assert url.endswith("CIK0000012345-submissions-001.json")
        return {
            "accessionNumber": [old_accession],
            "filingDate": ["2011-04-20"],
            "form": ["10-Q"],
        }

    def fetch_text(_url: str):
        return _filing_text(accepted="20110420160000", sic="3571")

    out = tmp_path / "out"
    summary = sec.build(
        targets_path=targets,
        cik_map_path=cik_map,
        output_dir=out,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
    )
    assert summary["resolved_sector_target_count"] == 1
    rows = list(
        csv.DictReader(
            (out / "g5_sec_sic_classification_source.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert rows[0]["sector"] == "SEC_SIC_DIVISION_D"


def test_missing_explicit_historical_cik_stays_unresolved(tmp_path: Path):
    targets = _targets(
        tmp_path,
        "2015-01-05,AAA,2015-01-05T18:00:00Z,1\n",
    )
    cik_map = _cik_map(tmp_path, "BBB,99999,,\n")

    out = tmp_path / "out"
    summary = sec.build(
        targets_path=targets,
        cik_map_path=cik_map,
        output_dir=out,
        fetch_json=lambda _url: (_ for _ in ()).throw(
            AssertionError("network should not be used")
        ),
        fetch_text=lambda _url: (_ for _ in ()).throw(
            AssertionError("network should not be used")
        ),
    )
    assert summary["resolved_sector_target_count"] == 0
    assert summary["unresolved_target_count"] == 1
    unresolved = list(
        csv.DictReader(
            (out / "g5_sec_sic_classification_unresolved.csv").open(
                encoding="utf-8"
            )
        )
    )
    assert unresolved[0]["reason"] == "NO_EXPLICIT_HISTORICAL_CIK_MAPPING"


def test_conflicting_date_applicable_cik_mappings_fail_closed(tmp_path: Path):
    targets = _targets(
        tmp_path,
        "2015-01-05,AAA,2015-01-05T18:00:00Z,1\n",
    )
    cik_map = _cik_map(
        tmp_path,
        "AAA,12345,2010-01-01,2020-12-31\n"
        "AAA,67890,2014-01-01,2016-12-31\n",
    )

    try:
        sec.build(
            targets_path=targets,
            cik_map_path=cik_map,
            output_dir=tmp_path / "out",
            fetch_json=lambda _url: {},
            fetch_text=lambda _url: "",
        )
    except sec.G5SecClassificationError as exc:
        assert "multiple CIK mappings apply" in str(exc)
    else:
        raise AssertionError("expected conflicting CIK mappings to fail closed")


def test_sic_division_boundaries_are_deterministic():
    assert sec._sic_division("0100") == "SEC_SIC_DIVISION_A"
    assert sec._sic_division("1040") == "SEC_SIC_DIVISION_B"
    assert sec._sic_division("1731") == "SEC_SIC_DIVISION_C"
    assert sec._sic_division("3999") == "SEC_SIC_DIVISION_D"
    assert sec._sic_division("4911") == "SEC_SIC_DIVISION_E"
    assert sec._sic_division("5199") == "SEC_SIC_DIVISION_F"
    assert sec._sic_division("5999") == "SEC_SIC_DIVISION_G"
    assert sec._sic_division("6799") == "SEC_SIC_DIVISION_H"
    assert sec._sic_division("8999") == "SEC_SIC_DIVISION_I"
    assert sec._sic_division("9729") == "SEC_SIC_DIVISION_J"
