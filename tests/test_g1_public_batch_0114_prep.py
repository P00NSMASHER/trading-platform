import csv, hashlib, json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "data/public/metadata/g1_announcement_times_batch_0114.csv"
EVIDENCE = ROOT / "data/public/metadata/g1_public_batch_0114_prep_evidence.json"
TARGETS = [
  {
    "event_id": "HEJFE-4080E04F012A7290",
    "historical_symbol": "QLIK",
    "trade": "2015-02-12 15:39:00",
    "clock": "2015-02-12T16:05:00-05:00",
    "row": "1869",
    "delta": 1560
  },
  {
    "event_id": "HEJFE-7CEFB3FE3D986464",
    "historical_symbol": "ROG",
    "trade": "2015-02-17 15:44:00",
    "clock": "2015-02-17T16:01:00-05:00",
    "row": "1877",
    "delta": 1020
  },
  {
    "event_id": "HEJFE-9861757889227DD4",
    "historical_symbol": "IDTI",
    "trade": "2015-02-02 14:24:00",
    "clock": "2015-02-02T16:05:00-05:00",
    "row": "1838",
    "delta": 6060
  },
  {
    "event_id": "HEJFE-8EAA8616B1750B40",
    "historical_symbol": "CGNX",
    "trade": "2015-05-04 15:09:00",
    "clock": "2015-05-04T16:06:00-04:00",
    "row": "1966",
    "delta": 3420
  },
  {
    "event_id": "HEJFE-8415E931D4314106",
    "historical_symbol": "KOPN",
    "trade": "2015-03-10 14:58:00",
    "clock": "2015-03-10T16:05:00-04:00",
    "row": "1909",
    "delta": 4020
  },
  {
    "event_id": "HEJFE-0AA84E6E44ED02D8",
    "historical_symbol": "AMSG",
    "trade": "2015-02-25 15:57:00",
    "clock": "2015-02-25T16:00:00-05:00",
    "row": "1894",
    "delta": 180
  },
  {
    "event_id": "HEJFE-947F50EBAFBA54DC",
    "historical_symbol": "CRL",
    "trade": "2015-02-10 15:55:00",
    "clock": "2015-02-10T16:30:00-05:00",
    "row": "1851",
    "delta": 2100
  },
  {
    "event_id": "HEJFE-791693865584F9CB",
    "historical_symbol": "COL",
    "trade": "2015-04-22 14:29:00",
    "clock": "2015-04-23T07:30:00-04:00",
    "row": "1936",
    "delta": 61260
  },
  {
    "event_id": "HEJFE-22BF36BABB9D19D7",
    "historical_symbol": "ALNY",
    "trade": "2015-02-12 15:55:00",
    "clock": "2015-02-12T16:00:00-05:00",
    "row": "1860",
    "delta": 300
  },
  {
    "event_id": "HEJFE-E28050410A1480C6",
    "historical_symbol": "DYN",
    "trade": "2015-05-06 14:24:00",
    "clock": "2015-05-06T16:07:00-04:00",
    "row": "1978",
    "delta": 6180
  },
  {
    "event_id": "HEJFE-0704950C71CFAFB4",
    "historical_symbol": "TXRH",
    "trade": "2015-02-23 15:24:00",
    "clock": "2015-02-23T16:02:00-05:00",
    "row": "1893",
    "delta": 2280
  },
  {
    "event_id": "HEJFE-C926C41F03E66E82",
    "historical_symbol": "PAY",
    "trade": "2014-12-15 15:36:00",
    "clock": "2014-12-15T16:01:00-05:00",
    "row": "1808",
    "delta": 1500
  },
  {
    "event_id": "HEJFE-826F68D9DA88B37C",
    "historical_symbol": "ATRC",
    "trade": "2015-02-23 15:58:00",
    "clock": "2015-02-23T16:02:00-05:00",
    "row": "1889",
    "delta": 240
  },
  {
    "event_id": "HEJFE-A5AE76F13A48C40F",
    "historical_symbol": "DGI",
    "trade": "2013-05-07 14:29:00",
    "clock": "2013-05-07T16:02:00-04:00",
    "row": "1703",
    "delta": 5580
  }
]

def rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def test_batch_0114_prep_evidence_is_exact_and_fail_closed():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    historical = {r["event_id"]: r for r in rows(ROOT / "data/processed/historical_events.csv")}
    resolutions = {r["event_id"]: r for r in rows(ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert evidence["prep_only"] is True
    assert evidence["base_main_sha"] == "8014585b043217da5d5774382eb79e6a8b0972cc"
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
    assert resolutions["HEJFE-CCC7747CFBDE893E"]["resolution_status"] == "excluded_fail_closed"

def test_batch_0114_prep_evidence_uses_admissible_sources():
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

def test_batch_0114_worker4_ownership_and_lane():
    override = {"HEJFE-8415E931D4314106"}
    event_ids = {x["event_id"] for x in TARGETS}
    assert 114 >= 64 and (114 - 64) % 5 == 0
    assert all(eid in override or int(hashlib.sha256(eid.encode("utf-8")).hexdigest(), 16) % 5 == 4 for eid in event_ids)

def test_batch_0114_preserves_existing_exact_timestamps():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    resolutions = {r["event_id"]: r for r in rows(ROOT / "data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert len(evidence["previous_exact_timestamps"]) == 123
    for eid, stamp in evidence["previous_exact_timestamps"].items():
        assert resolutions[eid]["public_announcement_ts"] == stamp
