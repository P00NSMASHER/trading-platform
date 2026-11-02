from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = "1"
DEFAULT_REQUIRED_MARKET_KINDS = (
    "equity_trade",
    "equity_quote",
    "option_trade",
    "option_quote",
)
DEFAULT_MIN_CONTROLS = 3
PROHIBITED_OUTPUTS = [
    "BUY",
    "SELL",
    "expected_return",
    "target_price",
    "position_size",
    "order",
    "execution_instruction",
]


@dataclass(frozen=True)
class ControlDateMarketGap:
    event_date: str
    same_date_positive_count: int
    same_date_positive_symbols: str
    g2_structural_candidate_count: int
    g2_structural_candidate_symbols: str
    minimum_additional_candidate_symbol_dates: int
    structural_status: str
    point_in_time_matching_status: str = "NOT_EVALUATED_BY_THIS_PLANNER"
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _event_date(value: str) -> str:
    value = _clean(value)
    if len(value) < 10:
        raise ValueError(f"invalid event timestamp {value!r}")
    day = value[:10]
    if len(day) != 10 or day[4] != "-" or day[7] != "-":
        raise ValueError(f"invalid event timestamp {value!r}")
    return day


def _load_positive_symbols(events_path: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    with events_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"event_id", "historical_symbol", "first_documented_illicit_trade_ts"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"events file missing columns: {sorted(missing)}")
        for i, row in enumerate(reader, 2):
            symbol = _clean(row.get("historical_symbol")).upper()
            if not symbol:
                raise ValueError(f"event row {i}: blank historical_symbol")
            out[_event_date(row.get("first_documented_illicit_trade_ts", ""))].add(symbol)
    return dict(out)


def _load_market_requirements(requirements_path: Path) -> dict[str, dict[str, set[str]]]:
    out: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    with requirements_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"record_kind", "trade_date", "historical_symbols"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"requirements file missing columns: {sorted(missing)}")
        for i, row in enumerate(reader, 2):
            kind = _clean(row.get("record_kind"))
            trade_date = _clean(row.get("trade_date"))
            if not kind or not trade_date:
                raise ValueError(f"requirements row {i}: blank record_kind/trade_date")
            for raw in _clean(row.get("historical_symbols")).split(";"):
                symbol = raw.strip().upper()
                if symbol:
                    out[trade_date][kind].add(symbol)
    return {day: {kind: set(symbols) for kind, symbols in kinds.items()} for day, kinds in out.items()}


def _intersection(sets: list[set[str]]) -> set[str]:
    if not sets:
        return set()
    out = set(sets[0])
    for values in sets[1:]:
        out.intersection_update(values)
    return out


def build(
    *,
    events_path: Path,
    requirements_path: Path,
    output_dir: Path,
    min_controls: int = DEFAULT_MIN_CONTROLS,
    required_market_kinds: tuple[str, ...] = DEFAULT_REQUIRED_MARKET_KINDS,
) -> dict:
    if min_controls < 1:
        raise ValueError("min_controls must be positive")
    if not required_market_kinds:
        raise ValueError("at least one required market kind is required")

    positives_by_date = _load_positive_symbols(events_path)
    requirements = _load_market_requirements(requirements_path)
    rows: list[ControlDateMarketGap] = []

    for event_date in sorted(positives_by_date):
        positives = positives_by_date[event_date]
        by_kind = requirements.get(event_date, {})
        kind_sets = [by_kind.get(kind, set()) for kind in required_market_kinds]
        market_pool = _intersection(kind_sets)
        market_pool.difference_update(positives)
        deficit = max(0, min_controls - len(market_pool))
        rows.append(
            ControlDateMarketGap(
                event_date=event_date,
                same_date_positive_count=len(positives),
                same_date_positive_symbols=";".join(sorted(positives)),
                g2_structural_candidate_count=len(market_pool),
                g2_structural_candidate_symbols=";".join(sorted(market_pool)),
                minimum_additional_candidate_symbol_dates=deficit,
                structural_status="G2_POOL_3PLUS" if deficit == 0 else "G2_POOL_DEFICIT",
            )
        )

    sufficient = sum(row.minimum_additional_candidate_symbol_dates == 0 for row in rows)
    deficient = len(rows) - sufficient
    minimum_expansion = sum(row.minimum_additional_candidate_symbol_dates for row in rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "g5_market_candidate_gap.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = list(asdict(rows[0]).keys()) if rows else [
            "event_date",
            "same_date_positive_count",
            "same_date_positive_symbols",
            "g2_structural_candidate_count",
            "g2_structural_candidate_symbols",
            "minimum_additional_candidate_symbol_dates",
            "structural_status",
            "point_in_time_matching_status",
            "research_use_only",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Lower-bound G5 market-universe gap analysis. It measures whether the frozen G2 "
            "requirements contain at least the minimum number of non-positive same-day symbols "
            "with every required market record kind. It does not evaluate sector/index fit, "
            "point-in-time reference metadata, covariate completeness, or match distance."
        ),
        "research_use_only": True,
        "inputs": {
            "events": {"path": str(events_path), "sha256": _sha256(events_path)},
            "market_requirements": {"path": str(requirements_path), "sha256": _sha256(requirements_path)},
        },
        "required_market_kinds": list(required_market_kinds),
        "minimum_controls_per_event": min_controls,
        "event_date_count": len(rows),
        "dates_with_g2_structural_pool_3plus": sufficient,
        "dates_with_g2_structural_pool_deficit": deficient,
        "minimum_additional_candidate_symbol_dates": minimum_expansion,
        "g5_model_evaluation_controls_ready": False,
        "release_claimed": False,
        "interpretation": (
            "The expansion count is a strict lower bound. Additional symbols can still be required "
            "after same-sector/index constraints, point-in-time metadata availability, full matching "
            "covariate completeness, known-positive exclusions, and distance thresholds are applied."
        ),
        "outputs": {"gap_csv": str(csv_path)},
        "prohibited_outputs": PROHIBITED_OUTPUTS,
    }
    (output_dir / "g5_market_candidate_gap_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description="Measure the structural G5 control-candidate gap in frozen G2 requirements.")
    p.add_argument("--events", type=Path, required=True)
    p.add_argument("--requirements", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--min-controls", type=int, default=DEFAULT_MIN_CONTROLS)
    args = p.parse_args()
    result = build(
        events_path=args.events,
        requirements_path=args.requirements,
        output_dir=args.output_dir,
        min_controls=args.min_controls,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
