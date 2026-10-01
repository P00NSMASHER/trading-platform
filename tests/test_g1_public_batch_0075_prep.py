import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

def test_batch_0075_pnra_prep_is_bounded_and_chronological():
    d = json.loads((ROOT / "data/public/metadata/g1_worker0_batch_0075_prep.json").read_text())
    assert d["preparation_status"] == "PREPARED_EVIDENCE_ONLY_NO_CANONICAL_MUTATION"
    assert d["base_main_sha"] == "ae62ac8fcda9f4b5704f6ee0943c4863c966c6d9"
    assert (d["previous_exact_count"], d["expected_exact_count_after_batch"], d["expected_excluded_after_batch"]) == (91, 92, 82)
    assert len(d["items"]) == 1
    x = d["items"][0]
    assert x["event_id"] == "HEJFE-8167467EBF64AABE"
    assert x["historical_symbol"] == "PNRA"
    assert x["source_family"] == "federal_court_public_distribution_record"
    assert x["source_grade"] == "A"
    assert x["timestamp_evidence_kind"] == "explicit_release_clock"
    assert x["timestamp_precision"] == "approximate_minute"
    assert x["public_distribution_explicit"] is True
    assert x["source_reference"].startswith("https://www.supremecourt.gov/DocketPDF/")
    assert x["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
    trade = datetime.fromisoformat(x["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
    release = datetime.fromisoformat(x["public_announcement_ts"])
    assert release > trade
    assert int((release - trade).total_seconds()) == 2700
