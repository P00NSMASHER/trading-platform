from __future__ import annotations

import ast
import copy
import csv
import hashlib
import io
import json
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import g1_source_research as research
import g1_acquisition_manifest as acquisition
import research_receipt_rebuild as rebuild
import real_data_release_sprint as sprint

ROOT = Path.cwd()
BASE = "1692ee04dbd6beb715b9f2b8f5ec621713640368"
WORKFLOW = ".github/workflows/g1-public-batch-0036.yml"
SCRIPT = "scripts/g1_batch_0036_generate.py"

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def save(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def rows(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

corpus = Path("data/processed/historical_events.csv")
assert sha(corpus) == "43fb221eed14c2a00a0e9d4531fe365dd264128625877a6cfc986cf50f862f12"
md = Path("data/processed/authorized_input_real")
events = rows(corpus)
old_exact = {
    r["event_id"]: r
    for r in rows(md / "announcement_resolutions.csv")
    if r["resolution_status"] == "resolved_exact_public_timestamp"
}
assert len(events) == 174 and len(old_exact) == 42

exclusion_path = md / "g1_final_timing_exclusions.json"
exclusions = load(exclusion_path)
assert len(exclusions["exclusions"]) == 132

batch = Path("data/public/metadata/g1_announcement_times_batch_0036.csv")
evidence_path = Path("data/public/metadata/g1_public_batch_0036_evidence.json")
assert not batch.exists() and not evidence_path.exists()

specs = [
    {
        "event_id": "HEJFE-D4E8CD312A2AA576",
        "historical_symbol": "ISSI",
        "expected_trade": "2012-01-25 14:51:00",
        "clock": "2012-01-25T16:10:00-05:00",
        "publisher_timestamp_text": "Jan 25, 2012, 04:10 ET",
        "release_title": "ISSI Announces First Fiscal Quarter 2012 Results",
        "source_reference": "https://www.prnewswire.com/news/integrated-silicon-solution%2C-inc./?page=4",
        "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/854701/000114420412003913/v300357_ex99-1.htm",
        "corroboration_basis": "PR Newswire's issuer archive explicitly timestamps the matching ISSI first-quarter results at Jan 25, 2012 04:10 ET. SEC Exhibit 99.1 independently corroborates issuer, release date and financial content.",
        "expected_delta": 4740,
        "source_family": "official_newswire_archive",
        "source_grade": "A",
    },
    {
        "event_id": "HEJFE-89844B5980EB5339",
        "historical_symbol": "AF",
        "expected_trade": "2012-01-25 15:18:00",
        "clock": "2012-01-25T16:30:00-05:00",
        "publisher_timestamp_text": "Jan 25, 2012, 04:30 ET",
        "release_title": "Astoria Financial Corporation Reports Fourth Quarter and Full Year Earnings Per Share of $0.12 and $0.70, Respectively",
        "source_reference": "https://www.prnewswire.com/news/astoria-financial-corporation/?page=4",
        "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/910322/000114420412004067/v300361_ex99-1.htm",
        "corroboration_basis": "PR Newswire's issuer archive explicitly timestamps the matching Astoria earnings release at Jan 25, 2012 04:30 ET. SEC Exhibit 99.1 independently corroborates issuer, release date and financial content.",
        "expected_delta": 4320,
        "source_family": "official_newswire_archive",
        "source_grade": "A",
    },
    {
        "event_id": "HEJFE-74011A906BCCABE9",
        "historical_symbol": "AGP",
        "expected_trade": "2011-10-27 13:03:00",
        "clock": "2011-10-28T06:00:00-04:00",
        "publisher_timestamp_text": "Oct 28, 2011, 06:00 ET",
        "release_title": "Amerigroup Reports Third Quarter 2011 Results",
        "source_reference": "https://www.prnewswire.com/news/amerigroup-corporation/?page=2",
        "corroboration_reference": "https://www.sec.gov/Archives/edgar/data/1064863/000114420411059887/v238314_ex99-1.htm",
        "corroboration_basis": "PR Newswire's issuer archive explicitly timestamps the matching Amerigroup third-quarter release at Oct 28, 2011 06:00 ET. SEC Exhibit 99.1 independently corroborates issuer, release date and financial content.",
        "expected_delta": 61020,
        "source_family": "official_newswire_archive",
        "source_grade": "A",
    },
    {
        "event_id": "HEJFE-99CCB9D9BECE4E72",
        "historical_symbol": "IDXX",
        "expected_trade": "2012-01-26 13:47:00",
        "clock": "2012-01-27T07:00:00-05:00",
        "publisher_timestamp_text": "Jan 27, 2012 7:00 am EST",
        "release_title": "IDEXX Laboratories Announces Fourth Quarter and Full Year Results",
        "source_reference": "https://ir.idexx.com/news-events/press-releases?page=28",
        "corroboration_reference": "https://ir.idexx.com/news-events/press-releases/detail/339/idexx-laboratories-announces-fourth-quarter-and-full-year-results",
        "corroboration_basis": "IDEXX's own investor-relations archive explicitly timestamps the matching earnings release at Jan 27, 2012 7:00 am EST; the issuer detail page independently matches the PR Newswire release, reporting period and financial content.",
        "expected_delta": 61980,
        "source_family": "issuer_investor_relations_archive",
        "source_grade": "A",
    },
]

items = []
hints_path = Path("data/public/metadata/g1_source_research_20260928.json")
hints = load(hints_path)
trial = copy.deepcopy(hints)

for spec in specs:
    matches = [r for r in events if r["event_id"] == spec["event_id"]]
    assert len(matches) == 1
    event = matches[0]
    assert event["historical_symbol"] == spec["historical_symbol"]
    assert event["first_documented_illicit_trade_ts"] == spec["expected_trade"]
    assert spec["event_id"] not in old_exact
    assert sum(r["event_id"] == spec["event_id"] for r in exclusions["exclusions"]) == 1

    trade = datetime.fromisoformat(event["first_documented_illicit_trade_ts"]).replace(
        tzinfo=ZoneInfo("America/New_York")
    )
    release = datetime.fromisoformat(spec["clock"])
    assert trade < release <= trade + timedelta(days=7)
    delta = int((release - trade).total_seconds())
    assert delta == spec["expected_delta"]

    item = {
        "event_id": spec["event_id"],
        "historical_symbol": spec["historical_symbol"],
        "event_date": trade.date().isoformat(),
        "first_documented_illicit_trade_ts": event["first_documented_illicit_trade_ts"],
        "public_announcement_ts": release.isoformat(),
        "timestamp_kind": "first_public_release",
        "timestamp_evidence_kind": "publisher_timestamp",
        "source_family": spec["source_family"],
        "source_grade": spec["source_grade"],
        "publisher_timestamp_text": spec["publisher_timestamp_text"],
        "release_title": spec["release_title"],
        "source_reference": spec["source_reference"],
        "corroboration_reference": spec["corroboration_reference"],
        "corroboration_basis": spec["corroboration_basis"],
        "reviewed_on": "2026-09-29",
        "information_asymmetry_seconds": delta,
    }
    items.append(item)
    trial["validation_probes"].append(
        dict(
            item,
            probe_id=f"{spec['historical_symbol']}-{spec['event_id'][-6:]}-batch0036",
            historical_event_match=True,
            exact_clock_observed=True,
            exact_public_release_ts=release.isoformat(),
            evidence_eligible=True,
        )
    )

research.validate_research_map(trial, exclusions)

fields = [
    "event_id",
    "historical_symbol",
    "event_date",
    "public_announcement_ts",
    "timestamp_kind",
    "source_grade",
    "source_reference",
]
output = io.StringIO(newline="")
writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
writer.writeheader()
for item in items:
    writer.writerow({k: item[k] for k in fields})
batch.write_text(output.getvalue(), encoding="utf-8")

save(
    evidence_path,
    {
        "schema_version": "1",
        "research_use_only": True,
        "base_main_sha": BASE,
        "batch_path": str(batch),
        "batch_sha256": sha(batch),
        "items": items,
        "previous_exact_count": 42,
        "expected_exact_count_after_batch": 46,
        "expected_excluded_after_batch": 128,
        "previous_exact_timestamps": {
            k: r["public_announcement_ts"] for k, r in old_exact.items()
        },
        "evidence_method": "Three primary PR Newswire archive timestamps plus one issuer-IR exact publication timestamp. SEC/issuer detail pages corroborate identity and content. CI checks chronology, normalization and deterministic receipts; scheduled call, EDGAR acceptance, inferred and date-only clocks are excluded.",
        "prohibited_substitutes": [
            "edgar_acceptance_time",
            "scheduled_call_time",
            "archive_capture_time",
            "inferred_clock",
            "date_only",
        ],
    },
)

resolved_ids = {x["event_id"] for x in items}
exclusions["exclusions"] = [
    r for r in exclusions["exclusions"] if r["event_id"] not in resolved_ids
]
exclusions["base_main_sha"] = BASE
exclusions["g1_state"].update(
    exact_resolved=46,
    reviewed_excluded=128,
    raw_exact_time_evidence_gaps=128,
    exact_timing_analysis_eligible=46,
)
save(exclusion_path, exclusions)

contract_path = Path("config/metadata_sources.public_progress.json")
contract = load(contract_path)
contract["sources"].insert(
    0,
    {
        "source_id": "public-prnewswire-idxx-batch-0036",
        "record_kind": "announcement_timestamp",
        "source_family": "official_newswire_archive",
        "path": str(batch),
        "enabled": True,
        "authorized": True,
        "data_classification": "public_official_data",
        "delimiter": ",",
        "encoding": "utf-8",
        "timezone": "America/New_York",
        "column_map": {k: k for k in fields},
        "license_reference": "Public PR Newswire issuer archives for ISSI, Astoria and Amerigroup plus IDEXX issuer investor-relations archive; matching SEC/issuer detail pages retained for corroboration. No licensed vendor data used.",
        "notes": "ISSI 2012-01-25 16:10 EST; AF 2012-01-25 16:30 EST; AGP 2011-10-28 06:00 EDT; IDXX 2012-01-27 07:00 EST. No scheduled-call or EDGAR acceptance clocks used.",
    },
)
contract["reviewed_announcement_exclusions"].update(
    expected_count=128, expected_sha256=sha(exclusion_path)
)
contract["purpose"] = (
    "Cumulative public point-in-time metadata: G1 has 46 exact release timestamps "
    "and 128 reviewed fail-closed exclusions; exact-timing and all independent "
    "non-synthetic release locks remain fail-closed."
)
save(contract_path, contract)

hints["base_main_sha"] = BASE
hints["current_g1_state"].update(
    public_exact_batch_count=36,
    exact_resolved_event_records=46,
    reviewed_excluded_event_records=128,
    note="The repository is at batch_0036; cumulative exact event records are 46 because some public batches resolve more than one historical event.",
)
for item in items:
    hints["validation_probes"].append(
        dict(
            item,
            probe_id=f"{item['historical_symbol']}-{item['event_id'][-6:]}-batch0036",
            historical_event_match=True,
            exact_clock_observed=True,
            exact_public_release_ts=item["public_announcement_ts"],
            evidence_eligible=False,
            disposition="RESOLVED_IN_BATCH_0036",
            reason="Promoted through separately reviewed issuer/preserved-wire evidence with independent corroboration. This research hint cannot resolve events by itself.",
        )
    )
save(hints_path, hints)

assert rebuild.rebuild(ROOT, publish=True)["after"]["up_to_date"]

fresh = rows(md / "announcement_resolutions.csv")
by_id = {r["event_id"]: r for r in fresh}
assert len(by_id) == 174
for old_id, old in old_exact.items():
    assert by_id[old_id] == old, "Existing exact evidence must remain unchanged"

expected_utc = {
    "HEJFE-D4E8CD312A2AA576": "2012-01-25T21:10:00Z",
    "HEJFE-89844B5980EB5339": "2012-01-25T21:30:00Z",
    "HEJFE-74011A906BCCABE9": "2011-10-28T10:00:00Z",
    "HEJFE-99CCB9D9BECE4E72": "2012-01-27T12:00:00Z",
}
for item in items:
    row = by_id[item["event_id"]]
    assert row["resolution_status"] == "resolved_exact_public_timestamp"
    assert row["public_announcement_ts"] == expected_utc[item["event_id"]]
    assert row["source_grade"] == item["source_grade"]
    assert int(row["information_asymmetry_seconds"]) == item["information_asymmetry_seconds"]

excluded = [r for r in fresh if r["resolution_status"] == "excluded_fail_closed"]
assert len(excluded) == 128
assert all(
    not r["public_announcement_ts"] and not r["information_asymmetry_seconds"]
    for r in excluded
)

ready = load(md / "metadata_readiness_summary.json")
assert ready["announcement_exact_resolved"] == 46
assert ready["announcement_events_excluded"] == 128
assert ready["ready_g1_exact_timing_analysis"] is False
assert ready["ready_for_non_synthetic_model_evaluation_metadata"] is False

acquisition_path = Path("data/public/metadata/g1_acquisition_manifest.json")
acquisition_path.write_text(
    acquisition.render_manifest(acquisition.build_manifest()), encoding="utf-8"
)

sd = Path("data/processed/real_data_release_sprint")
cp = Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(
    coverage_summary_path=cp,
    metadata_readiness_path=md / "metadata_readiness_summary.json",
    metadata_quality_path=md / "metadata_quality_summary.json",
    requirements_manifest_path=sd / "requirements_manifest.json",
    unresolved_gates_path=cp.parent / "unresolved_gates.csv",
)
status = sprint.build_status(
    requirements_manifest_path=sd / "requirements_manifest.json",
    coverage_summary_path=cp,
    metadata_readiness_path=md / "metadata_readiness_summary.json",
    metadata_quality_path=md / "metadata_quality_summary.json",
    outpath=sd / "step_status.json",
)
step9 = next(r for r in status["steps"] if r["step"] == 9)
assert step9["status"] == "SOURCE_BLOCKED"
assert "46/174" in step9["evidence"] and "128" in step9["evidence"]
assert not status["all_12_genuinely_complete"]

# Refresh global live-count regressions only.
for filename in [
    "tests/test_g1_source_research.py",
    "tests/test_g1_acquisition_manifest.py",
    "tests/test_real_data_release_sprint.py",
    "tests/test_g1_public_batch_0032.py",
    "tests/test_g1_public_batch_0034.py",
    "tests/test_g1_public_batch_0035.py",
]:
    p = Path(filename)
    txt = p.read_text()
    txt = txt.replace("== (42,132)", "== (46,128)")
    txt = txt.replace("len(excluded)==132", "len(excluded)==128")
    txt = txt.replace('len(excluded) == 132', 'len(excluded) == 128')
    txt = txt.replace('"42/174" in step9["evidence"] and "132" in step9["evidence"]',
                      '"46/174" in step9["evidence"] and "128" in step9["evidence"]')
    txt = txt.replace('updated["missing_exact_announcement_timestamps"] == 132',
                      'updated["missing_exact_announcement_timestamps"] == 128')
    txt = re.sub(r"== 38\b", "== 42", txt)
    txt = re.sub(r"== 136\b", "== 132", txt)
    if filename.endswith("test_g1_source_research.py"):
        txt = txt.replace('state["public_exact_batch_count"] == 35',
                          'state["public_exact_batch_count"] == 35')
    ast.parse(txt)
    p.write_text(txt)

p = Path("docs/g1_announcement_times.md")
txt = p.read_text().replace(
    "35 public exact-time batches / 42 exact-resolved",
    "36 public exact-time batches / 46 exact-resolved",
)
txt += """
### Batch 0036: ISSI + Astoria + Amerigroup + IDEXX

Primary public archives supply four exact first-public clocks: ISSI at 2012-01-25 16:10 EST, Astoria Financial at 2012-01-25 16:30 EST, Amerigroup at 2011-10-28 06:00 EDT, and IDEXX at 2012-01-27 07:00 EST. The first three are explicit PR Newswire issuer-archive timestamps with matching SEC exhibits; IDEXX is an explicit issuer investor-relations timestamp with the matching PR Newswire release detail. The releases are 4,740, 4,320, 61,020 and 61,980 seconds after their frozen first trades. This advances G1 from 42 exact / 132 reviewed exclusions to 46 exact / 128 reviewed exclusions. Scheduled conference-call times, EDGAR acceptance times, date-only pages and inferred clocks remain prohibited substitutes. Step 9 remains SOURCE_BLOCKED.
"""
p.write_text(txt)

test_path = Path("tests/test_g1_public_batch_0036.py")
test_source = '''from __future__ import annotations
import csv
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
def read_rows(path):
    with path.open(newline="",encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
def test_batch_0036_exact_clocks_and_event_match():
    dossier=json.loads((ROOT/"data/public/metadata/g1_public_batch_0036_evidence.json").read_text())
    events={r["event_id"]:r for r in read_rows(ROOT/"data/processed/historical_events.csv")}
    resolved={r["event_id"]:r for r in read_rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    expected={
        "HEJFE-D4E8CD312A2AA576":("ISSI","2012-01-25T21:10:00Z",4740,"A"),
        "HEJFE-89844B5980EB5339":("AF","2012-01-25T21:30:00Z",4320,"A"),
        "HEJFE-74011A906BCCABE9":("AGP","2011-10-28T10:00:00Z",61020,"A"),
        "HEJFE-99CCB9D9BECE4E72":("IDXX","2012-01-27T12:00:00Z",61980,"A"),
    }
    assert len(dossier["items"])==4
    for item in dossier["items"]:
        symbol,utc,delta,grade=expected[item["event_id"]]
        event=events[item["event_id"]]
        trade=datetime.fromisoformat(event["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
        release=datetime.fromisoformat(item["public_announcement_ts"])
        assert event["historical_symbol"]==symbol
        assert trade < release <= trade + timedelta(days=7)
        assert int((release-trade).total_seconds())==delta
        assert resolved[item["event_id"]]["public_announcement_ts"]==utc
        assert resolved[item["event_id"]]["resolution_status"]=="resolved_exact_public_timestamp"
        assert resolved[item["event_id"]]["source_grade"]==grade
        assert item["source_reference"].startswith("https://")
        assert item["corroboration_reference"].startswith("https://")
def test_batch_0036_hash_prior_evidence_and_fail_closed_remainder():
    dossier=json.loads((ROOT/"data/public/metadata/g1_public_batch_0036_evidence.json").read_text())
    assert hashlib.sha256((ROOT/dossier["batch_path"]).read_bytes()).hexdigest()==dossier["batch_sha256"]
    by_id={r["event_id"]:r for r in read_rows(ROOT/"data/processed/authorized_input_real/announcement_resolutions.csv")}
    assert len(by_id)==174
    for eid,timestamp in dossier["previous_exact_timestamps"].items():
        assert by_id[eid]["public_announcement_ts"]==timestamp
        assert by_id[eid]["resolution_status"]=="resolved_exact_public_timestamp"
    excluded=[r for r in by_id.values() if r["resolution_status"]=="excluded_fail_closed"]
    assert len(excluded)==128
    assert all(not r["public_announcement_ts"] and not r["information_asymmetry_seconds"] for r in excluded)
'''
ast.parse(test_source)
test_path.write_text(test_source)

assert rebuild.rebuild(ROOT, publish=False)["before"]["up_to_date"]

changed = set(
    subprocess.check_output(["git", "diff", "--name-only", BASE], text=True).splitlines()
)
changed.update([str(batch), str(evidence_path), str(test_path), SCRIPT])

permitted = {
    WORKFLOW, SCRIPT, str(contract_path), str(exclusion_path), str(hints_path),
    str(acquisition_path), str(batch), str(evidence_path), str(test_path),
    "docs/g1_announcement_times.md",
    "tests/test_g1_source_research.py", "tests/test_g1_acquisition_manifest.py",
    "tests/test_real_data_release_sprint.py", "tests/test_g1_public_batch_0032.py",
    "tests/test_g1_public_batch_0034.py", "tests/test_g1_public_batch_0035.py",
    str(cp), str(cp.parent/"unresolved_gates.csv"), str(sd/"step_status.json"),
    "data/processed/research_receipt_bundle.json",
    "data/processed/real_data_replay/real_data_replay_status.json",
} | {str(md/name) for name in rebuild.METADATA_RECEIPTS}
assert changed <= permitted, f"Unexpected changes: {changed-permitted}"

allowpath = Path("config/release_drift_allowlist.json")
allow = load(allowpath)
reason = (
    "G1 batch 0036: ISSI, Astoria and Amerigroup primary PR Newswire clocks plus "
    "IDEXX issuer-IR exact clock; deterministic 46 exact / 128 reviewed exclusions "
    "with all prior exact evidence preserved and release gates unchanged."
)
for name in sorted(changed):
    section = (
        "intentional_release_modifications"
        if name in allow["intentional_release_modifications"]
        else "repository_additions"
    )
    allow[section][name] = {"expected_sha256": sha(name), "reason": reason}
save(allowpath, allow)
changed.add(str(allowpath))

subprocess.run(["git", "add", "--", *sorted(changed)], check=True)

audit = Path("private_runtime/audit/g1-batch-0035")
audit.mkdir(parents=True, exist_ok=True)
save(
    audit/"verification.json",
    {
        "base_main_sha": BASE,
        "source_head_sha": os.environ["GITHUB_SHA"],
        "exact": 46,
        "reviewed_excluded": 128,
        "previous_exact_preserved": 42,
        "new_events": items,
        "step9": "SOURCE_BLOCKED",
        "evaluation_release_permitted": False,
        "deterministic_rebuild_matches": True,
        "tracked_change_sha256": {name: sha(name) for name in sorted(changed)},
    },
)
print(json.dumps({
    "exact":46,
    "reviewed_excluded":128,
    "new_events":[x["event_id"] for x in items],
    "step9":"SOURCE_BLOCKED"
}, indent=2))
