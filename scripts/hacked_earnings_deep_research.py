#!/usr/bin/env python3
"""Pinned-source, retrospective text research. Never changes canonical G1-G5 gates."""
from __future__ import annotations
import argparse
import collections
import csv
import datetime as dt
import functools
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import statistics
import sys
import time
import unittest
from urllib.parse import quote
from urllib.request import Request, urlopen
import zipfile

SOURCE_SHA = "c23c7d79d067a79d70cf20e31b072d3703497eae"
BASE = f"https://raw.githubusercontent.com/vgreg/hacked_earnings_jfe/{SOURCE_SHA}/"
COEFFICIENT_PATH = "Text Analysis/PR_fit_EN_0_5_text_clean_stemmed_400_Count_0_005_0_4_WORDS.parquet"
BLOBS = {
    "Data/SampleFirms.csv": "bbb68de172f7ab2104714513a72547f3dad3b86c",
    "Data/TimeOfFirstTrade.csv": "8e823995d45b0bb536809a8499d559cddd929c8b",
    COEFFICIENT_PATH: "72d66171f5eb28cd3ec629f13b0b1d15219cbf96",
    "Data/Press releases/2010.zip": "b4b45ba8bb5e5bf4c502373914fdcaaae268d3aa",
    "Data/Press releases/2011.zip": "8f4b9b391e8e87649d2a5f5615a30371741c5e6a",
    "Data/Press releases/2012.zip": "afa44be02ab5aaea6e6105cbca247286bc892fd7",
    "Data/Press releases/2013.zip": "59e183f05e377ebd0ef2f581ba88522863663972",
    "Data/Press releases/2014.zip": "0e0e349b76318bb9558a790000c9cbe5ee933001",
    "Data/Press releases/2015.zip": "919ba9f271abdc06ba7c539ad278d5bb4fcb3715",
}
MEMBER_PATTERN = re.compile(r"^(\d+)_(\d{8})_(\d+)(?: [^/]*)?\.txt$", re.I)
TOKEN_PATTERN = re.compile(r"[a-z]+")
MAX_SOURCE_BYTES = 40_000_000
MAX_MEMBER_BYTES = 20_000_000
MAX_ARCHIVE_EXPANDED_BYTES = 1_000_000_000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_hash(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify_blob(data: bytes, expected: str) -> None:
    if git_blob_hash(data) != expected:
        raise ValueError("Source git-blob hash mismatch")


def download_sources(cache: Path) -> list[dict]:
    manifest = []
    for relative, expected in BLOBS.items():
        path = cache / relative
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            for attempt in range(3):
                try:
                    request = Request(BASE + quote(relative), headers={"User-Agent": "hacked-earnings-research/1.0"})
                    with urlopen(request, timeout=60) as response:
                        payload = response.read(MAX_SOURCE_BYTES + 1)
                    if len(payload) > MAX_SOURCE_BYTES:
                        raise ValueError("Source exceeds bounded download size")
                    verify_blob(payload, expected)
                    path.write_bytes(payload)
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)
        payload = path.read_bytes()
        verify_blob(payload, expected)
        manifest.append({"path": relative, "source_commit": SOURCE_SHA, "git_blob_sha1": expected,
                         "sha256": sha256(payload), "bytes": len(payload), "url": BASE + quote(relative)})
        print(f"Verified {relative}: {len(payload):,} bytes", flush=True)
    return manifest


def member_key(name: str) -> tuple[str, str, int] | None:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or "\\" in name:
        raise ValueError("Unsafe ZIP member path")
    if "__MACOSX" in p.parts or p.name.startswith("._"):
        return None
    match = MEMBER_PATTERN.fullmatch(p.name)
    if match is None:
        return None
    permno, date, appendix = match.groups()
    return str(int(permno)), dt.datetime.strptime(date, "%Y%m%d").date().isoformat(), int(appendix)


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def clean400(text: str, stopwords: set[str], stem) -> list[str]:
    answer = []
    for match in TOKEN_PATTERN.finditer(text.lower()):
        word = match.group()
        if word in stopwords:
            continue
        answer.append(stem(word))
        if len(answer) == 400:
            break
    return answer


def contribution(tokens: list[str], weights: dict[str, float]) -> float:
    # CountVectorizer's default token pattern excludes single-character tokens.
    return sum(weights.get(token, 0.0) for token in tokens if len(token) >= 2)


def numeric(value) -> float | None:
    if value in (None, "", "nan", "NaN"):
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Nonfinite numeric value")
    return result


def reconcile_event(event: dict, rows: list[dict]) -> dict | None:
    trade_day = dt.date.fromisoformat(event["TimeOfFirstTrade"][:10])
    candidates = [r for r in rows if r["PERMNO"] == event["PERMNO"]
                  and 0 <= (dt.date.fromisoformat(r["date"]) - trade_day).days <= 3]
    return min(candidates, key=lambda r: r["date"]) if candidates else None


def candidate_controls(target: dict, rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["date"] == target["date"] and r["PERMNO"] != target["PERMNO"]
            and r["Hacked"] == "0" and r["Actual"] == "0"]


def summarize(rows: list[dict]) -> dict:
    soft = [float(r["Soft"]) for r in rows if numeric(r.get("Soft")) is not None]
    return {"rows": len(rows), "unique_permnos": len({r["PERMNO"] for r in rows}),
            "soft_count": len(soft), "soft_missing": len(rows) - len(soft),
            "soft_mean": statistics.mean(soft) if soft else None,
            "soft_median": statistics.median(soft) if soft else None,
            "mean_absolute_soft": statistics.mean(map(abs, soft)) if soft else None,
            "text_linked_rows": sum(int(r.get("text_document_count", 0)) > 0 for r in rows),
            "text_ambiguous_rows": sum(int(r.get("text_distinct_content_count", 0)) > 1 for r in rows)}


def run(cache: Path, output: Path, download: bool) -> dict:
    import nltk
    import pyarrow
    import pyarrow.parquet as pq
    from nltk.corpus import stopwords as nltk_stopwords
    output.mkdir(parents=True, exist_ok=True)
    manifest = download_sources(cache) if download else []
    if not download:
        for relative, expected in BLOBS.items():
            payload = (cache / relative).read_bytes()
            verify_blob(payload, expected)
            manifest.append({"path": relative, "source_commit": SOURCE_SHA, "git_blob_sha1": expected,
                             "sha256": sha256(payload), "bytes": len(payload), "url": BASE + quote(relative)})
    stop = set(nltk_stopwords.words("english"))
    stem = functools.lru_cache(maxsize=250_000)(nltk.PorterStemmer().stem)
    coefficient_rows = pq.read_table(cache / COEFFICIENT_PATH).select(["word", "coef"]).to_pylist()
    weights = {r["word"]: float(r["coef"]) for r in coefficient_rows}
    if len(coefficient_rows) != 2393 or len(weights) != 2393:
        raise ValueError("Coefficient schema/count drift")
    if not all(math.isfinite(v) for v in weights.values()):
        raise ValueError("Nonfinite coefficient")
    sample = read_csv(cache / "Data/SampleFirms.csv")
    events = read_csv(cache / "Data/TimeOfFirstTrade.csv")
    if len(sample) != 43687 or len(events) != 174:
        raise ValueError("Pinned source row-count drift")
    keys = [(r["PERMNO"], r["date"]) for r in sample]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate SampleFirms PERMNO/date; no many-to-many join permitted")
    for row in sample:
        dt.date.fromisoformat(row["date"])
        if row["Hacked"] not in {"0", "1"} or row["Actual"] not in {"0", "1"}:
            raise ValueError("Unexpected label values")
        numeric(row["Soft"])
    documents: list[dict] = []
    selected: dict[tuple[str, str], dict] = {}
    members_by_key: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    archive_stats = []
    unparsed = []
    for year in range(2010, 2016):
        before = len(documents)
        expanded_bytes = 0
        with zipfile.ZipFile(cache / f"Data/Press releases/{year}.zip") as archive:
            for info in sorted(archive.infolist(), key=lambda i: i.filename):
                if info.is_dir():
                    continue
                key = member_key(info.filename)
                if key is None:
                    unparsed.append({"year": year, "member": info.filename, "bytes": info.file_size})
                    continue
                if info.file_size > MAX_MEMBER_BYTES:
                    raise ValueError("Oversized archive member")
                expanded_bytes += info.file_size
                if expanded_bytes > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise ValueError("Expanded archive size limit exceeded")
                payload = archive.read(info)
                try:
                    text = payload.decode("utf-8-sig")
                    encoding = "utf-8-sig"
                except UnicodeDecodeError:
                    text = payload.decode("cp1252", errors="replace")
                    encoding = "cp1252_with_replacement"
                tokens = clean400(text, stop, stem)
                row = {"PERMNO": key[0], "date": key[1], "appendix_id": key[2], "archive_year": year,
                       "member": info.filename, "sha256": sha256(payload), "bytes": len(payload),
                       "text_characters": len(text), "decoding": encoding,
                       "replacement_characters": text.count("\ufffd"), "clean400_token_count": len(tokens),
                       "vocabulary_occurrences": sum(t in weights and len(t) >= 2 for t in tokens),
                       "fitted_word_contribution_no_intercept": contribution(tokens, weights),
                       "preannouncement_eligible": False, "independent_prediction": False}
                documents.append(row)
                pair = key[:2]
                members_by_key[pair].append(row)
                rank = (key[2], info.filename)
                if pair not in selected or rank < selected[pair]["rank"]:
                    selected[pair] = {"rank": rank, "doc": row, "tokens": set(tokens)}
        archive_stats.append({"year": year, "text_members": len(documents) - before, "expanded_bytes": expanded_bytes})
        print(f"Processed {year}: {len(documents) - before:,} text members", flush=True)
    previous = {}
    for pair in sorted(selected, key=lambda key: (key[0], key[1])):
        entry = selected[pair]
        predecessor = previous.get(pair[0])
        entry["prior_text_date"] = predecessor[0] if predecessor else ""
        if predecessor:
            union = entry["tokens"] | predecessor[1]
            entry["prior_text_jaccard_distance"] = 1 - len(entry["tokens"] & predecessor[1]) / len(union) if union else 0.0
        else:
            entry["prior_text_jaccard_distance"] = ""
        previous[pair[0]] = (pair[1], entry["tokens"])
    enriched = []
    for row in sample:
        pair = (row["PERMNO"], row["date"])
        docs = members_by_key.get(pair, [])
        feature = dict(row)
        feature.update({"text_document_count": len(docs), "text_distinct_content_count": len({d["sha256"] for d in docs}),
                        "availability_status": "PUBLICATION_TIME_UNVERIFIED", "preannouncement_eligible": False,
                        "live_model_eligible": False, "canonical_g2_credit": 0})
        if docs:
            chosen = selected[pair]
            for field in ("member", "sha256", "appendix_id", "clean400_token_count", "text_characters",
                          "fitted_word_contribution_no_intercept", "replacement_characters"):
                feature[f"selected_{field}"] = chosen["doc"][field]
            feature["prior_text_date"] = chosen["prior_text_date"]
            feature["prior_text_jaccard_distance"] = chosen["prior_text_jaccard_distance"]
            feature["appendix_selection"] = "lowest_numeric_id_then_lexicographic_path_exploratory_only"
        enriched.append(feature)
    by_security = collections.defaultdict(list)
    by_date = collections.defaultdict(list)
    for row in enriched:
        by_security[row["PERMNO"]].append(row)
        by_date[row["date"]].append(row)
    event_rows, control_rows = [], []
    event_keys = set()
    for number, event in enumerate(events, 1):
        target = reconcile_event(event, by_security[event["PERMNO"]])
        result = {"source_trade_row": number, **event, "link_status": "UNRESOLVED"}
        if target:
            pair = (target["PERMNO"], target["date"])
            event_keys.add(pair)
            result.update({k: v for k, v in target.items() if k not in {"PERMNO", "SYMBOL", "GVKEY"}})
            result["link_status"] = "SOURCE_DATE_HEURISTIC_0_TO_3_DAYS_NOT_CANONICAL_G1"
            result["source_label_exception"] = not (target["Hacked"] == target["Actual"] == "1")
            candidates = candidate_controls(target, by_date[target["date"]])
            result["same_day_unexposed_candidate_count"] = len(candidates)
            for candidate in candidates:
                control_rows.append({"source_trade_row": number, "treated_PERMNO": target["PERMNO"],
                                     "candidate_PERMNO": candidate["PERMNO"], "candidate_SYMBOL": candidate["SYMBOL"],
                                     "date": target["date"], "status": "CANDIDATE_ONLY_NOT_G5_MATCHED",
                                     "used_soft_for_selection": False, "used_text_for_selection": False,
                                     "balance_verified": False, "canonical_g5_credit": 0})
        event_rows.append(result)
    cohorts = []
    for year in ["ALL"] + [str(y) for y in range(2010, 2016)]:
        for hacked, actual in [("0", "0"), ("1", "0"), ("1", "1")]:
            rows = [r for r in enriched if r["Hacked"] == hacked and r["Actual"] == actual
                    and (year == "ALL" or r["date"].startswith(year))]
            cohorts.append({"year": year, "Hacked": hacked, "Actual": actual, **summarize(rows)})
    auxiliary = [r for r in enriched if r["Actual"] == "1" and (r["PERMNO"], r["date"]) not in event_keys]
    missing_soft_text = [r for r in enriched if numeric(r["Soft"]) is None and r["text_document_count"] > 0]
    joined_events = [r for r in event_rows if r["link_status"] != "UNRESOLVED"]
    summary = {"status": "RETROSPECTIVE_RESEARCH_ONLY", "source_commit": SOURCE_SHA,
               "source_files_verified": len(manifest), "sample": summarize(enriched),
               "archives": archive_stats, "archive_text_members": len(documents),
               "archive_unique_security_dates": len(members_by_key),
               "archive_unique_content_hashes": len({d["sha256"] for d in documents}),
               "unparsed_members": len(unparsed), "coefficient_rows": len(weights),
               "nonzero_coefficients": sum(v != 0 for v in weights.values()),
               "positive_coefficients": sum(v > 0 for v in weights.values()),
               "negative_coefficients": sum(v < 0 for v in weights.values()),
               "events": summarize(joined_events), "events_unresolved": len(events) - len(joined_events),
               "event_source_label_exceptions": sum(r.get("source_label_exception", False) for r in event_rows),
               "missing_soft_sample_rows_with_text": len(missing_soft_text),
               "missing_soft_event_rows_with_text": sum(numeric(r.get("Soft")) is None and r.get("text_document_count", 0) > 0 for r in joined_events),
               "additional_actual_label_rows_outside_174_join": summarize(auxiliary),
               "same_day_unexposed_candidate_pairs": len(control_rows),
               "events_with_same_day_unexposed_candidates": sum(r.get("same_day_unexposed_candidate_count", 0) > 0 for r in event_rows),
               "source_label_invariant_violations": sum(r["Actual"] == "1" and r["Hacked"] != "1" for r in sample),
               "versions": {"python": sys.version.split()[0], "nltk": nltk.__version__, "pyarrow": pyarrow.__version__},
               "stopword_count": len(stop), "stopwords_sha256": sha256("\n".join(sorted(stop)).encode()),
               "canonical_coverage_change": {"G1": 0, "G2": 0, "G3": 0, "G4": 0, "G5": 0},
               "limitations": [
                   "Soft is fitted on the training sample in the published recipe; not independently validated prediction.",
                   "Text and original Soft cannot be used before verified public release; availability clocks are not in archive filenames.",
                   "Fitted-word contribution lacks the unpublished intercept and is NOT a recovered or imputed Soft score.",
                   "Original unsorted directory order and first-appendix choice cannot be reproduced; explicit exploratory choice preserves multiplicity.",
                   "Hacked/Actual are retrospective source labels, not live features; exact-time 174 and broader Actual universe remain distinct.",
                   "First-trade-to-earnings joins are source-date heuristics, not new canonical announcement-time or identity evidence.",
                   "Same-day controls are unbalanced research candidates only; no market cap, liquidity, outcome, or execution evidence is manufactured.",
                   "No raw TAQ/OPRA/ITCH or omitted proprietary MainPanel/return targets recovered; no profit/backtest claims.",
                   "Prior-text changes are descriptive and still need independently verified publication clocks and point-in-time training.",
               ]}
    write_csv(output / "archive_document_manifest.csv", documents)
    write_csv(output / "archive_unparsed_members.csv", unparsed)
    write_csv(output / "word_coefficients.csv", coefficient_rows)
    write_csv(output / "sample_text_features.csv", enriched)
    write_csv(output / "event_174_text_features.csv", event_rows)
    write_csv(output / "cohort_summary.csv", cohorts)
    write_csv(output / "additional_actual_label_rows.csv", auxiliary)
    write_csv(output / "missing_soft_with_text.csv", missing_soft_text)
    write_csv(output / "same_day_control_candidates.csv", control_rows)
    (output / "source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    report = ["# Hacked earnings: deeper public-source extraction", "", "## Result", "",
              f"Verified {len(manifest)} source assets at `{SOURCE_SHA}` and processed all six annual archives.",
              f"Enumerated {len(documents):,} press-release text members; linked text to {summary['sample']['text_linked_rows']:,} of 43,687 sample rows and {summary['events']['text_linked_rows']} of 174 first-trade records.",
              f"Recovered {len(weights):,} fitted coefficients ({summary['nonzero_coefficients']:,} nonzero).",
              f"Found text for {len(missing_soft_text):,} sample rows with missing published Soft, including {summary['missing_soft_event_rows_with_text']} first-trade records. Published Soft is left missing.",
              f"Isolated {len(auxiliary)} additional Actual=1 sample rows outside the 174-event heuristic join.",
              f"Generated {len(control_rows):,} same-day nonexposed candidate pairs across {summary['events_with_same_day_unexposed_candidates']} events. These are not accepted G5 matches.",
              "", "## Interpretation", "",
              "This package expands the usable text research corpus, makes model weights inspectable, preserves appendix ambiguity, and prepares candidate comparison groups. It does not establish prediction or trading profitability.",
              "", "## Required safeguards", ""]
    report += [f"- {item}" for item in summary["limitations"]]
    report += ["", "## Next empirical work", "",
               "1. Resolve multiple-appendix identity and obtain verifiable public-release clocks before feature admission.",
               "2. Join authorized realized returns and fit only on earlier dates, with issuer-aware validation and event-window embargoes.",
               "3. Compare text novelty and independently fitted tone across retrospective cohorts; report missingness and issuer/date concentration.",
               "4. Add point-in-time size/liquidity/sector balance to the candidate control table before accepting G5 matches.",
               "", "No production model, scheduler, protected release configuration, or canonical data gate is modified.", ""]
    (output / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    hashes = {p.name: sha256(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file() and p.name != "output_hashes.json"}
    (output / "output_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, allow_nan=False), flush=True)
    return summary


class SafetyTests(unittest.TestCase):
    def test_blob_integrity(self):
        verify_blob(b"test", git_blob_hash(b"test"))
        with self.assertRaises(ValueError):
            verify_blob(b"changed", git_blob_hash(b"test"))
    def test_zip_path(self):
        for name in ("../1_20150101_1.txt", "/1_20150101_1.txt", "dir\\1_20150101_1.txt"):
            with self.assertRaises(ValueError):
                member_key(name)
        self.assertEqual(member_key("2015/QTR1/001_20150101_2.txt"), ("1", "2015-01-01", 2))
    def test_sidecars_excluded(self):
        self.assertIsNone(member_key("__MACOSX/2015/._1_20150101_1.txt"))
        self.assertIsNone(member_key("README.txt"))
    def test_stopword_before_limit(self):
        tokens = clean400(("the word " * 500), {"the"}, lambda s: s)
        self.assertEqual(tokens, ["word"] * 400)
    def test_count_not_presence(self):
        self.assertEqual(contribution(["rais", "rais", "x"], {"rais": .5, "x": 10}), 1.0)
    def test_source_reconciliation_bounds(self):
        event = {"PERMNO": "1", "TimeOfFirstTrade": "2015-01-01 15:00:00"}
        rows = [{"PERMNO": "1", "date": "2014-12-31"}, {"PERMNO": "1", "date": "2015-01-05"}, {"PERMNO": "2", "date": "2015-01-01"}]
        self.assertIsNone(reconcile_event(event, rows))
        rows.append({"PERMNO": "1", "date": "2015-01-04"})
        self.assertEqual(reconcile_event(event, rows)["date"], "2015-01-04")
    def test_control_exclusion(self):
        target = {"PERMNO": "1", "date": "2015-01-01"}
        rows = [{"PERMNO": p, "date": d, "Hacked": h, "Actual": a}
                for p, d, h, a in [("1", "2015-01-01", "0", "0"), ("2", "2015-01-01", "1", "0"), ("3", "2015-01-02", "0", "0"), ("4", "2015-01-01", "0", "0")]]
        self.assertEqual([r["PERMNO"] for r in candidate_controls(target, rows)], ["4"])
    def test_missing_not_zero(self):
        self.assertIsNone(numeric(""))
        self.assertEqual(numeric("0"), 0.0)
        with self.assertRaises(ValueError):
            numeric("inf")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("private_runtime/hacked_earnings_source"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/hacked_earnings_deep"))
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SafetyTests))
        sys.exit(0 if result.wasSuccessful() else 1)
    run(args.cache, args.output, args.download)
