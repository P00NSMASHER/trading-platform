import csv
import zipfile
from pathlib import Path

import hacked_earnings_github_extractor as extractor


def _write_zip(path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def test_archive_inspection_verifies_and_indexes_release_names(tmp_path, monkeypatch):
    archive = tmp_path / "2015.zip"
    _write_zip(
        archive,
        {
            "2015/QTR1/10145_20150217_0.txt": "release",
            "2015/QTR1/README.txt": "metadata",
        },
    )
    monkeypatch.setattr(
        extractor,
        "ARCHIVE_BLOB_SHAS",
        {"2015.zip": extractor.git_blob_sha(archive)},
    )

    inventory, releases = extractor.inspect_archives(tmp_path)

    assert inventory[0]["integrity"] == "verified"
    assert inventory[0]["zip_member_count"] == 2
    assert inventory[0]["parsed_release_count"] == 1
    assert releases[("10145", "20150217")] == [
        "2015/QTR1/10145_20150217_0.txt"
    ]


def test_event_index_uses_enriched_earnings_date(tmp_path):
    enrichment = tmp_path / "events.csv"
    with enrichment.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=[
                "event_id",
                "permno",
                "historical_symbol",
                "first_documented_illicit_trade_ts",
                "nearest_sample_earnings_date",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "event_id": "HEJFE-1",
                "permno": "10145",
                "historical_symbol": "HON",
                "first_documented_illicit_trade_ts": "2012-01-26 15:53:00",
                "nearest_sample_earnings_date": "2012-01-27",
            }
        )

    rows = extractor.build_event_release_index(
        enrichment,
        {("10145", "20120127"): ["2012/QTR1/10145_20120127_0.txt"]},
    )

    assert rows[0]["release_match_count"] == 1
    assert rows[0]["release_member_paths"] == "2012/QTR1/10145_20120127_0.txt"
