import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREP = ROOT / "data/public/metadata/g1_public_batch_0098_prep_evidence.json"
RESOLUTIONS = (
    ROOT
    / "data/processed/authorized_input_real/announcement_resolutions.csv"
)


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_worker3_sm_prep_is_owned_exact_and_fail_closed():
    prep = json.loads(PREP.read_text(encoding="utf-8"))
    assert prep["prep_only"] is True
    assert prep["research_use_only"] is True
    assert prep["worker_slot"] == 3
    assert int(prep["reserved_batch"]) >= 68
    assert (int(prep["reserved_batch"]) - 68) % 5 == 0
    assert prep["base_main_sha"] == "51d847052f163a0c61b3d9e2d74003d321a511a1"

    assert len(prep["items"]) == 1
    item = prep["items"][0]
    assert item["event_id"] == "HEJFE-5B6F87699FF5093E"
    assert item["historical_symbol"] == "SM"

    digest = hashlib.sha256(item["event_id"].encode("utf-8")).digest()
    digest_hex = digest.hex()
    owner = int.from_bytes(digest, "big") % 5
    assert digest_hex == prep["ownership_audit"]["sha256"]
    assert owner == prep["ownership_audit"]["sha256_mod_5"] == 3
    assert prep["ownership_audit"]["worker_3_owned"] is True

    release = datetime.fromisoformat(item["public_announcement_ts"])
    trade = datetime.fromisoformat(item["first_documented_illicit_trade_ts"])
    assert int((release - trade).total_seconds()) == 8520
    assert item["expected_information_asymmetry_seconds"] == 8520
    assert item["issuer_archive_clock_text"] == "May 5, 2015 5:30 pm ET"
    assert item["timestamp_evidence_kind"] == "explicit_release_clock"
    assert item["public_distribution_explicit"] is True
    assert item["source_grade"] == "A"
    assert prep["source_family"] == "official_issuer_release_archive"
    assert prep["source_reference"].endswith("press-releases?page=24")
    assert "/press-releases/detail/168/" in prep["release_detail_reference"]
    assert prep["corroboration_reference"].endswith(
        "2015-05-05_SM_Energy_Reports_Results_for_the_First_Quarter_168.pdf"
    )

    assert prep["live_validation"]["active_token_worker"] == 4
    assert prep["live_validation"]["active_token_state"] == "ASSIGNED_OTHER_WORKER"
    assert prep["live_validation"]["active_token_event_id"] == "HEJFE-809E53BB4081FBAE"
    assert prep["live_validation"]["unclaimed_by_active_package"] is True

    rows = {row["event_id"]: row for row in _rows(RESOLUTIONS)}
    current = rows[item["event_id"]]
    assert current["resolution_status"] == "excluded_fail_closed"
    assert current["public_announcement_ts"] == ""
    assert current["information_asymmetry_seconds"] == ""
    assert sum(
        row["resolution_status"] == "resolved_exact_public_timestamp"
        for row in rows.values()
    ) == 121
    assert sum(
        row["resolution_status"] == "excluded_fail_closed"
        for row in rows.values()
    ) == 53
