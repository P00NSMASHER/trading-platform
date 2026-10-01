import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

def rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def test_worker3_batch_0073_pnra_prep_evidence():
    evidence = json.loads((ROOT / "data/public/metadata/g1_public_batch_0073_evidence.json").read_text())
    assert evidence["preparation_status"] == "PREPARED_EVIDENCE_ONLY_NO_CANONICAL_MUTATION"
    assert evidence["base_main_sha"] == "cf5a70f07b54513c9f954e71289cc61d3d5aab4b"
    assert evidence["previous_exact_count"] == 86
    assert evidence["expected_exact_count_after_batch"] == 87
    assert evidence["expected_excluded_after_batch"] == 87
    assert len(evidence["items"]) == 1

    item = evidence["items"][0]
    assert item["event_id"] == "HEJFE-600696AB8463FFD8"
    assert item["historical_symbol"] == "PNRA"
    assert item["public_announcement_ts"] == "2013-07-23T16:00:00-04:00"
    assert item["timestamp_kind"] == "first_public_release"
    assert item["timestamp_evidence_kind"] == "explicit_release_clock"
    assert item["public_distribution_explicit"] is True
    assert item["source_family"] == "sec_litigation_public_distribution_record"
    assert item["source_grade"] == "A"
    assert item["source_reference"] == "https://www.sec.gov/files/litigation/complaints/2015/comp-pr2015-163.pdf"
    assert item["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")

    events = {r["event_id"]: r for r in rows(ROOT / "data/processed/historical_events.csv")}
    event = events[item["event_id"]]
    assert event["historical_symbol"] == "PNRA"
    trade = datetime.fromisoformat(event["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
    release = datetime.fromisoformat(item["public_announcement_ts"])
    assert trade < release <= trade + timedelta(days=7)
    assert int((release - trade).total_seconds()) == 2940

def test_worker3_batch_0073_prep_does_not_claim_canonical_resolution():
    resolved = {r["event_id"]: r for r in rows(ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv")}
    row = resolved["HEJFE-600696AB8463FFD8"]
    assert row["resolution_status"] == "excluded_fail_closed"
    assert not row["public_announcement_ts"]
    assert not row["information_asymmetry_seconds"]
