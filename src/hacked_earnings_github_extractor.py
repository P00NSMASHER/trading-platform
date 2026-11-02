from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path


SOURCE_REPOSITORY = "vgreg/hacked_earnings_jfe"
SOURCE_COMMIT = "c23c7d79d067a79d70cf20e31b072d3703497eae"
ARCHIVE_BLOB_SHAS = {
    "2010.zip": "b4b45ba8bb5e5bf4c502373914fdcaaae268d3aa",
    "2011.zip": "8f4b9b391e8e87649d2a5f5615a30371741c5e6a",
    "2012.zip": "afa44be02ab5aaea6e6105cbca247286bc892fd7",
    "2013.zip": "59e183f05e377ebd0ef2f581ba88522863663972",
    "2014.zip": "0e0e349b76318bb9558a790000c9cbe5ee933001",
    "2015.zip": "919ba9f271abdc06ba7c539ad278d5bb4fcb3715",
}
RELEASE_NAME = re.compile(
    r"^(?P<permno>\d+)_(?P<date>\d{8})_(?P<sequence>\d+)\.txt$",
    re.IGNORECASE,
)


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def inspect_archives(press_release_dir: Path) -> tuple[list[dict], dict[tuple[str, str], list[str]]]:
    archives: list[dict] = []
    releases: dict[tuple[str, str], list[str]] = defaultdict(list)

    for archive_name, expected_blob_sha in sorted(ARCHIVE_BLOB_SHAS.items()):
        archive_path = press_release_dir / archive_name
        if not archive_path.is_file():
            raise FileNotFoundError(archive_path)
        actual_blob_sha = git_blob_sha(archive_path)
        if actual_blob_sha != expected_blob_sha:
            raise ValueError(
                f"{archive_name}: git blob SHA mismatch: {actual_blob_sha} != {expected_blob_sha}"
            )

        with zipfile.ZipFile(archive_path) as archive:
            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise ValueError(f"{archive_name}: corrupt ZIP member: {corrupt_member}")
            members = [item for item in archive.infolist() if not item.is_dir()]
            parsed_count = 0
            for member in members:
                match = RELEASE_NAME.match(Path(member.filename).name)
                if match is None:
                    continue
                parsed_count += 1
                key = (match.group("permno"), match.group("date"))
                releases[key].append(member.filename)

        archives.append(
            {
                "archive": archive_name,
                "source_path": f"Data/Press releases/{archive_name}",
                "size_bytes": archive_path.stat().st_size,
                "git_blob_sha": actual_blob_sha,
                "zip_member_count": len(members),
                "parsed_release_count": parsed_count,
                "uncompressed_bytes": sum(item.file_size for item in members),
                "integrity": "verified",
            }
        )

    for paths in releases.values():
        paths.sort()
    return archives, dict(releases)


def build_event_release_index(
    event_enrichment_path: Path,
    releases: dict[tuple[str, str], list[str]],
) -> list[dict]:
    rows: list[dict] = []
    with event_enrichment_path.open("r", encoding="utf-8", newline="") as source:
        for event in csv.DictReader(source):
            release_date = event["nearest_sample_earnings_date"].replace("-", "")
            key = (str(int(event["permno"])), release_date)
            paths = releases.get(key, [])
            rows.append(
                {
                    "event_id": event["event_id"],
                    "permno": event["permno"],
                    "historical_symbol": event["historical_symbol"],
                    "first_documented_illicit_trade_ts": event[
                        "first_documented_illicit_trade_ts"
                    ],
                    "matched_earnings_date": event["nearest_sample_earnings_date"],
                    "release_match_count": len(paths),
                    "release_member_paths": ";".join(paths),
                    "source_repository": SOURCE_REPOSITORY,
                    "source_commit": SOURCE_COMMIT,
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def decode_word_coefficients(source_path: Path, output_path: Path) -> dict:
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise RuntimeError("pyarrow is required to decode the coefficient parquet") from exc

    table = parquet.read_table(source_path, columns=["word", "coef"])
    rows = table.to_pylist()
    rows.sort(key=lambda row: (float(row["coef"]), str(row["word"])))
    write_csv(output_path, rows)
    return {
        "row_count": len(rows),
        "minimum": rows[0] if rows else None,
        "maximum": rows[-1] if rows else None,
        "output_path": output_path.name,
    }


def extract(source_root: Path, event_enrichment_path: Path, output_dir: Path) -> dict:
    archives, releases = inspect_archives(source_root / "Data" / "Press releases")
    event_rows = build_event_release_index(event_enrichment_path, releases)
    event_index_path = output_dir / "event_press_release_index.csv"
    write_csv(event_index_path, event_rows)

    coefficient_path = output_dir / "word_coefficients.csv"
    coefficient_summary = decode_word_coefficients(
        source_root
        / "Text Analysis"
        / "PR_fit_EN_0_5_text_clean_stemmed_400_Count_0_005_0_4_WORDS.parquet",
        coefficient_path,
    )
    matched_events = sum(int(row["release_match_count"]) > 0 for row in event_rows)
    manifest = {
        "schema_version": "1",
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": SOURCE_COMMIT,
        "archive_integrity": archives,
        "archive_count": len(archives),
        "archive_member_count": sum(row["zip_member_count"] for row in archives),
        "parsed_release_count": sum(row["parsed_release_count"] for row in archives),
        "event_count": len(event_rows),
        "events_with_release_match": matched_events,
        "events_without_release_match": len(event_rows) - matched_events,
        "event_index_path": event_index_path.name,
        "word_coefficients": coefficient_summary,
        "g2_market_data_coverage_change": 0,
        "coverage_note": (
            "These public GitHub assets contain research labels, SEC press releases, and "
            "text-model coefficients, not licensed TAQ/LSEG trade or quote payloads."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "github_binary_extraction_manifest.json"
    manifest["manifest_path"] = manifest_path.name
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify and index public binary assets from vgreg/hacked_earnings_jfe."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--event-enrichment", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            extract(args.source_root, args.event_enrichment, args.output_dir),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
