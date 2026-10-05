from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

DEFAULT_BLOCKERS = Path(
    "data/processed/authorized_input_real/g4_final_blockers.json"
)

# Each NYSE target is intentionally bound to the immediately preceding
# trading day's Master file.  The Master file is a same-day evening product,
# so a conservative 23:59:59 local availability bound is still before the
# next trading day's intraday research cutoff.
NYSE_TARGETS = {
    ("ACO", "2013-03-26"): "2013-03-25",
    ("ACO", "2013-03-27"): "2013-03-26",
    ("ACO", "2013-03-28"): "2013-03-27",
    ("ACO", "2013-04-01"): "2013-03-28",
    ("ACO", "2013-04-02"): "2013-04-01",
    ("ACO", "2013-04-03"): "2013-04-02",
    ("ACO", "2013-04-04"): "2013-04-03",
    ("ACO", "2013-04-05"): "2013-04-04",
    ("ACO", "2013-04-08"): "2013-04-05",
    ("ACO", "2013-04-09"): "2013-04-08",
}

# Nasdaq Fundamental Data is a start-of-day T+1 reference product.  For
# CGNX, the exact target-day file is required so that its own Effective Date
# timestamp can be checked against the 13:34 ET cutoff.
NASDAQ_TARGETS = {
    ("CGNX", "2015-02-06"): "2015-02-06",
    ("CGNX", "2015-02-09"): "2015-02-09",
    ("CGNX", "2015-02-10"): "2015-02-10",
    ("CGNX", "2015-02-11"): "2015-02-11",
    ("CGNX", "2015-02-12"): "2015-02-12",
}

TARGET_CUTOFFS = {
    "ACO": time(14, 10),
    "CGNX": time(13, 34),
    }

NYSE_LISTED_EXCHANGE_CODE = "00"

OUTPUT_FIELDS = [
    "historical_symbol",
    "target_trade_date",
    "fact_date",
    "available_at",
    "shares_outstanding",
    "source_reference",
]


@dataclass(frozen=True)
class Task:
    route: str
    historical_symbol: str
    target_trade_date: str
    source_date: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_blocker_targets(payload: dict) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    for blocker in payload.get("blockers") or []:
        symbol = str(blocker.get("historical_symbol") or "").strip().upper()
        for trade_date in blocker.get("target_trade_dates") or []:
            targets.add((symbol, str(trade_date)))
    return targets


def load_and_verify_blockers(path: Path = DEFAULT_BLOCKERS) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    state = dict(payload.get("g4_state") or {})
    expected = set(NYSE_TARGETS) | set(NASDAQ_TARGETS)

    if int(state.get("required", -1)) != 3828:
        raise ValueError("G4 blocker receipt no longer has the canonical 3,828-row scope")
    if int(state.get("exact_resolved", -1)) != 3813:
        raise ValueError("G4 exact-resolved baseline drifted from 3,813")
    if int(state.get("reviewed_excluded", -1)) != 15:
        raise ValueError("G4 reviewed-exclusion baseline drifted from 15")
    if int(state.get("blocking_unresolved", -1)) != 0:
        raise ValueError("G4 blocker receipt contains unreviewed unresolved rows")
    actual = _canonical_blocker_targets(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"G4 blocker target drift: missing={missing} extra={extra}")
    return payload


def build_tasks(blockers_path: Path = DEFAULT_BLOCKERS) -> list[Task]:
    load_and_verify_blockers(blockers_path)
    tasks = [
        Task("nyse_daily_taq_master", symbol, target, source)
        for (symbol, target), source in sorted(NYSE_TARGETS.items())
    ]
    tasks += [
        Task("nasdaq_fundamental_data", symbol, target, source)
        for (symbol, target), source in sorted(NASDAQ_TARGETS.items())
    ]
    return sorted(tasks, key=lambda x: (x.target_trade_date, x.historical_symbol))


def build_completion_plan(blockers_path: Path = DEFAULT_BLOCKERS) -> dict:
    tasks = build_tasks(blockers_path)
    nyse = [task for task in tasks if task.route == "nyse_daily_taq_master"]
    nasdaq = [task for task in tasks if task.route == "nasdaq_fundamental_data"]
    return {
        "schema_version": "1",
        "purpose": (
            "Exact G4 completion plan that replaces all 15 reviewed share exclusions "
            "with admissible pre-cutoff exchange-reference shares evidence. "
            "Planning is public-safe; licensed payloads remain private."
        ),
        "current_g4": {
            "required": 3828,
            "exact_resolved": 3813,
            "reviewed_excluded": 15,
            "target_exact_resolved": 3828,
            "target_reviewed_excluded": 0,
        },
        "routes": {
            "nyse_daily_taq_master": {
                "target_rows": len(nyse),
                "symbols": sorted({task.historical_symbol for task in nyse}),
                "source_dates": sorted({task.source_date for task in nyse}),
                "field_contract": {
                    "symbol_compressed_offset": 26,
                    "symbol_compressed_size": 15,
                    "listed_exchange_offset": 156,
                    "listed_exchange_size": 2,
                    "shares_outstanding_offset": 177,
                    "shares_outstanding_size": 10,
                    "required_listed_exchange_code": NYSE_LISTED_EXCHANGE_CODE,
                },
                "availability_policy": (
                    "Use 23:59:59 America/New_York on the prior trading-day Master "
                    "date as a conservative upper bound; this remains before the "
                    "next target-day cutoff."
                ),
            },
            "nasdaq_fundamental_data": {
                "target_rows": len(nasdaq),
                "symbols": sorted({task.historical_symbol for task in nasdaq}),
                "source_dates": sorted({task.source_date for task in nasdaq}),
                "field_contract": {
                    "effective_date_field": 1,
                    "symbol_field": 3,
                    "tso_field": 17,
                    "tso_date_field": 18,
                    "delimiter": "|",
                },
                "availability_policy": (
                    "Use the vendor-provided Effective Date timestamp and require it "
                    "to be no later than the target-day 13:34 America/New_York cutoff."
                ),
            },
        },
        "tasks": [
            {
                "route": task.route,
                "historical_symbol": task.historical_symbol,
                "target_trade_date": task.target_trade_date,
                "source_date": task.source_date,
            }
            for task in tasks
        ],
        "activation_rule": (
            "All 15 rows must materialize with positive exact shares, admissible "
            "fact dates, and pre-cutoff availability. Partial activation is prohibited."
        ),
        "coverage_claimed": False,
    }


def _read_archive_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = [x for x in archive.namelist() if not x.endswith("/")]
            if len(members) != 1:
                raise ValueError(f"{path}: expected exactly one file in Master archive")
            return archive.read(members[0]).decode("ascii")
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rt", encoding="ascii", newline="") as handle:
            return handle.read()
    return path.read_text(encoding="ascii")


def parse_nyse_master(path: Path, *, symbol: str) -> dict:
    wanted = symbol.strip().upper()
    if not wanted:
        raise ValueError("NYSE Master symbol must be nonblank")

    matches = []
    for raw in _read_archive_text(path).splitlines():
        if len(raw) < 187:
            continue
        row_symbol = raw[26:41].strip().upper()
        if row_symbol != wanted:
            continue
        listed_exchange = raw[156:158].strip()
        shares_raw = raw[177:187].strip().replace(",", "")
        if listed_exchange != NYSE_LISTED_EXCHANGE_CODE:
            raise ValueError(
                f"{path.name}: {wanted} listed-exchange code {listed_exchange!r} "
                "is not NYSE code '00'; NYSE-only shares field is inadmissible"
            )
        if not shares_raw.isdigit() or int(shares_raw) <= 0:
            raise ValueError(f"{path.name}: {wanted} has invalid Shares Outstanding")
        matches.append(
            {
                "historical_symbol": wanted,
                "shares_outstanding": str(int(shares_raw)),
                "listed_exchange_code": listed_exchange,
            }
        )
    if len(matches) != 1:
        raise ValueError(
            f"{path.name}: expected exactly one NYSE Master row for {wanted}, "
            f"found {len(matches)}"
        )
    return matches[0]


def _parse_nasdaq_effective_timestamp(value: str) -> datetime:
    clean = value.strip()
    for fmt in ("%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=NY)
        except ValueError:
            pass
    raise ValueError(
        "Nasdaq Fundamental Effective Date must include an explicit start-of-day timestamp"
    )


def parse_nasdaq_fundamental(path: Path, *, symbol: str) -> dict:
    wanted = symbol.strip().upper()
    if not wanted:
        raise ValueError("Nasdaq Fundamental symbol must be nonblank")

    matches = []
    text = _read_archive_text(path)
    for row in csv.reader(io.StringIO(text), delimiter="|"):
        fields = [field.strip() for field in row]
        if len(fields) < 18:
            continue
        if fields[0].lower() == "effective date":
            continue
        if fields[2].upper() != wanted:
            continue
        effective = _parse_nasdaq_effective_timestamp(fields[0])
        tso_raw = fields[16].replace(",", "").strip()
        tso_date_raw = fields[17].strip()
        if not tso_raw.isdigit() or int(tso_raw) <= 0:
            raise ValueError(f"{path.name}: {wanted} has invalid TSO")
        try:
            tso_date = datetime.strptime(tso_date_raw, "%m/%d/%Y").date()
        except ValueError as exc:
            raise ValueError(f"{path.name}: {wanted} has invalid TSO Date") from exc
        matches.append(
            {
                "historical_symbol": wanted,
                "shares_outstanding": str(int(tso_raw)),
                "fact_date": tso_date.isoformat(),
                "available_at": effective.isoformat(),
            }
        )
    if len(matches) != 1:
        raise ValueError(
            f"{path.name}: expected exactly one Nasdaq Fundamental row for {wanted}, "
            f"found {len(matches)}"
        )
    return matches[0]


def _nyse_candidate_paths(root: Path, source_date: str) -> list[Path]:
    compact = source_date.replace("-", "")
    stem = f"EQY_US_ALL_REF_MASTER_{compact}"
    return [root / f"{stem}{suffix}" for suffix in (".zip", ".gz", ".txt", "")]


def _nasdaq_candidate_paths(root: Path, source_date: str) -> list[Path]:
    d = date.fromisoformat(source_date)
    stamp = d.strftime("%m%d%Y")
    return [
        root / f"NASDAQ{stamp}.txt",
        root / f"NASDAQRV{stamp}.txt",
        root / f"NASDAQ{stamp}.txt.gz",
        root / f"NASDAQRV{stamp}.txt.gz",
    ]


def _one_existing(candidates: Iterable[Path]) -> Path:
    existing = [path for path in candidates if path.exists()]
    if len(existing) != 1:
        raise FileNotFoundError(
            "expected exactly one matching vendor file; found "
            + ", ".join(str(path) for path in existing)
        )
    return existing[0]


def _cutoff(symbol: str, target_trade_date: str) -> datetime:
    return datetime.combine(
        date.fromisoformat(target_trade_date),
        TARGET_CUTOFFS[symbol],
        tzinfo=NY,
    )


def materialize_exact_rows(
    *,
    nyse_root: Path,
    nasdaq_root: Path,
    blockers_path: Path = DEFAULT_BLOCKERS,
) -> tuple[list[dict[str, str]], dict]:
    tasks = build_tasks(blockers_path)
    rows: list[dict[str, str]] = []
    input_receipts = []

    for task in tasks:
        if task.route == "nyse_daily_taq_master":
            path = _one_existing(_nyse_candidate_paths(nyse_root, task.source_date))
            parsed = parse_nyse_master(path, symbol=task.historical_symbol)
            fact_date = task.source_date
            available = datetime.combine(
                date.fromisoformat(task.source_date),
                time(23, 59, 59),
                tzinfo=NY,
            )
        else:
            path = _one_existing(_nasdaq_candidate_paths(nasdaq_root, task.source_date))
            parsed = parse_nasdaq_fundamental(path, symbol=task.historical_symbol)
            fact_date = parsed["fact_date"]
            available = datetime.fromisoformat(parsed["available_at"])

        target_date = date.fromisoformat(task.target_trade_date)
        fact = date.fromisoformat(fact_date)
        if fact > target_date:
            raise ValueError(
                f"{task.historical_symbol} {task.target_trade_date}: future fact date"
            )
        if (target_date - fact).days > 130:
            raise ValueError(
                f"{task.historical_symbol} {task.target_trade_date}: fact exceeds 130-day ceiling"
            )
        cutoff = _cutoff(task.historical_symbol, task.target_trade_date)
        if available > cutoff:
            raise ValueError(
                f"{task.historical_symbol} {task.target_trade_date}: source was not "
                "available before the research cutoff"
            )

        rows.append(
            {
                "historical_symbol": task.historical_symbol,
                "target_trade_date": task.target_trade_date,
                "fact_date": fact_date,
                "available_at": available.isoformat(),
                "shares_outstanding": parsed["shares_outstanding"],
                "source_reference": path.name,
            }
        )
        input_receipts.append(
            {
                "route": task.route,
                "source_file": path.name,
                "source_sha256": sha256_file(path),
                "historical_symbol": task.historical_symbol,
                "target_trade_date": task.target_trade_date,
            }
        )

    keys = {(row["historical_symbol"], row["target_trade_date"]) for row in rows}
    expected = set(NYSE_TARGETS) | set(NASDAQ_TARGETS)
    if len(rows) != 15 or keys != expected:
        raise ValueError("exact G4 materialization did not produce all 18 required rows")

    summary = {
        "schema_version": "1",
        "status": "READY_FOR_PRIVATE_G4_ACTIVATION",
        "rows_materialized": len(rows),
        "nyse_rows": sum(row["historical_symbol"] == "ACO" for row in rows),
        "nasdaq_rows": sum(row["historical_symbol"] == "CGNX" for row in rows),
        "input_receipts": input_receipts,
        "g4_target_state": {
            "required": 3828,
            "exact_resolved": 3828,
            "reviewed_excluded": 0,
            "blocking_unresolved": 0,
        },
        "note": (
            "This materialization receipt is not itself a canonical G4 gate change. "
            "Activate the two private source CSVs in the metadata contract, disable "
            "the reviewed-share exclusion receipt, rerun resolver/quality/release "
            "receipts, and require exact 3,828/3,828 before promotion."
        ),
    }
    return sorted(rows, key=lambda row: (row["target_trade_date"], row["historical_symbol"])), summary


def write_private_outputs(
    rows: list[dict[str, str]],
    summary: dict,
    *,
    output_root: Path,
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    routes = {
        "nyse": [row for row in rows if row["historical_symbol"] in {"ACO", "WLL"}],
        "nasdaq": [row for row in rows if row["historical_symbol"] == "CGNX"],
    }
    for name, selected in routes.items():
        path = output_root / f"g4_{name}_exact_shares.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(selected)
    (output_root / "g4_exact_materialization_receipt.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the exact 15-row G4 exchange-reference completion plan or "
            "materialize it from private licensed NYSE/Nasdaq files."
        )
    )
    parser.add_argument("--blockers", type=Path, default=DEFAULT_BLOCKERS)
    parser.add_argument("--nyse-root", type=Path)
    parser.add_argument("--nasdaq-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if not args.execute:
        print(json.dumps(build_completion_plan(args.blockers), indent=2, sort_keys=True))
        return

    if args.nyse_root is None or args.nasdaq_root is None or args.output_root is None:
        raise SystemExit("--execute requires --nyse-root, --nasdaq-root and --output-root")
    rows, summary = materialize_exact_rows(
        nyse_root=args.nyse_root,
        nasdaq_root=args.nasdaq_root,
        blockers_path=args.blockers,
    )
    write_private_outputs(rows, summary, output_root=args.output_root)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
