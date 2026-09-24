from pathlib import Path
import csv
from sec_companyfacts_normalizer import normalize

ROOT=Path(__file__).resolve().parents[1]

def test_companyfacts_normalizer_conservative_availability(tmp_path):
    out=tmp_path/"shares.csv"
    s=normalize([ROOT/"data/examples/metadata/sec_companyfacts/CIK0000000001.json"], ROOT/"data/examples/metadata/sec_symbol_map.csv", out)
    assert s["row_count"] == 2
    rows=list(csv.DictReader(out.open()))
    assert rows[0]["historical_symbol"] == "TEST"
    assert rows[0]["available_at"].startswith("2015-02-16T23:59:59")
    # A fact dated 2015-02-17 but filed on 2015-02-18 remains unavailable on the fact date.
    assert rows[1]["fact_date"] == "2015-02-17"
    assert rows[1]["available_at"].startswith("2015-02-18T23:59:59")
