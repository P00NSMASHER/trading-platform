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
BASE = "828810d4e168a08498c7087075d91a9406f3cd6f"
WORKFLOW = ".github/workflows/g1-public-batch-0116-worker-1.yml"
SCRIPT = "scripts/g1_batch_0116_generate.py"
SPEC = "data/public/metadata/g1_public_batch_0116_integration_spec.json"
PREP = Path("data/public/metadata/g1_public_batch_0116_prep_evidence.json")
PREP_TEST = Path("tests/test_g1_public_batch_0116_prep.py")
BATCH = Path("data/public/metadata/g1_announcement_times_batch_0116.csv")
EVIDENCE = Path("data/public/metadata/g1_public_batch_0116_evidence.json")
FINAL_TEST = Path("tests/test_g1_public_batch_0116.py")
OLD_EXACT, OLD_EXCLUDED = 145, 29
NEW_EXACT, NEW_EXCLUDED = 159, 15

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
assert digest(BATCH) == prep["batch_sha256"]
items = copy.deepcopy(prep["items"])
ids = {item["event_id"] for item in items}
assert len(items) == len(ids) == 14
assert ids == set(load(SPEC)["event_ids"])

for item in items:
    eid = item["event_id"]
    event = events[eid]
    assert eid not in old_exact
    assert sum(row["event_id"] == eid for row in exclusions["exclusions"]) == 1
    assert int(hashlib.sha256(eid.encode("utf-8")).hexdigest(), 16) % 5 == 1
    assert event["historical_symbol"] == item["historical_symbol"]
    assert event["first_documented_illicit_trade_ts"] == item["first_documented_illicit_trade_ts"]
    trade = datetime.fromisoformat(event["first_documented_illicit_trade_ts"]).replace(tzinfo=ZoneInfo("America/New_York"))
    release = datetime.fromisoformat(item["public_announcement_ts"])
    assert trade < release <= trade + timedelta(days=7)
    assert int((release - trade).total_seconds()) == item["information_asymmetry_seconds"]
    assert item["source_family"] == "federal_court_public_distribution_record"
    assert item["source_grade"] == "A" and item["public_distribution_explicit"] is True
    assert item["source_reference"].startswith("https://storage.courtlistener.com/recap/")
    assert item["corroboration_reference"].startswith(("https://github.com/", "https://www.sec.gov/"))
    assert item["wire_source_code"] in {"BW", "MW"}
    item["timestamp_evidence_kind"] = "explicit_release_clock"

hints_path = Path("data/public/metadata/g1_source_research_20260928.json")
hints = load(hints_path)
trial = copy.deepcopy(hints)
trial["validation_probes"] = [row for row in trial.get("validation_probes", []) if row.get("event_id") not in ids]
for item in items:
    trial["validation_probes"].append(dict(
        item,
        probe_id=f'{item["historical_symbol"]}-batch0116',
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
    "court_artifact": prep["court_artifact"],
    "evidence_method": prep["evidence_method"],
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
    "source_id": "public-worker1-federal-court-gx8002-batch-0116",
    "record_kind": "announcement_timestamp",
    "source_family": "federal_court_public_distribution_record",
    "path": str(BATCH),
    "enabled": True,
    "authorized": True,
    "data_classification": "public_official_data",
    "delimiter": ",",
    "encoding": "utf-8",
    "timezone": "America/New_York",
    "column_map": {field: field for field in fields},
    "license_reference": "Filed E.D.N.Y. GX 8002 Document 367-2 explicit press-release/public-distribution clocks, with exact release identity/date corroborated by pinned public press-release members and an official SEC Exhibit 99.1 for Pandora. No licensed vendor data used.",
    "notes": "Fourteen exact first-public distribution clocks; prohibited substitute times are not used.",
})
contract["reviewed_announcement_exclusions"].update(expected_count=NEW_EXCLUDED, expected_sha256=digest(exclusion_path))
contract["purpose"] = f"Cumulative public point-in-time metadata: G1 has {NEW_EXACT} exact release timestamps and {NEW_EXCLUDED} reviewed fail-closed exclusions; exact-timing and all independent non-synthetic release locks remain fail-closed."
save(contract_path, contract)

hints["priority_events"] = [row for row in hints.get("priority_events", []) if row.get("event_id") not in ids]
hints["validation_probes"] = [row for row in hints.get("validation_probes", []) if row.get("event_id") not in ids]
hints["base_main_sha"] = BASE
hints["current_g1_state"].update(
    public_exact_batch_count=83,
    exact_resolved_event_records=NEW_EXACT,
    reviewed_excluded_event_records=NEW_EXCLUDED,
    note="The latest integrated recovery is batch_0116; cumulative public exact-time batches are 83 and cumulative exact event records are 159 because some public batches resolve more than one historical event.",
)
for item in items:
    hints["validation_probes"].append(dict(
        item,
        probe_id=f'{item["historical_symbol"]}-batch0116',
        historical_event_match=True,
        exact_clock_observed=True,
        exact_public_release_ts=item["public_announcement_ts"],
        evidence_eligible=False,
        disposition="RESOLVED_IN_BATCH_0116",
        reason="Promoted from filed federal-court GX 8002 explicit public-distribution clock with pinned press-release/SEC identity corroboration.",
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
assert ready["ready_g1_exact_timing_analysis"] is False

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
assert step9["status"] == "SOURCE_BLOCKED"
assert "159/174" in step9["evidence"] and "15" in step9["evidence"]

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
            ('report["exact_resolved_event_records"] == 145', 'report["exact_resolved_event_records"] == 159'),
            ('report["reviewed_excluded_event_records"] == 29', 'report["reviewed_excluded_event_records"] == 15'),
            ('report["priority_event_count"] == 1', 'report["priority_event_count"] == 0'),
            ('[\n        "NKE"\n    ]', '[]'),
            ('state["public_exact_batch_count"] == 82', 'state["public_exact_batch_count"] == 83'),
            ('state["exact_resolved_event_records"] == 145', 'state["exact_resolved_event_records"] == 159'),
        ]
    elif filename.endswith("test_g1_acquisition_manifest.py"):
        pairs = [
            ('manifest["state"]["exact_resolved"] == 145', 'manifest["state"]["exact_resolved"] == 159'),
            ('manifest["state"]["acquisition_needed"] == 29', 'manifest["state"]["acquisition_needed"] == 15'),
            ('len(manifest["work_queue"]) == 29', 'len(manifest["work_queue"]) == 15'),
            ('len({row["dedupe_key"] for row in manifest["work_queue"]}) == 29', 'len({row["dedupe_key"] for row in manifest["work_queue"]}) == 15'),
            ('len(resolved) == 145', 'len(resolved) == 159'),
            ('len(unresolved) == 29', 'len(unresolved) == 15'),
            ('"NKE", "VMW", "EW", "DGI", "PNRA"', '"VMW", "EW", "PNRA", "ISIL", "BIO"'),
            ('[1, 4, 6, 1000, 1000]', '[4, 6, 1000, 1000, 1000]'),
        ]
    elif filename.endswith("test_real_data_release_sprint.py"):
        pairs = [('updated["missing_exact_announcement_timestamps"] == 29', 'updated["missing_exact_announcement_timestamps"] == 15')]
    else:
        pairs = [
            ('(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (145,29)', '(readiness["announcement_exact_resolved"],readiness["announcement_events_excluded"]) == (159,15)'),
            ('(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (145, 29)', '(readiness["announcement_exact_resolved"], readiness["announcement_events_excluded"]) == (159, 15)'),
            ('"145/174" in step9["evidence"] and "29" in step9["evidence"]', '"159/174" in step9["evidence"] and "15" in step9["evidence"]'),
            ('len(excluded)==29', 'len(excluded)==15'),
            ('len(excluded) == 29', 'len(excluded) == 15'),
            ('len(ex)==29', 'len(ex)==15'),
            ('len(ex) == 29', 'len(ex) == 15'),
        ]
    for old, new in pairs:
        text = text.replace(old, new)
    ast.parse(text)
    path.write_text(text, encoding="utf-8")

docs = Path("docs/g1_announcement_times.md")
text = docs.read_text(encoding="utf-8")
assert "82 public exact-time batches / 145 exact-resolved" in text
text = text.replace("82 public exact-time batches / 145 exact-resolved", "83 public exact-time batches / 159 exact-resolved", 1)
text += """

### Batch 0116: ACO, KELYA, CMTL, VEEV, CACI, DGI, SWKS, NKE, P, COLM, DGI, POWI, TRAK, SCVL

Filed E.D.N.Y. GX 8002 Document 367-2 supplies explicit first-public press-release distribution clocks for fourteen Worker-1 events. Exact release identity/date is corroborated by pinned public press-release archive members and an official SEC Exhibit 99.1 for Pandora. This advances G1 from 145 exact / 29 reviewed exclusions to 159 exact / 15 reviewed exclusions. Conference-call, EDGAR acceptance, archive-capture, date-only, scheduled-release and inferred clocks are not used. Step 9 remains SOURCE_BLOCKED.
"""
docs.write_text(text, encoding="utf-8")

test_text = PREP_TEST.read_text(encoding="utf-8")
test_text = test_text.replace("g1_public_batch_0116_prep_evidence.json", "g1_public_batch_0116_evidence.json")
test_text = test_text.replace("_prep_", "_")
test_text = test_text.replace('    assert evidence["prep_only"] is True\n', "")
test_text = test_text.replace(
    '        assert resolutions[eid]["resolution_status"] == "excluded_fail_closed"\n',
    '        assert resolutions[eid]["resolution_status"] == "resolved_exact_public_timestamp"\n'
)
needle = '        assert int((release - trade).total_seconds()) == spec["delta"]\n'
insert = needle + '        assert resolutions[eid]["public_announcement_ts"] == release.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")\n'
assert needle in test_text
test_text = test_text.replace(needle, insert, 1)
ast.parse(test_text)
FINAL_TEST.write_text(test_text, encoding="utf-8")
PREP.unlink()
PREP_TEST.unlink()
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
reason = "G1 batch 0116 Worker-1 filed federal-court public-distribution clocks for fourteen events; deterministic 159 exact / 15 reviewed exclusions with pinned press-release/SEC identity corroboration and prior evidence preserved."
for filename in sorted(changed):
    section = "intentional_release_modifications" if filename in allow["intentional_release_modifications"] else "repository_additions"
    allow[section][filename] = {"expected_sha256": digest(filename), "reason": reason}
save(allow_path, allow)
changed.add(str(allow_path))
subprocess.run(["git", "add", "--", *sorted(changed)], check=True)

audit = Path("private_runtime/audit/g1-batch-0116")
audit.mkdir(parents=True, exist_ok=True)
save(audit / "verification.json", {
    "base_main_sha": BASE,
    "source_head_sha": os.environ["GITHUB_SHA"],
    "exact": NEW_EXACT,
    "reviewed_excluded": NEW_EXCLUDED,
    "previous_exact_preserved": OLD_EXACT,
    "new_event_ids": sorted(ids),
    "step9": "SOURCE_BLOCKED",
    "evaluation_release_permitted": False,
    "deterministic_rebuild_matches": True,
})
print(json.dumps({"exact": NEW_EXACT, "reviewed_excluded": NEW_EXCLUDED, "new_events": sorted(ids)}, indent=2))
