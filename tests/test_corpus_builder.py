from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from corpus_builder import build, load_first_trades, validate


def test_source_has_expected_174_rows():
    events = load_first_trades(ROOT / "data/raw/TimeOfFirstTrade.csv")
    assert len(events) == 174
    assert len({e.event_id for e in events}) == 174


def test_ground_truth_and_pending_announcement_fields():
    events = load_first_trades(ROOT / "data/raw/TimeOfFirstTrade.csv")
    assert all(e.hacked_flag == 1 for e in events)
    assert all(e.sec_documented_trade_flag == 1 for e in events)
    assert all(e.public_announcement_ts == "" for e in events)
    assert all(e.information_asymmetry_seconds == "" for e in events)
    assert all(e.research_use_only == 1 for e in events)


def test_distribution_matches_known_source_shape():
    events = load_first_trades(ROOT / "data/raw/TimeOfFirstTrade.csv")
    report = validate(events)
    assert report["year_distribution"] == {
        "2011": 15,
        "2012": 23,
        "2013": 37,
        "2014": 2,
        "2015": 97,
    }
    assert report["valid"] is True


def test_build_outputs(tmp_path):
    report = build(ROOT / "data/raw/TimeOfFirstTrade.csv", tmp_path)
    assert report["row_count"] == 174
    assert (tmp_path / "historical_events.csv").exists()
    assert (tmp_path / "manifest.json").exists()
