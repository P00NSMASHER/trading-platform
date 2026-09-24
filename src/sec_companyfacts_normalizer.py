from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["historical_symbol", "cik", "fact_date", "available_at", "shares_outstanding", "form", "accession", "source_reference"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


def _norm_cik(value: str | int) -> str:
    return str(value).lstrip("0") or "0"


def _symbol_for(cik: str, fact_date: str, mappings: list[dict[str, str]]) -> str:
    matches = []
    for r in mappings:
        if _norm_cik(r.get("cik", "")) != cik:
            continue
        start = r.get("effective_from", "") or "0001-01-01"
        end = r.get("effective_to", "") or "9999-12-31"
        if start <= fact_date <= end:
            matches.append((start, r.get("historical_symbol", "")))
    matches = [x for x in matches if x[1]]
    return sorted(matches, reverse=True)[0][1] if matches else ""


def normalize(companyfacts_paths: list[Path], symbol_map: Path, out: Path) -> dict:
    mappings = _read_csv(symbol_map)
    rows = []
    skipped_no_symbol = 0
    skipped_bad = 0
    for p in companyfacts_paths:
        obj = json.loads(p.read_text(encoding="utf-8"))
        cik = _norm_cik(obj.get("cik", ""))
        facts = obj.get("facts", {})
        concept = (facts.get("dei", {}) or {}).get("EntityCommonStockSharesOutstanding", {})
        units = concept.get("units", {}) if isinstance(concept, dict) else {}
        observations = units.get("shares", []) if isinstance(units, dict) else []
        for o in observations:
            fact_date = str(o.get("end", ""))
            filed = str(o.get("filed", ""))
            val = o.get("val")
            try:
                if not fact_date or not filed or float(val) <= 0:
                    skipped_bad += 1; continue
                date.fromisoformat(fact_date); date.fromisoformat(filed)
            except Exception:
                skipped_bad += 1; continue
            symbol = _symbol_for(cik, fact_date, mappings)
            if not symbol:
                skipped_no_symbol += 1; continue
            # Companyfacts commonly exposes only a filing DATE, not an acceptance second.
            # End-of-day ET is conservative: it prevents the fact from being used earlier on its filing date.
            avail = datetime.fromisoformat(filed + "T23:59:59").replace(tzinfo=NY).isoformat()
            accn = str(o.get("accn", ""))
            rows.append({
                "historical_symbol": symbol,
                "cik": cik,
                "fact_date": fact_date,
                "available_at": avail,
                "shares_outstanding": str(val),
                "form": str(o.get("form", "")),
                "accession": accn,
                "source_reference": f"SEC Companyfacts {accn}" if accn else f"SEC Companyfacts CIK {cik}",
            })
    # Deduplicate exact observations but preserve amendments/new filings as separate availability records.
    uniq = {}
    for r in rows:
        key = (r["historical_symbol"], r["fact_date"], r["available_at"], r["shares_outstanding"], r["accession"])
        uniq[key] = r
    rows = sorted(uniq.values(), key=lambda r: (r["historical_symbol"], r["fact_date"], r["available_at"]))
    _write_csv(out, rows)
    return {"row_count": len(rows), "skipped_no_symbol": skipped_no_symbol, "skipped_bad": skipped_bad, "output": str(out)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Normalize already-downloaded public SEC Companyfacts JSON into point-in-time shares records")
    ap.add_argument("--companyfacts", type=Path, action="append", required=True)
    ap.add_argument("--symbol-map", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(normalize(args.companyfacts, args.symbol_map, args.out), indent=2))


if __name__ == "__main__":
    main()
