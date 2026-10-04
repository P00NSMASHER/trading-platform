import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREP = ROOT / "data/public/metadata/g1_public_batch_0102_prep_evidence.json"
RESOLUTIONS = (
    ROOT
    / "data/processed/authorized_input_real/announcement_resolutions.csv"
)


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_worker2_wmb_prep_is_invalidated_cross_shard():
    prep = json.loads(PREP.read_text(encoding="utf-8"))
    assert prep["prep_only"] is True
    assert prep["research_use_only"] is True
    assert prep["invalidated"] is True
    assert prep["disposition"] == "DO_NOT_INTEGRATE_CROSS_SHARD"
    assert prep["claimed_worker_slot"] == 2
    assert prep["actual_worker_slot"] == 4
    assert int(prep["reserved_batch"]) % 5 == 2

    assert len(prep["items"]) == 1
    item = prep["items"][0]
    assert item["event_id"] == "HEJFE-1783DE88400AF6CC"
    assert item["historical_symbol"] == "WMB"
    digest = hashlib.sha256(item["event_id"].encode("utf-8")).digest()
    digest_hex = digest.hex()
    owner = int.from_bytes(digest, "big") % 5
    assert digest_hex == prep["ownership_audit"]["sha256"]
    assert owner == prep["ownership_audit"]["sha256_mod_5"] == 4
    assert prep["ownership_audit"]["worker_2_owned"] is False

    release = datetime.fromisoformat(item["public_announcement_ts"])
    trade = datetime.fromisoformat(item["first_documented_illicit_trade_ts"])
    assert int((release - trade).total_seconds()) == 4260
    assert item["expected_information_asymmetry_seconds"] == 4260
    assert prep["source_family"] == "federal_court_public_distribution_record"
    assert prep["source_reference"].startswith(
        "https://storage.courtlistener.com/recap/"
    )
    assert item["corroboration_reference"].startswith(
        "https://www.sec.gov/Archives/edgar/data/"
    )

    rows = {row["event_id"]: row for row in _rows(RESOLUTIONS)}
    current = rows[item["event_id"]]
    assert current["resolution_status"] == "excluded_fail_closed"
    assert current["public_announcement_ts"] == ""
    assert current["information_asymmetry_seconds"] == ""
    assert sum(
        row["resolution_status"] == "resolved_exact_public_timestamp"
        for row in rows.values()
    ) == 114
    assert sum(
        row["resolution_status"] == "excluded_fail_closed"
        for row in rows.values()
    ) == 60
