import json
from pathlib import Path

import pytest

import g4_exchange_reference_completion as g4


ROOT = Path(__file__).resolve().parents[1]
BLOCKERS = ROOT / "data/processed/authorized_input_real/g4_final_blockers.json"


def _fixed_width_master_row(symbol: str, shares: int, listed_exchange: str = "00") -> str:
    chars = [" "] * 251
    symbol_text = symbol.ljust(15)
    chars[26:41] = list(symbol_text)
    chars[156:158] = list(listed_exchange)
    shares_text = str(shares).rjust(10)
    chars[177:187] = list(shares_text)
    return "".join(chars)


def _nasdaq_row(effective: str, symbol: str, tso: int, tso_date: str) -> str:
    fields = [""] * 18
    fields[0] = effective
    fields[1] = "Cognex Corporation"
    fields[2] = symbol
    fields[3] = "Common Stock"
    fields[4] = "C"
    fields[16] = str(tso)
    fields[17] = tso_date
    return "|".join(fields)


def test_completion_plan_exactly_replaces_the_18_reviewed_exclusions():
    plan = g4.build_completion_plan(BLOCKERS)

    assert plan["current_g4"] == {
        "required": 3828,
        "exact_resolved": 3810,
        "reviewed_excluded": 18,
        "target_exact_resolved": 3828,
        "target_reviewed_excluded": 0,
    }
    assert len(plan["tasks"]) == 18
    assert plan["routes"]["nyse_daily_taq_master"]["target_rows"] == 13
    assert plan["routes"]["nasdaq_fundamental_data"]["target_rows"] == 5
    assert plan["routes"]["nyse_daily_taq_master"]["symbols"] == ["ACO", "WLL"]
    assert plan["routes"]["nasdaq_fundamental_data"]["symbols"] == ["CGNX"]
    assert plan["coverage_claimed"] is False

    keys = {
        (task["historical_symbol"], task["target_trade_date"])
        for task in plan["tasks"]
    }
    assert keys == set(g4.NYSE_TARGETS) | set(g4.NASDAQ_TARGETS)


def test_nyse_fixed_width_parser_uses_documented_exact_offsets(tmp_path: Path):
    path = tmp_path / "EQY_US_ALL_REF_MASTER_20130325.txt"
    path.write_text(
        "  03252013 header\n"
        + _fixed_width_master_row("ACO", 32_123_456)
        + "\n",
        encoding="ascii",
    )

    parsed = g4.parse_nyse_master(path, symbol="ACO")
    assert parsed == {
        "historical_symbol": "ACO",
        "shares_outstanding": "32123456",
        "listed_exchange_code": "00",
    }


def test_nyse_parser_rejects_non_nyse_use_of_nyse_only_shares_field(tmp_path: Path):
    path = tmp_path / "EQY_US_ALL_REF_MASTER_20150205.txt"
    path.write_text(
        _fixed_width_master_row("CGNX", 86_000_000, listed_exchange="07") + "\n",
        encoding="ascii",
    )
    with pytest.raises(ValueError, match="not NYSE code"):
        g4.parse_nyse_master(path, symbol="CGNX")


def test_nasdaq_fundamental_parser_requires_timestamp_and_exact_tso(tmp_path: Path):
    path = tmp_path / "NASDAQ02062015.txt"
    path.write_text(
        "Effective Date|Issue Name|Symbol|Description|Type||||||||||||TSO|TSO Date\n"
        + _nasdaq_row("02/06/2015 07:30", "CGNX", 86_544_015, "02/01/2015")
        + "\n",
        encoding="ascii",
    )
    parsed = g4.parse_nasdaq_fundamental(path, symbol="CGNX")
    assert parsed["historical_symbol"] == "CGNX"
    assert parsed["shares_outstanding"] == "86544015"
    assert parsed["fact_date"] == "2015-02-01"
    assert parsed["available_at"].startswith("2015-02-06T07:30:00")


def test_nasdaq_parser_fails_closed_without_effective_timestamp(tmp_path: Path):
    path = tmp_path / "NASDAQ02062015.txt"
    path.write_text(
        _nasdaq_row("02/06/2015", "CGNX", 86_544_015, "02/01/2015") + "\n",
        encoding="ascii",
    )
    with pytest.raises(ValueError, match="explicit start-of-day timestamp"):
        g4.parse_nasdaq_fundamental(path, symbol="CGNX")


def test_full_private_materialization_produces_18_pre_cutoff_rows(tmp_path: Path):
    nyse = tmp_path / "nyse"
    nasdaq = tmp_path / "nasdaq"
    nyse.mkdir()
    nasdaq.mkdir()

    by_source = {}
    for (symbol, target), source_date in g4.NYSE_TARGETS.items():
        by_source.setdefault((source_date, symbol), None)
    for source_date, symbol in by_source:
        compact = source_date.replace("-", "")
        path = nyse / f"EQY_US_ALL_REF_MASTER_{compact}.txt"
        shares = 32_200_000 if symbol == "ACO" else 166_900_000
        path.write_text(_fixed_width_master_row(symbol, shares) + "\n", encoding="ascii")

    for (_symbol, target), source_date in g4.NASDAQ_TARGETS.items():
        d = g4.date.fromisoformat(source_date)
        path = nasdaq / f"NASDAQ{d.strftime('%m%d%Y')}.txt"
        path.write_text(
            _nasdaq_row(
                f"{d.strftime('%m/%d/%Y')} 07:15",
                "CGNX",
                86_544_015,
                "02/01/2015",
            )
            + "\n",
            encoding="ascii",
        )

    rows, summary = g4.materialize_exact_rows(
        nyse_root=nyse,
        nasdaq_root=nasdaq,
        blockers_path=BLOCKERS,
    )

    assert len(rows) == 18
    assert summary["status"] == "READY_FOR_PRIVATE_G4_ACTIVATION"
    assert summary["rows_materialized"] == 18
    assert summary["nyse_rows"] == 13
    assert summary["nasdaq_rows"] == 5
    assert summary["g4_target_state"] == {
        "required": 3828,
        "exact_resolved": 3828,
        "reviewed_excluded": 0,
        "blocking_unresolved": 0,
    }
    assert all(int(row["shares_outstanding"]) > 0 for row in rows)

    # All five Nasdaq rows must be source-available before the 13:34 research cutoff.
    cgnx = [row for row in rows if row["historical_symbol"] == "CGNX"]
    assert len(cgnx) == 5
    assert all("T07:15:00" in row["available_at"] for row in cgnx)


def test_materialization_is_all_or_nothing(tmp_path: Path):
    nyse = tmp_path / "nyse"
    nasdaq = tmp_path / "nasdaq"
    nyse.mkdir()
    nasdaq.mkdir()

    # A partial vendor delivery must never be mistaken for exact G4 completion.
    first = next(iter(g4.NYSE_TARGETS.items()))
    (symbol, _target), source_date = first
    compact = source_date.replace("-", "")
    (nyse / f"EQY_US_ALL_REF_MASTER_{compact}.txt").write_text(
        _fixed_width_master_row(symbol, 32_200_000) + "\n",
        encoding="ascii",
    )

    with pytest.raises(FileNotFoundError):
        g4.materialize_exact_rows(
            nyse_root=nyse,
            nasdaq_root=nasdaq,
            blockers_path=BLOCKERS,
        )


def test_blocker_receipt_is_locked_to_the_exact_current_18_rows():
    payload = json.loads(BLOCKERS.read_text(encoding="utf-8"))
    assert g4._canonical_blocker_targets(payload) == (
        set(g4.NYSE_TARGETS) | set(g4.NASDAQ_TARGETS)
    )
