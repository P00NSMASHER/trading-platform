from __future__ import annotations
import ast, copy, csv, hashlib, json, os, subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import g1_acquisition_manifest as acquisition
import g1_source_research as research
import real_data_release_sprint as sprint
import research_receipt_rebuild as rebuild

ROOT = Path.cwd()
BASE = "7c4691089b8552b05ea9822309e835045dab247d"
WORKFLOW = ".github/workflows/g1-public-batch-0130-worker-1.yml"
SCRIPT = "scripts/g1_batch_0130_generate.py"
SPEC = "data/public/metadata/g1_public_batch_0130_integration_spec.json"
PREP = Path("data/public/metadata/g1_public_batch_0130_prep_evidence.json")
PREP_TEST = Path("tests/test_g1_public_batch_0130_prep.py")
BATCH = Path("data/public/metadata/g1_announcement_times_batch_0130.csv")
EVIDENCE = Path("data/public/metadata/g1_public_batch_0130_evidence.json")
FINAL_TEST = Path("tests/test_g1_public_batch_0130.py")
OLD_EXACT, OLD_EXCLUDED = 173, 1
NEW_EXACT, NEW_EXCLUDED = 174, 0

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def save(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def csv_rows(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

assert os.environ.get("BASE", BASE) == BASE
corpus = Path("data/processed/historical_events.csv")
assert digest(corpus) == "43fb221eed14c2a00a0e9d4531fe365dd264128625877a6cfc986cf50f862f12"
md = Path("data/processed/authorized_input_real")
events = {row["event_id"]: row for row in csv_rows(corpus)}
resolution_path = md / "announcement_resolutions.csv"
old_resolutions = csv_rows(resolution_path)
old_exact = {row["event_id"]: row for row in old_resolutions if row["resolution_status"] == "resolved_exact_public_timestamp"}
assert len(events) == 174 and len(old_exact) == OLD_EXACT

exclusion_path = md / "g1_final_timing_exclusions.json"
exclusions = load(exclusion_path)
assert len(exclusions["exclusions"]) == OLD_EXCLUDED

prep = load(PREP)
assert prep["prep_only"] is True and prep["base_main_sha"] == BASE
items = copy.deepcopy(prep["items"])
ids = {item["event_id"] for item in items}
assert len(items) == len(ids) == 1
assert ids == set(load(SPEC)["event_ids"])

for item in items:
    item.setdefault("source_reference", prep["primary_evidence"]["url"])
    eid = item["event_id"]
    event = events[eid]
    assert eid not in old_exact
    assert sum(row["event_id"] == eid for row in exclusions["exclusions"]) == 1
    assert int(hashlib.sha256(eid.encode("utf-8")).hexdigest(), 16) % 5 == 0
    assert event["historical_symbol"] == item["historical_symbol"]
    assert event["first_documented_illicit_trade_ts"].replace(" ", "T") == item["first_documented_illicit_trade_ts"][:19]
    trade = datetime.fromisoformat(event["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
    release = datetime.fromisoformat(item["public_announcement_ts"])
    assert trade < release <= trade + timedelta(days=7)
    assert int((release - trade).total_seconds()) == item["information_asymmetry_seconds"]
    assert item["source_family"] == "official_newswire_archive"
    assert item["source_grade"] == "A" and item["public_distribution_explicit"] is True
    assert item["source_reference"].startswith("https://www.globenewswire.com/news-release/2013/10/22/930758/")
    assert item["corroboration_reference"].startswith("https://www.sec.gov/Archives/edgar/data/")
    assert item["wire_source_code"] in {"BW", "MW"}
    item["timestamp_evidence_kind"] = "explicit_release_clock"

hints_path = Path("data/public/metadata/g1_source_research_20260928.json")
hints = load(hints_path)
trial = copy.deepcopy(hints)
trial["validation_probes"] = [row for row in trial.get("validation_probes", []) if row.get("event_id") not in ids]
for item in items:
    trial["validation_probes"].append(dict(
        item,
        probe_id=f'{item["historical_symbol"]}-batch0130',
        historical_event_match=True,
        exact_clock_observed=True,
        exact_public_release_ts=item["public_announcement_ts"],
        evidence_eligible=True,
    ))
research.validate_research_map(trial, exclusions)

save(EVIDENCE, {
    "schema_version": "1",
    "research_use_only": True,
    "base_main_sha": BASE,
    "batch_path": str(BATCH),
    "batch_sha256": digest(BATCH),
    "items": items,
    "previous_exact_count": OLD_EXACT,
    "expected_exact_count_after_batch": NEW_EXACT,
    "expected_excluded_after_batch": NEW_EXCLUDED,
    "previous_exact_timestamps": {eid: row["public_announcement_ts"] for eid, row in old_exact.items()},
    "publisher_archive_evidence": prep["publisher_archive_evidence"],
    "evidence_method": "GlobeNewswire migrated Marketwired release ID 930758 exposes the exact publisher timestamp October 22, 2013 08:03 ET and machine metadata 2013-10-22T12:03:00Z for the exact Gentex Q3 2013 financial-results release. Gentex IR and SEC Exhibit 99.1 independently corroborate release identity/date/content; conference-call and EDGAR times are not used.",
    "prohibited_substitutes": prep["prohibited_substitutes"],
})

exclusions["exclusions"] = [row for row in exclusions["exclusions"] if row["event_id"] not in ids]
exclusions["base_main_sha"] = BASE
exclusions["g1_state"].update(
    exact_resolved=NEW_EXACT,
    reviewed_excluded=NEW_EXCLUDED,
    raw_exact_time_evidence_gaps=NEW_EXCLUDED,
    exact_timing_analysis_eligible=NEW_EXACT,
)
save(exclusion_path, exclusions)

fields = ["event_id", "historical_symbol", "event_date", "public_announcement_ts", "timestamp_kind", "source_grade", "source_reference"]
contract_path = Path("config/metadata_sources.public_progress.json")
contract = load(contract_path)
contract["sources"].insert(0, {
    "source_id": "public-worker0-globenewswire-marketwired-batch-0130",
    "record_kind": "announcement_timestamp",
    "source_family": "official_newswire_archive",
    "path": str(BATCH),
    "enabled": True,
    "authorized": True,
    "data_classification": "public_research_replication",
    "delimiter": ",",
    "encoding": "utf-8",
    "timezone": "America/New_York",
    "column_map": {field: field for field in fields},
    "license_reference": "Public GlobeNewswire migrated Marketwired release ID 930758 exact publisher timestamp, with Gentex IR and SEC Exhibit 99.1 as identity/date/content corroboration. No licensed vendor data used.",
    "notes": "One exact first-public publisher clock from the migrated Marketwired/GlobeNewswire archive; substitute times are not used.",
})
contract["reviewed_announcement_exclusions"].update(expected_count=NEW_EXCLUDED, expected_sha256=digest(exclusion_path))
contract["purpose"] = f"Cumulative public point-in-time metadata: G1 has {NEW_EXACT} exact release timestamps and {NEW_EXCLUDED} reviewed fail-closed exclusions; G1 exact timing is complete while downstream G2/G5 gates remain independent."
save(contract_path, contract)

hints["priority_events"] = [row for row in hints.get("priority_events", []) if row.get("event_id") not in ids]
hints["validation_probes"] = [row for row in hints.get("validation_probes", []) if row.get("event_id") not in ids]
hints["base_main_sha"] = BASE
hints["current_g1_state"].update(
    public_exact_batch_count=89,
    exact_resolved_event_records=NEW_EXACT,
    reviewed_excluded_event_records=NEW_EXCLUDED,
    note="The latest integrated recovery is batch_0130; cumulative public exact-time batches are 89 and all 174 required event records have exact first-public timestamps.",
)
for item in items:
    hints["validation_probes"].append(dict(
        item,
        probe_id=f'{item["historical_symbol"]}-batch0130',
        historical_event_match=True,
        exact_clock_observed=True,
        exact_public_release_ts=item["public_announcement_ts"],
        evidence_eligible=False,
        disposition="RESOLVED_IN_BATCH_0130",
        reason="Promoted from GlobeNewswire migrated Marketwired release ID 930758 exact publisher timestamp with issuer-IR and SEC Exhibit corroboration.",
    ))
save(hints_path, hints)

assert rebuild.rebuild(ROOT, publish=True)["after"]["up_to_date"]
fresh = csv_rows(resolution_path)
by_id = {row["event_id"]: row for row in fresh}
assert len(by_id) == 174
for eid, old in old_exact.items():
    assert by_id[eid] == old
expected = {
    item["event_id"]: datetime.fromisoformat(item["public_announcement_ts"]).astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")
    for item in items
}
for item in items:
    row = by_id[item["event_id"]]
    assert row["resolution_status"] == "resolved_exact_public_timestamp"
    assert row["public_announcement_ts"] == expected[item["event_id"]]
excluded = [row for row in fresh if row["resolution_status"] == "excluded_fail_closed"]
assert len(excluded) == NEW_EXCLUDED
assert all(not row["public_announcement_ts"] and not row["information_asymmetry_seconds"] for row in excluded)
ready = load(md / "metadata_readiness_summary.json")
assert ready["announcement_exact_resolved"] == NEW_EXACT
assert ready["announcement_events_excluded"] == NEW_EXCLUDED
assert ready["ready_g1_exact_timing_analysis"] is True

acq = Path("data/public/metadata/g1_acquisition_manifest.json")
acq.write_text(acquisition.render_manifest(acquisition.build_manifest()), encoding="utf-8")
sprint_dir = Path("data/processed/real_data_release_sprint")
coverage = Path("data/processed/coverage_plan_real/coverage_summary.json")
sprint.refresh_coverage(
    coverage_summary_path=coverage,
    metadata_readiness_path=md / "metadata_readiness_summary.json",
    metadata_quality_path=md / "metadata_quality_summary.json",
    requirements_manifest_path=sprint_dir / "requirements_manifest.json",
    unresolved_gates_path=coverage.parent / "unresolved_gates.csv",
)
status = sprint.build_status(
    requirements_manifest_path=sprint_dir / "requirements_manifest.json",
    coverage_summary_path=coverage,
    metadata_readiness_path=md / "metadata_readiness_summary.json",
    metadata_quality_path=md / "metadata_quality_summary.json",
    outpath=sprint_dir / "step_status.json",
)
step9 = next(row for row in status["steps"] if row["step"] == 9)
assert step9["status"] == "PASS"
assert "174/174" in step9["evidence"] and "0" in step9["evidence"]

test_files = [
    "tests/test_g1_source_research.py",
    "tests/test_g1_acquisition_manifest.py",
    "tests/test_real_data_release_sprint.py",
    *sorted(str(path) for path in Path("tests").glob("test_g1_public_batch_*.py")),
]
for filename in test_files:
    path = Path(filename)
    text = path.read_text(encoding="utf-8")
    if filename.endswith("test_g1_source_research.py"):
        pairs = [
            ('report["exact_resolved_event_records"] == 173', 'report["exact_resolved_event_records"] == 174'),
            ('report["reviewed_excluded_event_records"] == 1', 'report["reviewed_excluded_event_records"] == 0'),
            ('state["public_exact_batch_count"] == 88', 'state["public_exact_batch_count"] == 89'),
            ('state["exact_resolved_event_records"] == 173', 'state["exact_resolved_event_records"] == 174'),
        ]
    elif filename.endswith("test_g1_acquisition_manifest.py"):
        pairs = [
            ('manifest["state"]["exact_resolved"] == 173', 'manifest["state"]["exact_resolved"] == 174'),
            ('manifest["state"]["acquisition_needed"] == 1', 'manifest["state"]["acquisition_needed"] == 0'),
            ('len(manifest["work_queue"]) == 1', 'len(manifest["work_queue"]) == 0'),
            ('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 1', 'len({row["dedupe_key"] for row in manifest["work_queue"]}) == 0'),
            ('len(resolved) == 173', 'len(resolved) == 174'),
            ('len(unresolved) == 1', 'len(unresolved) == 0'),
            ('"GNTX"', ''),
            ('[1000]', '[]'),
        ]
    elif filename.endswith("test_real_data_release_sprint.py"):
        pairs = [('updated["missing_exact_announcement_timestamps"] == 1', 'updated["missing_exact_announcement_timestamps"] == 0')]
    else:
        pairs = [
            ('(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (173,1)', '(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (174,0)'),
            ('(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (173, 1)', '(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (174, 0)'),
            ('"173/174" in step9["evidence"] and "1" in step9["evidence"]', '"174/174" in step9["evidence"] and "0" in step9["evidence"]'),
            ('len(excluded)==1', 'len(excluded)==0'),
            ('len(excluded) == 1', 'len(excluded) == 0'),
            ('len(ex)==1', 'len(ex)==0'),
            ('len(ex) == 1', 'len(ex) == 0'),
            ('step9["status"]=="SOURCE_BLOCKED"', 'step9["status"]=="PASS"'),
            ('step9["status"] == "SOURCE_BLOCKED"', 'step9["status"] == "PASS"'),
            ('readiness["ready_g1_exact_timing_analysis"] is False', 'readiness["ready_g1_exact_timing_analysis"] is True'),
        ]
    for old, new in pairs:
        text = text.replace(old, new)
    ast.parse(text)
    path.write_text(text, encoding="utf-8")

docs = Path("docs/g1_announcement_times.md")
text = docs.read_text(encoding="utf-8")
assert "88 public exact-time batches / 173 exact-resolved" in text
text = text.replace("88 public exact-time batches / 173 exact-resolved", "89 public exact-time batches / 174 exact-resolved", 1)
text += """

### Batch 0130: GNTX

GlobeNewswire migrated Marketwired release ID 930758 exposes the exact first-public publisher timestamp for Gentex Q3 2013 results as October 22, 2013 08:03 ET, with machine metadata 2013-10-22T12:03:00Z. Gentex IR and SEC Exhibit 99.1 independently corroborate identity/date/content. Conference-call, EDGAR, archive-capture and inferred times are not used. This advances G1 from 173 exact / 1 reviewed exclusion to 174/174 exact / 0 exclusions. Step 9 passes.
"""
docs.write_text(text, encoding="utf-8")

# Final batch regression is staged explicitly by the source branch.
assert rebuild.rebuild(ROOT, publish=False)["before"]["up_to_date"]

changed = set(subprocess.check_output(["git", "diff", "--name-only", BASE], text=True).splitlines())
changed.update({str(BATCH), str(EVIDENCE), str(FINAL_TEST)})
permitted = {
    str(contract_path), str(exclusion_path), str(hints_path), str(acq), str(BATCH), str(EVIDENCE), str(FINAL_TEST),
    "docs/g1_announcement_times.md", "src/metadata_resolver.py", "tests/test_metadata_resolver.py",
    "tests/test_g1_source_research.py", "tests/test_g1_acquisition_manifest.py", "tests/test_real_data_release_sprint.py",
    str(coverage), str(coverage.parent / "unresolved_gates.csv"), str(sprint_dir / "step_status.json"),
    "data/processed/research_receipt_bundle.json", "data/processed/real_data_replay/real_data_replay_status.json",
} | {str(path) for path in Path("tests").glob("test_g1_public_batch_*.py")} | {str(md / name) for name in rebuild.METADATA_RECEIPTS}
unexpected = changed - permitted
assert not unexpected, f"Unexpected changed files: {sorted(unexpected)}"

allow_path = Path("config/release_drift_allowlist.json")
allow = load(allow_path)
reason = "G1 batch 0130 GNTX exact first-public publisher timestamp from GlobeNewswire migrated Marketwired release ID 930758; deterministic 174/174 exact with prior evidence preserved."
for filename in sorted(changed):
    section = "intentional_release_modifications" if filename in allow["intentional_release_modifications"] else "repository_additions"
    allow[section][filename] = {"expected_sha256": digest(filename), "reason": reason}
save(allow_path, allow)
changed.add(str(allow_path))
subprocess.run(["git", "add", "--", *sorted(changed)], check=True)

audit = Path("private_runtime/audit/g1-batch-0130")
audit.mkdir(parents=True, exist_ok=True)
save(audit / "verification.json", {
    "base_main_sha": BASE,
    "source_head_sha": os.environ["GITHUB_SHA"],
    "exact": NEW_EXACT,
    "reviewed_excluded": NEW_EXCLUDED,
    "previous_exact_preserved": OLD_EXACT,
    "new_event_ids": sorted(ids),
    "step9": "PASS",
    "evaluation_release_permitted": False,
    "deterministic_rebuild_matches": True,
})
print(json.dumps({"exact": NEW_EXACT, "reviewed_excluded": NEW_EXCLUDED, "new_events": sorted(ids)}, indent=2))
