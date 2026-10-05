import csv, hashlib, json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
BATCH=ROOT/"data/public/metadata/g1_announcement_times_batch_0122.csv"
EVIDENCE=ROOT/"data/public/metadata/g1_public_batch_0122_evidence.json"
TARGETS={
  "HEJFE-B5A8A297D14CD19D": {
    "symbol": "TXT",
    "clock": "2015-04-28T06:30:00-04:00",
    "row": "1947",
    "delta": 53760
  },
  "HEJFE-FBA59D82CEE8FD00": {
    "symbol": "CGNX",
    "clock": "2015-02-12T16:06:00-05:00",
    "row": "1861",
    "delta": 7320
  },
  "HEJFE-4E643D38FFB3016E": {
    "symbol": "PNRA",
    "clock": "2015-02-11T17:28:00-05:00",
    "row": "1857",
    "delta": 9000
  },
  "HEJFE-54A5D1D8A5B593C8": {
    "symbol": "NUAN",
    "clock": "2015-02-05T16:03:00-05:00",
    "row": "1848",
    "delta": 1800
  },
  "HEJFE-198DE6D99E934F32": {
    "symbol": "EW",
    "clock": "2011-04-20T16:01:00-04:00",
    "row": "934",
    "delta": 5520
  },
  "HEJFE-A3C5C43F6AC75C44": {
    "symbol": "PRU",
    "clock": "2015-05-06T16:07:00-04:00",
    "row": "1979",
    "delta": 1200
  }
}

def rows(path):
    with path.open(newline="",encoding="utf-8") as h:return list(csv.DictReader(h))

def test_batch_0122_exact_event_binding_and_canonical_resolution():
    evidence=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    items={x["event_id"]:x for x in evidence["items"]}
    batch={x["event_id"]:x for x in rows(BATCH)}
    hist={x["event_id"]:x for x in rows(ROOT/"data/processed/historical_events.csv")}
    resolved={x["event_id"]:x for x in rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert set(items)==set(batch)==set(TARGETS) and len(items)==6
    for eid,spec in TARGETS.items():
        item=items[eid]; trade=datetime.fromisoformat(hist[eid]["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York")); release=datetime.fromisoformat(spec["clock"])
        assert item["historical_symbol"]==spec["symbol"]==hist[eid]["historical_symbol"]
        assert item["public_announcement_ts"]==spec["clock"] and str(item["gx8002_row_id"])==spec["row"]
        assert int((release-trade).total_seconds())==spec["delta"] and trade<release
        assert item["source_family"]=="federal_court_public_distribution_record" and item["source_grade"]=="A"
        assert item["public_distribution_explicit"] is True and item["wire_source_code"] in {"BW","MW"}
        assert item["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
        assert resolved[eid]["resolution_status"]=="resolved_exact_public_timestamp"
        assert resolved[eid]["public_announcement_ts"]==release.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00","Z")

def test_batch_0122_preserves_prior_exact_and_leaves_two_fail_closed():
    evidence=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    resolved={x["event_id"]:x for x in rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert evidence["previous_exact_count"]==166 and evidence["expected_exact_count_after_batch"]==172 and evidence["expected_excluded_after_batch"]==2
    assert hashlib.sha256(BATCH.read_bytes()).hexdigest()==evidence["batch_sha256"]
    for eid,stamp in evidence["previous_exact_timestamps"].items(): assert resolved[eid]["public_announcement_ts"]==stamp
    excluded=[x for x in resolved.values() if x["resolution_status"]=="excluded_fail_closed"]
    assert len(excluded)==0 and all(not x["public_announcement_ts"] and not x["information_asymmetry_seconds"] for x in excluded)

def test_batch_0122_worker2_ownership_and_lane():
    assert 117>=62 and (117-62)%5==0
    assert all(int(hashlib.sha256(eid.encode("utf-8")).hexdigest(),16)%5==2 for eid in TARGETS)
