from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import g5_external_metadata_adapter as adapter
import g5_sec_13f_ownership as sec


def _targets(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "targets.csv"
    path.write_text(
        "event_date,candidate_symbol,latest_acceptable_effective_ts_utc,research_use_only\n"
        + body,
        encoding="utf-8",
    )
    return path


def _cusip_map(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "cusip.csv"
    path.write_text(
        "historical_symbol,cusip,valid_from,valid_through\n" + body,
        encoding="utf-8",
    )
    return path


def _shares(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "shares.csv"
    path.write_text(
        "event_date,symbol,available_at,shares_outstanding\n" + body,
        encoding="utf-8",
    )
    return path


def _submission(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "SUBMISSION.tsv"
    path.write_text(
        "ACCESSION_NUMBER\tCIK\tFILING_DATE\tPERIODOFREPORT\tSUBMISSIONTYPE\n"
        + body,
        encoding="utf-8",
    )
    return path


def _infotable(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "INFOTABLE.tsv"
    path.write_text(
        "ACCESSION_NUMBER\tCUSIP\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\n"
        + body,
        encoding="utf-8",
    )
    return path


def test_public_13f_fraction_is_adapter_compatible(tmp_path: Path):
    targets = _targets(
        tmp_path,
        "2015-02-17,AAA,2015-02-17T18:00:00Z,1\n",
    )
    cusip = _cusip_map(tmp_path, "AAA,123456789,2010-01-01,2020-12-31\n")
    shares = _shares(
        tmp_path,
        "2015-02-17,AAA,2015-02-16T20:00:00Z,1000000\n",
    )
    submission = _submission(
        tmp_path,
        "A1\t1001\t2015-02-13\t2014-12-31\t13F-HR\n"
        "A2\t1002\t2015-02-14\t2014-12-31\t13F-HR\n",
    )
    infotable = _infotable(
        tmp_path,
        "A1\t123456789\t250000\tSH\t\n"
        "A2\t123456789\t350000\tSH\t\n",
    )

    out = tmp_path / "out"
    summary = sec.build(
        targets_path=targets,
        cusip_map_path=cusip,
        shares_path=shares,
        submission_path=submission,
        infotable_path=infotable,
        output_dir=out,
    )
    assert summary["resolved_ownership_target_count"] == 1

    rows = list(
        csv.DictReader(
            (out / "g5_sec_13f_ownership_source.csv").open(encoding="utf-8")
        )
    )
    assert rows[0]["institutional_shares"] == "600000"
    assert rows[0]["institutional_ownership"] == "0.6"

    normalized, receipt = adapter.normalize(
        lane="ownership",
        candidate_path=targets,
        source_path=out / "g5_sec_13f_ownership_source.csv",
        expected_source_sha256=sec._sha256(
            out / "g5_sec_13f_ownership_source.csv"
        ),
        authorization_reference="PUBLIC_SEC_13F_DATASETS",
        source_name="SEC_13F_STRUCTURED_DATA",
    )
    assert normalized[0]["institutional_ownership"] == "0.6"
    assert receipt["accepted_field_counts"] == {"institutional_ownership": 1}


def test_post_event_amendment_does_not_replace_pre_event_original(tmp_path: Path):
    targets = _targets(
        tmp_path,
        "2015-02-17,AAA,2015-02-17T18:00:00Z,1\n",
    )
    cusip = _cusip_map(tmp_path, "AAA,123456789,,\n")
    shares = _shares(
        tmp_path,
        "2015-02-17,AAA,2015-02-16T20:00:00Z,1000000\n",
    )
    submission = _submission(
        tmp_path,
        "ORIG\t1001\t2015-02-13\t2014-12-31\t13F-HR\n"
        "AMEND\t1001\t2015-02-20\t2014-12-31\t13F-HR/A\n",
    )
    infotable = _infotable(
        tmp_path,
        "ORIG\t123456789\t200000\tSH\t\n"
        "AMEND\t123456789\t900000\tSH\t\n",
    )

    out = tmp_path / "out"
    sec.build(
        targets_path=targets,
        cusip_map_path=cusip,
        shares_path=shares,
        submission_path=submission,
        infotable_path=infotable,
        output_dir=out,
    )
    rows = list(
        csv.DictReader(
            (out / "g5_sec_13f_ownership_source.csv").open(encoding="utf-8")
        )
    )
    assert rows[0]["institutional_shares"] == "200000"
    assert rows[0]["institutional_ownership"] == "0.2"


def test_same_day_13f_filing_is_excluded_without_intraday_timestamp(tmp_path: Path):
    targets = _targets(
        tmp_path,
        "2015-02-17,AAA,2015-02-17T23:00:00Z,1\n",
    )
    cusip = _cusip_map(tmp_path, "AAA,123456789,,\n")
    shares = _shares(
        tmp_path,
        "2015-02-17,AAA,2015-02-16T20:00:00Z,1000000\n",
    )
    submission = _submission(
        tmp_path,
        "SAME\t1001\t2015-02-17\t2014-12-31\t13F-HR\n",
    )
    infotable = _infotable(
        tmp_path,
        "SAME\t123456789\t200000\tSH\t\n",
    )

    out = tmp_path / "out"
    summary = sec.build(
        targets_path=targets,
        cusip_map_path=cusip,
        shares_path=shares,
        submission_path=submission,
        infotable_path=infotable,
        output_dir=out,
    )
    assert summary["resolved_ownership_target_count"] == 0
    gaps = list(
        csv.DictReader(
            (out / "g5_sec_13f_ownership_gaps.csv").open(encoding="utf-8")
        )
    )
    assert gaps[0]["reason"] == "NO_PRE_EVENT_STRUCTURED_13F_HOLDINGS"


def test_puts_calls_and_principal_amounts_are_not_common_share_ownership(tmp_path: Path):
    targets = _targets(
        tmp_path,
        "2015-02-17,AAA,2015-02-17T18:00:00Z,1\n",
    )
    cusip = _cusip_map(tmp_path, "AAA,123456789,,\n")
    shares = _shares(
        tmp_path,
        "2015-02-17,AAA,2015-02-16T20:00:00Z,1000000\n",
    )
    submission = _submission(
        tmp_path,
        "A1\t1001\t2015-02-13\t2014-12-31\t13F-HR\n",
    )
    infotable = _infotable(
        tmp_path,
        "A1\t123456789\t100000\tSH\t\n"
        "A1\t123456789\t700000\tSH\tCALL\n"
        "A1\t123456789\t800000\tPRN\t\n",
    )

    out = tmp_path / "out"
    sec.build(
        targets_path=targets,
        cusip_map_path=cusip,
        shares_path=shares,
        submission_path=submission,
        infotable_path=infotable,
        output_dir=out,
    )
    rows = list(
        csv.DictReader(
            (out / "g5_sec_13f_ownership_source.csv").open(encoding="utf-8")
        )
    )
    assert rows[0]["institutional_shares"] == "100000"
    assert rows[0]["institutional_ownership"] == "0.1"


def test_missing_exact_cusip_and_pre_cutoff_denominator_fail_closed(tmp_path: Path):
    targets = _targets(
        tmp_path,
        "2015-02-17,AAA,2015-02-17T18:00:00Z,1\n"
        "2015-02-17,BBB,2015-02-17T18:00:00Z,1\n",
    )
    cusip = _cusip_map(tmp_path, "AAA,123456789,,\n")
    shares = _shares(
        tmp_path,
        "2015-02-17,AAA,2015-02-18T20:00:00Z,1000000\n",
    )
    submission = _submission(
        tmp_path,
        "A1\t1001\t2015-02-13\t2014-12-31\t13F-HR\n",
    )
    infotable = _infotable(
        tmp_path,
        "A1\t123456789\t100000\tSH\t\n",
    )

    out = tmp_path / "out"
    summary = sec.build(
        targets_path=targets,
        cusip_map_path=cusip,
        shares_path=shares,
        submission_path=submission,
        infotable_path=infotable,
        output_dir=out,
    )
    assert summary["resolved_ownership_target_count"] == 0
    gaps = {
        row["symbol"]: row["reason"]
        for row in csv.DictReader(
            (out / "g5_sec_13f_ownership_gaps.csv").open(encoding="utf-8")
        )
    }
    assert gaps["AAA"] == "NO_PRE_CUTOFF_SHARES_OUTSTANDING_DENOMINATOR"
    assert gaps["BBB"] == "NO_EXACT_HISTORICAL_CUSIP_MAPPING"


def test_conflicting_date_applicable_cusips_fail_closed(tmp_path: Path):
    targets = _targets(
        tmp_path,
        "2015-02-17,AAA,2015-02-17T18:00:00Z,1\n",
    )
    cusip = _cusip_map(
        tmp_path,
        "AAA,123456789,2010-01-01,2020-12-31\n"
        "AAA,987654321,2014-01-01,2016-12-31\n",
    )
    shares = _shares(
        tmp_path,
        "2015-02-17,AAA,2015-02-16T20:00:00Z,1000000\n",
    )
    submission = _submission(
        tmp_path,
        "A1\t1001\t2015-02-13\t2014-12-31\t13F-HR\n",
    )
    infotable = _infotable(
        tmp_path,
        "A1\t123456789\t100000\tSH\t\n",
    )

    try:
        sec.build(
            targets_path=targets,
            cusip_map_path=cusip,
            shares_path=shares,
            submission_path=submission,
            infotable_path=infotable,
            output_dir=tmp_path / "out",
        )
    except sec.G5Sec13FOwnershipError as exc:
        assert "multiple CUSIPs apply" in str(exc)
    else:
        raise AssertionError("expected conflicting CUSIPs to fail closed")
