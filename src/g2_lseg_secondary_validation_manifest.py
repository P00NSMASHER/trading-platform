from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_SECONDARY = Path("data/processed/g2_vendor_requests/lseg_secondary_ric_candidates.csv")
DEFAULT_CORE = Path("data/processed/real_data_release_sprint/g2_core_source_date_requirements.csv")
DEFAULT_OPTIONS = Path("data/processed/real_data_release_sprint/g2_option_source_date_requirements.csv")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path}: empty CSV")
    return rows


def build_validation_manifest(
    secondary_rows: list[dict[str, str]],
    core_rows: list[dict[str, str]],
    option_rows: list[dict[str, str]],
) -> dict:
    secondary: dict[str, dict[str, str]] = {}
    for row in secondary_rows:
        symbol = row["historical_symbol"].strip()
        rics = [x for x in row["candidate_rics"].split(";") if x]
        if not symbol or not rics:
            raise ValueError("secondary candidate row missing symbol or RIC")
        if row["validation_status"] != "historical_date_validation_required":
            raise ValueError(f"{symbol}: secondary mapping is not fail-closed")
        secondary[symbol] = row

    jobs: dict[tuple[str, str], dict[str, object]] = {}

    def add_requirements(rows: list[dict[str, str]], lane: str) -> None:
        for row in rows:
            symbols = [x for x in row["historical_symbols"].split(";") if x]
            if len(symbols) != int(row["symbol_date_pair_count"]):
                raise ValueError(
                    f"{row['trade_date']}/{row['record_kind']}: pair-count mismatch"
                )
            for symbol in symbols:
                if symbol not in secondary:
                    continue
                key = (row["trade_date"], symbol)
                job = jobs.setdefault(
                    key,
                    {
                        "trade_date": row["trade_date"],
                        "historical_symbol": symbol,
                        "lanes": set(),
                        "record_kinds": set(),
                    },
                )
                job["lanes"].add(lane)
                job["record_kinds"].add(row["record_kind"])

    add_requirements(core_rows, "equity")
    add_requirements(option_rows, "options")

    rows_out: list[dict[str, str]] = []
    for (trade_date, symbol), job in sorted(jobs.items()):
        evidence = secondary[symbol]
        rows_out.append(
            {
                "trade_date": trade_date,
                "historical_symbol": symbol,
                "candidate_rics": evidence["candidate_rics"],
                "evidence_type": evidence["evidence_type"],
                "source_repo": evidence["source_repo"],
                "source_file": evidence["source_file"],
                "required_lanes": ";".join(sorted(job["lanes"])),
                "required_record_kinds": ";".join(sorted(job["record_kinds"])),
                "request_type": "HistoricalIdentifierValidationThenTickHistory",
                "validation_status": "requires_live_lseg_historical_date_validation",
            }
        )

    represented = {row["historical_symbol"] for row in rows_out}
    missing = sorted(set(secondary).difference(represented))
    if missing:
        raise ValueError(f"secondary symbols absent from frozen requirements: {missing}")

    lane_checks = sum(len(row["required_lanes"].split(";")) for row in rows_out)
    record_kind_checks = sum(
        len(row["required_record_kinds"].split(";")) for row in rows_out
    )
    dates = [row["trade_date"] for row in rows_out]

    return {
        "schema_version": "1",
        "purpose": (
            "Minimal date-specific LSEG historical identifier validation queue for "
            "repository-backed secondary RIC candidates. This performs no API call, "
            "download, purchase, or G2 coverage mutation."
        ),
        "summary": {
            "secondary_symbols": len(secondary),
            "unique_symbol_date_validation_jobs": len(rows_out),
            "lane_symbol_date_checks_represented": lane_checks,
            "record_kind_symbol_date_checks_represented": record_kind_checks,
            "min_trade_date": min(dates),
            "max_trade_date": max(dates),
            "unresolved_candidate_jobs": len(rows_out),
            "g2_coverage_change": False,
        },
        "jobs": rows_out,
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "trade_date",
        "historical_symbol",
        "candidate_rics",
        "evidence_type",
        "source_repo",
        "source_file",
        "required_lanes",
        "required_record_kinds",
        "request_type",
        "validation_status",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build minimal historical-date validation jobs for secondary LSEG RICs."
    )
    parser.add_argument("--secondary", type=Path, default=DEFAULT_SECONDARY)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--options", type=Path, default=DEFAULT_OPTIONS)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest = build_validation_manifest(
        _read_csv(args.secondary),
        _read_csv(args.core),
        _read_csv(args.options),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.output_dir / "secondary_historical_validation_jobs.csv", manifest["jobs"])
    (args.output_dir / "secondary_historical_validation_summary.json").write_text(
        json.dumps(
            {
                "schema_version": manifest["schema_version"],
                "purpose": manifest["purpose"],
                "summary": manifest["summary"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
