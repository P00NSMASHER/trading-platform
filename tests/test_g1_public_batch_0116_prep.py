import csv, hashlib, json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "data/public/metadata/g1_announcement_times_batch_0116.csv"
EVIDENCE = ROOT / "data/public/metadata/g1_public_batch_0116_prep_evidence.json"
TARGETS = [
  {"event_id": "HEJFE-AC78A2434E4AE8FB", "historical_symbol": "ACO", "trade": "2013-04-25 14:40:00", "clock": "2013-04-26T07:00:00-04:00", "row": "1665", "delta": 58800},
  {"event_id": "HEJFE-5089F8E69B6BC646", "historical_symbol": "KELYA", "trade": "2013-05-07 15:49:00", "clock": "2013-05-08T07:30:00-04:00", "row": "1704", "delta": 56460},
  {"event_id": "HEJFE-7C93D3838E60926C", "historical_symbol": "CMTL", "trade": "2014-12-10 15:41:00", "clock": "2014-12-10T16:12:00-05:00", "row": "1807", "delta": 1860},
  {"event_id": "HEJFE-EBC49B9A024181AD", "historical_symbol": "VEEV", "trade": "2015-03-03 13:31:00", "clock": "2015-03-03T16:03:00-05:00", "row": "1907", "delta": 9120},
  {"event_id": "HEJFE-B9C8B3D0EF3DCB5E", "historical_symbol": "CACI", "trade": "2015-04-29 14:54:00", "clock": "2015-04-29T16:05:00-04:00", "row": "1952", "delta": 4260},
  {"event_id": "HEJFE-09EF6AD227D3AC5D", "historical_symbol": "DGI", "trade": "2012-07-31 12:21:00", "clock": "2012-07-31T16:01:00-04:00", "row": "1471", "delta": 13200},
  {"event_id": "HEJFE-4DEF5FDB3210E91B", "historical_symbol": "SWKS", "trade": "2015-01-22 15:41:00", "clock": "2015-01-22T16:15:00-05:00", "row": "1818", "delta": 2040},
  {"event_id": "HEJFE-0BAF70D8CC8F1631", "historical_symbol": "NKE", "trade": "2015-03-19 15:58:00", "clock": "2015-03-19T16:15:00-04:00", "row": "1918", "delta": 1020},
  {"event_id": "HEJFE-847F0EFE669B2440", "historical_symbol": "P", "trade": "2015-02-05 15:59:00", "clock": "2015-02-05T16:02:00-05:00", "row": "1849", "delta": 180},
  {"event_id": "HEJFE-FBFFFD99898188CF", "historical_symbol": "COLM", "trade": "2015-02-12 14:33:00", "clock": "2015-02-12T16:00:00-05:00", "row": "1862", "delta": 5220},
  {"event_id": "HEJFE-A76C746507C0D9AF", "historical_symbol": "DGI", "trade": "2015-02-26 15:42:00", "clock": "2015-02-26T16:02:00-05:00", "row": "1903", "delta": 1200},
  {"event_id": "HEJFE-8A0517D50278EAE4", "historical_symbol": "POWI", "trade": "2015-04-29 15:23:00", "clock": "2015-04-29T16:03:00-04:00", "row": "1955", "delta": 2400},
  {"event_id": "HEJFE-4D7E68AD113380B3", "historical_symbol": "TRAK", "trade": "2015-02-23 15:41:00", "clock": "2015-02-23T16:05:00-05:00", "row": "1892", "delta": 1440},
  {"event_id": "HEJFE-D6BA56FA6D57427E", "historical_symbol": "SCVL", "trade": "2015-05-20 15:17:00", "clock": "2015-05-20T16:05:00-04:00", "row": "1983", "delta": 2880}
]

WIRE_CODES = {
    "HEJFE-AC78A2434E4AE8FB": "MW",
    "HEJFE-5089F8E69B6BC646": "MW",
    "HEJFE-7C93D3838E60926C": "BW",
    "HEJFE-EBC49B9A024181AD": "BW",
    "HEJFE-B9C8B3D0EF3DCB5E": "BW",
    "HEJFE-09EF6AD227D3AC5D": "MW",
    "HEJFE-4DEF5FDB3210E91B": "BW",
    "HEJFE-0BAF70D8CC8F1631": "BW",
    "HEJFE-847F0EFE669B2440": "BW",
    "HEJFE-FBFFFD99898188CF": "BW",
    "HEJFE-A76C746507C0D9AF": "BW",
    "HEJFE-8A0517D50278EAE4": "BW",
    "HEJFE-4D7E68AD113380B3": "BW",
    "HEJFE-D6BA56FA6D57427E": "BW",
}

def rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def test_batch_0116_prep_evidence_is_exact_and_fail_closed():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    historical = {r["event_id"]: r for r in rows(ROOT / "data/processed/historical_events.csv")}
    resolutions = {r["event_id"]: r for r in rows(ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert evidence["prep_only"] is True
    assert evidence["base_main_sha"] == "828810d4e168a08498c7087075d91a9406f3cd6f"
    assert len(evidence["items"]) == len(TARGETS) == 14
    assert hashlib.sha256(BATCH.read_bytes()).hexdigest() == evidence["batch_sha256"]
    for spec in TARGETS:
        eid = spec["event_id"]
        assert historical[eid]["historical_symbol"] == spec["historical_symbol"]
        assert historical[eid]["first_documented_illicit_trade_ts"] == spec["trade"]
        assert resolutions[eid]["resolution_status"] == "excluded_fail_closed"
        trade = datetime.fromisoformat(spec["trade"]).replace(tzinfo=ZoneInfo("America/New_York"))
        release = datetime.fromisoformat(spec["clock"])
        assert trade < release <= trade + timedelta(days=7)
        assert int((release - trade).total_seconds()) == spec["delta"]

def test_batch_0116_rows_are_bound_to_evidence_and_csv():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    expected = {item["event_id"]: item for item in TARGETS}
    evidence_items = {item["event_id"]: item for item in evidence["items"]}
    batch_rows = {item["event_id"]: item for item in rows(BATCH)}
    assert set(evidence_items) == set(batch_rows) == set(expected)
    for eid, spec in expected.items():
        item = evidence_items[eid]
        batch = batch_rows[eid]
        assert item["historical_symbol"] == spec["historical_symbol"]
        assert item["first_documented_illicit_trade_ts"] == spec["trade"]
        assert item["public_announcement_ts"] == spec["clock"]
        assert item["gx8002_row_id"] == spec["row"]
        assert item["wire_source_code"] == WIRE_CODES[eid]
        assert item["information_asymmetry_seconds"] == spec["delta"]
        assert item["release_title"].strip()
        if eid == "HEJFE-847F0EFE669B2440":
            assert item["corroborating_release_member_path"] == ""
            assert item["corroboration_reference"].startswith("https://www.sec.gov/")
        else:
            assert item["corroborating_release_member_path"].endswith(".txt")
        assert batch["historical_symbol"] == spec["historical_symbol"]
        assert batch["event_date"] == spec["trade"][:10]
        assert batch["public_announcement_ts"] == spec["clock"]
        assert batch["timestamp_kind"] == "first_public_release"
        assert batch["source_grade"] == "A"

def test_batch_0116_prep_evidence_uses_admissible_sources():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    for item in evidence["items"]:
        assert item["timestamp_kind"] == "first_public_release"
        assert item["timestamp_evidence_kind"] == "federal_court_public_distribution_record"
        assert item["source_family"] == "federal_court_public_distribution_record"
        assert item["source_grade"] == "A"
        assert item["public_distribution_explicit"] is True
        assert item["source_reference"].startswith("https://storage.courtlistener.com/recap/")
        assert item["court_docket_reference"].startswith("https://www.courtlistener.com/docket/")
        assert item["corroboration_reference"].startswith(("https://github.com/", "https://www.sec.gov/"))
        assert item["public_announcement_ts"].endswith(("-04:00", "-05:00"))

def test_batch_0116_worker1_ownership_and_lane():
    event_ids = {x["event_id"] for x in TARGETS}
    assert 116 >= 66 and (116 - 66) % 5 == 0
    assert all(int(hashlib.sha256(eid.encode("utf-8")).hexdigest(), 16) % 5 == 1 for eid in event_ids)

def test_batch_0116_preserves_existing_exact_timestamps():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    resolutions = {r["event_id"]: r for r in rows(ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert len(evidence["previous_exact_timestamps"]) == 145
    for eid, stamp in evidence["previous_exact_timestamps"].items():
        assert resolutions[eid]["public_announcement_ts"] == stamp
