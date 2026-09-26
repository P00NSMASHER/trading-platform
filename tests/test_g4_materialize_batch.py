from __future__ import annotations

import csv
import json
from pathlib import Path

import g4_materialize_batch as g4

ROOT = Path(__file__).resolve().parents[1]


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_materializer_rejects_anchor_filed_after_target_window(tmp_path):
    req = tmp_path / "req.csv"
    anchors = tmp_path / "anchors.csv"
    out = tmp_path / "out.csv"
    report = tmp_path / "report.json"

    _write_csv(
        req,
        ["historical_symbol", "trade_date", "window_intervals_local"],
        [["TEST", "2011-03-21", "15:20-16:00"]],
    )
    _write_csv(
        anchors,
        [
            "historical_symbol","cik","fact_date","shares_outstanding","filed_date","form",
            "accession","source_tag","source_reference","source_grade","notes",
        ],
        [[
            "TEST","0000000001","2011-03-01","10000000","2011-03-21","10-Q",
            "A","sec_cover_page","https://example.invalid/a","A","",
        ]],
    )

    result = g4.build(req, anchors, 0, 1, out, report)
    assert result["resolved_count"] == 0
    row = next(csv.DictReader(out.open(newline="", encoding="utf-8")))
    assert row["status"] == "UNRESOLVED"


def test_materializer_uses_freshest_valid_pre_window_anchor(tmp_path):
    req = tmp_path / "req.csv"
    anchors = tmp_path / "anchors.csv"
    out = tmp_path / "out.csv"
    report = tmp_path / "report.json"

    _write_csv(
        req,
        ["historical_symbol", "trade_date", "window_intervals_local"],
        [["TEST", "2011-06-20", "14:00-15:00"]],
    )
    _write_csv(
        anchors,
        [
            "historical_symbol","cik","fact_date","shares_outstanding","filed_date","form",
            "accession","source_tag","source_reference","source_grade","notes",
        ],
        [
            ["TEST","0000000001","2011-03-01","9000000","2011-03-10","10-K","OLD","sec_cover_page","https://example.invalid/old","A",""],
            ["TEST","0000000001","2011-05-06","10000000","2011-05-16","10-Q","NEW","sec_cover_page","https://example.invalid/new","A",""],
        ],
    )

    result = g4.build(req, anchors, 0, 1, out, report)
    assert result["resolved_count"] == 1
    row = next(csv.DictReader(out.open(newline="", encoding="utf-8")))
    assert row["shares_outstanding"] == "10000000"
    assert row["accession"] == "NEW"
    assert row["source_reference"] == "https://example.invalid/new"


def test_batch_0001_generated_evidence_is_exactly_500_when_present():
    evidence = ROOT / "data/public/metadata/g4_shares_batch_0001.csv"
    report = ROOT / "data/processed/authorized_input_real/g4_shares_batch_0001_report.json"
    if not evidence.exists() or not report.exists():
        return

    rows = list(csv.DictReader(evidence.open(newline="", encoding="utf-8")))
    receipt = json.loads(report.read_text(encoding="utf-8"))

    assert len(rows) == 500
    assert [int(r["observation_index"]) for r in rows] == list(range(1, 501))
    assert all(r["status"] == "RESOLVED" for r in rows)
    assert all(r["shares_outstanding"] for r in rows)
    assert all(r["source_reference"] for r in rows)
    assert receipt["resolved_count"] == 500
    assert receipt["unresolved_count"] == 0
    assert receipt["remaining_after_batch"] == 3328
