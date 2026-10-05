from __future__ import annotations
import csv, json, re
from datetime import datetime
from pathlib import Path

ROW_RE = re.compile(
    r"""^\s*(?P<row_id>\d+)\s+
    (?P<ticker>[A-Z0-9.\-]+)\s+
    (?P<year>20\d{2})\s+
    (?P<distribution_date>\d{1,2}/\d{1,2}/(?:\d{2}|\d{4}))\s+
    (?P<earliest_date>\d{1,2}/\d{1,2}/(?:\d{2}|\d{4}))\s+
    (?P<earliest_time>\d{1,2}:\d{2})\s+
    (?P<close_date>\d{1,2}/\d{1,2}/(?:\d{2}|\d{4}))\s+
    (?P<close_time>\d{1,2}:\d{2})\s+
    (?P<submission_date>\d{1,2}/\d{1,2}/(?:\d{2}|\d{4}))\s+
    (?P<submission_time>\d{1,2}:\d{2})\s+
    (?P<public_date>\d{1,2}/\d{1,2}/(?:\d{2}|\d{4}))\s+
    (?P<public_time>\d{1,2}:\d{2})\s+
    (?P<source>[A-Z]{1,5})\b
    (?P<tail>.*)$""",
    re.VERBOSE,
)

HEADER_NEEDLES = (
    "Press Release / Distribution Date",
    "Earliest Order Time",
    "Press Release Submission / Time",
    "Press Release / Distribution Time",
    "Source",
)

def norm_dt(date_s: str, time_s: str) -> datetime:
    fmt = "%m/%d/%Y %H:%M" if len(date_s.rsplit("/",1)[-1]) == 4 else "%m/%d/%y %H:%M"
    return datetime.strptime(f"{date_s} {time_s}", fmt)

def load_unresolved(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for row in data["exclusions"]:
        trade = datetime.fromisoformat(row["first_documented_illicit_trade_ts"].replace("Z","+00:00"))
        if trade.tzinfo:
            trade = trade.replace(tzinfo=None)
        out.append({
            "event_id": row["event_id"],
            "symbol": row.get("historical_symbol") or row.get("symbol"),
            "first_trade": trade,
        })
    return out

def parse_rows(text: str) -> tuple[list[dict], list[str]]:
    lines = text.splitlines()
    rows = []
    headers = []
    for idx, line in enumerate(lines):
        if any(n in line for n in HEADER_NEEDLES):
            headers.append(line.strip())
        m = ROW_RE.match(line)
        if not m:
            continue
        d = m.groupdict()
        d["line_number"] = idx + 1
        d["raw_line"] = re.sub(r"\s+", " ", line).strip()
        d["earliest_order_dt"] = norm_dt(d["earliest_date"], d["earliest_time"]).isoformat(timespec="minutes")
        d["submission_dt"] = norm_dt(d["submission_date"], d["submission_time"]).isoformat(timespec="minutes")
        d["public_distribution_dt_unzoned"] = norm_dt(d["public_date"], d["public_time"]).isoformat(timespec="minutes")
        headline = ""
        for j in range(idx + 1, min(idx + 5, len(lines))):
            candidate = re.sub(r"\s+", " ", lines[j]).strip()
            if not candidate:
                continue
            if ROW_RE.match(lines[j]) or any(n in candidate for n in HEADER_NEEDLES):
                break
            # Headlines in the exhibit are the first non-table line after the row.
            if len(candidate) > 8 and not candidate.startswith("Case 1:"):
                headline = candidate
                break
        d["headline"] = headline
        rows.append(d)
    return rows, headers

def main() -> None:
    root = Path.cwd()
    court_txt = Path("/tmp/gx8002.txt")
    unresolved = load_unresolved(root / "data/processed/authorized_input_real/g1_final_timing_exclusions.json")
    text = court_txt.read_text(encoding="utf-8", errors="replace")
    rows, headers = parse_rows(text)

    mapped = []
    unmatched = []
    ambiguous = []
    for event in unresolved:
        cands = [r for r in rows if r["ticker"] == event["symbol"] and int(r["year"]) == event["first_trade"].year]
        exact = []
        for r in cands:
            edt = datetime.fromisoformat(r["earliest_order_dt"])
            if edt.strftime("%Y-%m-%d %H:%M") == event["first_trade"].strftime("%Y-%m-%d %H:%M"):
                exact.append(r)
        if len(exact) == 1:
            r = exact[0]
            public_dt = datetime.fromisoformat(r["public_distribution_dt_unzoned"])
            mapped.append({
                "event_id": event["event_id"],
                "symbol": event["symbol"],
                "first_documented_illicit_trade_ts": event["first_trade"].isoformat(timespec="minutes"),
                "gx8002_row_id": r["row_id"],
                "press_release_distribution_date": r["distribution_date"],
                "press_release_submission_dt_unzoned": r["submission_dt"],
                "press_release_distribution_dt_unzoned": r["public_distribution_dt_unzoned"],
                "source_code": r["source"],
                "headline": r["headline"],
                "raw_row": r["raw_line"],
                "line_number": r["line_number"],
                "chronology_unzoned_seconds": int((public_dt - event["first_trade"]).total_seconds()),
                "timezone_status": "UNPROVEN_DO_NOT_PROMOTE",
            })
        elif len(exact) > 1:
            ambiguous.append({"event_id":event["event_id"],"symbol":event["symbol"],"matches":[r["raw_line"] for r in exact]})
        else:
            unmatched.append({
                "event_id": event["event_id"],
                "symbol": event["symbol"],
                "first_trade": event["first_trade"].isoformat(timespec="minutes"),
                "same_symbol_year_rows": [r["raw_line"] for r in cands],
            })

    out_dir = root / "private_runtime/audit/g1-gx8002-court-map"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version":"1",
        "research_use_only":True,
        "court_case":"United States v. Vitaly Korchevsky, 1:15-cr-00381 (E.D.N.Y.)",
        "court_document":"367-2",
        "court_source_url":"https://storage.courtlistener.com/recap/gov.uscourts.nyed.373762/gov.uscourts.nyed.373762.367.2.pdf",
        "header_lines":headers,
        "parsed_row_count":len(rows),
        "unresolved_count":len(unresolved),
        "mapped_exact_first_trade_count":len(mapped),
        "ambiguous_count":len(ambiguous),
        "unmatched_count":len(unmatched),
        "timezone_status":"UNPROVEN_DO_NOT_PROMOTE",
        "warning":"The court labels the field Press Release / Distribution Time, but timezone must be explicitly established before canonical promotion.",
        "mapped":mapped,
        "ambiguous":ambiguous,
        "unmatched":unmatched,
    }
    (out_dir/"mapping.json").write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    fields=["event_id","symbol","first_documented_illicit_trade_ts","gx8002_row_id","press_release_distribution_date","press_release_submission_dt_unzoned","press_release_distribution_dt_unzoned","source_code","headline","chronology_unzoned_seconds","timezone_status"]
    with (out_dir/"mapping.csv").open("w",newline="",encoding="utf-8") as fh:
        w=csv.DictWriter(fh,fieldnames=fields);w.writeheader()
        for row in mapped:w.writerow({k:row[k] for k in fields})
    print(json.dumps({k:payload[k] for k in ("parsed_row_count","unresolved_count","mapped_exact_first_trade_count","ambiguous_count","unmatched_count","timezone_status")},indent=2))
    print("GX8002_UNRESOLVED_MAPPED")
    for row in mapped:
        print(json.dumps({k:row[k] for k in ("event_id","symbol","gx8002_row_id","press_release_distribution_dt_unzoned","source_code","headline","chronology_unzoned_seconds")},ensure_ascii=False))

if __name__ == "__main__":
    main()
