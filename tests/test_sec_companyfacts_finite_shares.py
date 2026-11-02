"""Fail-closed adversarial SEC share-count intake, independent of broker/market access."""
from __future__ import annotations

import csv
import json
import math

from sec_companyfacts_normalizer import normalize


def test_sec_companyfacts_rejects_nonfinite_and_boolean_shares_without_dropping_valid_rows(tmp_path):
    symbol_map = tmp_path / "symbols.csv"
    symbol_map.write_text(
        "cik,effective_from,effective_to,historical_symbol\n"
        "1,2010-01-01,2030-12-31,TEST\n",
        encoding="utf-8",
    )
    malformed = ["NaN", "Infinity", "-Infinity", "1e309", True, False, 0, -10, None,
                 1.5, "2.5", "1.00000000000000001"]
    valid = [1250000, "2500000"]
    observations = [
        {
            "end": "2015-02-17",
            "filed": "2015-02-18",
            "val": value,
            "form": "10-K",
            "accn": f"TEST-{index:04d}",
        }
        for index, value in enumerate(malformed + valid)
    ]
    # Non-object rows must not make an otherwise valid SEC batch crash.
    observations.extend([None, [], "not an object"])
    # A source cannot report a future outstanding-share fact as already filed;
    # compact date strings would also break lexicographic point-in-time joins.
    observations.extend([
        {"end": "2026-11-01", "filed": "2026-10-30", "val": 500, "accn": "FUTURE"},
        {"end": "20150217", "filed": "2015-02-18", "val": 600, "accn": "COMPACT"},
    ])
    companyfacts = tmp_path / "CIK0000000001.json"
    companyfacts.write_text(
        json.dumps({
            "cik": 1,
            "facts": {
                "dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "units": {"shares": observations},
                    },
                },
            },
        }, allow_nan=False),
        encoding="utf-8",
    )
    # A corrupt nested container must not abort the ingestion of other
    # independently sourced, valid Companyfacts files.
    bad_frames = [
        [],
        {"cik": 1, "facts": None},
        {"cik": 1, "facts": {"dei": []}},
        {"cik": 1, "facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": None}}}}},
    ]
    paths = [companyfacts]
    for index, payload in enumerate(bad_frames):
        source = tmp_path / f"corrupt-frame-{index}.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(source)
    out = tmp_path / "accepted-shares.csv"
    result = normalize(paths, symbol_map, out)
    rows = list(csv.DictReader(out.open(encoding="utf-8", newline="")))
    assert result["row_count"] == 2
    # The final three malformed structural rows are appended separately above.
    assert result["skipped_bad"] == len(malformed) + 3 + 2 + len(bad_frames)
    assert result["skipped_no_symbol"] == 0
    assert {row["shares_outstanding"] for row in rows} == {"1250000", "2500000"}
    assert all(math.isfinite(float(row["shares_outstanding"])) for row in rows)
    assert all(row["available_at"].startswith("2015-02-18T23:59:59") for row in rows)
    assert all(row["historical_symbol"] == "TEST" for row in rows)
