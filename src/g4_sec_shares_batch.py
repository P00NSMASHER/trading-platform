from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
SEC_UA = "P00NSMASHER trading-platform research 22281248+P00NSMASHER@users.noreply.github.com"
CURRENT_TICKERS = "https://www.sec.gov/files/company_tickers.json"
BROWSE = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={symbol}&owner=exclude&count=1&output=atom"
COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik10}.json"
SUBMISSION_FILE = "https://data.sec.gov/submissions/{name}"
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A"}
MAX_STALENESS_DAYS = 130

FIELDS = [
    "observation_index",
    "historical_symbol",
    "target_trade_date",
    "target_cutoff_local",
    "cik",
    "fact_date",
    "available_at",
    "shares_outstanding",
    "source_tag",
    "form",
    "accession",
    "filed_date",
    "staleness_days",
    "source_grade",
    "source_reference",
    "status",
    "unresolved_reason",
    "research_use_only",
]


class G4Error(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def _request(url: str, *, as_json: bool = False):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": SEC_UA,
            "Accept-Encoding": "gzip, deflate",
            "Host": urllib.parse.urlparse(url).netloc,
        },
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        data = response.read()
    time.sleep(0.12)
    if as_json:
        return json.loads(data.decode("utf-8"))
    return data.decode("utf-8", errors="replace")


def _load_overrides(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out = {}
    for row in _read_csv(path):
        sym = row.get("historical_symbol", "").upper()
        cik = re.sub(r"\D", "", row.get("cik", ""))
        if sym and cik:
            out[sym] = cik.zfill(10)
    return out


def _current_ticker_map() -> dict[str, str]:
    raw = _request(CURRENT_TICKERS, as_json=True)
    out = {}
    for row in raw.values():
        ticker = str(row.get("ticker", "")).strip().upper()
        cik = str(row.get("cik_str", "")).strip()
        if ticker and cik:
            out[ticker] = cik.zfill(10)
    return out


def _browse_cik(symbol: str) -> str:
    try:
        text = _request(BROWSE.format(symbol=urllib.parse.quote(symbol)))
    except Exception:
        return ""
    try:
        root = ET.fromstring(text)
        for element in root.iter():
            if element.tag.lower().endswith("cik") and (element.text or "").strip().isdigit():
                return element.text.strip().zfill(10)
    except ET.ParseError:
        pass
    m = re.search(r"<cik>\s*(\d+)\s*</cik>", text, re.I)
    return m.group(1).zfill(10) if m else ""


def resolve_ciks(symbols: list[str], overrides: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    current = _current_ticker_map()
    resolved = {}
    methods = {}
    for sym in symbols:
        if sym in overrides:
            resolved[sym] = overrides[sym]
            methods[sym] = "override"
        elif sym in current:
            resolved[sym] = current[sym]
            methods[sym] = "sec_current_ticker_map"
        else:
            cik = _browse_cik(sym)
            if cik:
                resolved[sym] = cik
                methods[sym] = "sec_browse_edgar"
            else:
                methods[sym] = "unresolved"
    return resolved, methods


def _submission_rows(obj: dict) -> list[dict]:
    recent = (obj.get("filings") or {}).get("recent") or {}
    keys = list(recent)
    n = max((len(recent.get(k) or []) for k in keys), default=0)
    rows = []
    for i in range(n):
        row = {}
        for k in keys:
            arr = recent.get(k) or []
            row[k] = arr[i] if i < len(arr) else ""
        rows.append(row)
    return rows


def _acceptance_map(cik10: str) -> dict[str, str]:
    root = _request(SUBMISSIONS.format(cik10=cik10), as_json=True)
    rows = _submission_rows(root)
    for extra in (root.get("filings") or {}).get("files") or []:
        name = str(extra.get("name", "")).strip()
        if not name:
            continue
        obj = _request(SUBMISSION_FILE.format(name=urllib.parse.quote(name)), as_json=True)
        # Older submission shards are compact filing arrays, not wrapped in filings.recent.
        if "filings" in obj:
            rows.extend(_submission_rows(obj))
        else:
            keys = list(obj)
            n = max((len(obj.get(k) or []) for k in keys if isinstance(obj.get(k), list)), default=0)
            for i in range(n):
                row = {}
                for k in keys:
                    arr = obj.get(k)
                    row[k] = arr[i] if isinstance(arr, list) and i < len(arr) else ""
                rows.append(row)
    out = {}
    for row in rows:
        accn = str(row.get("accessionNumber", "")).strip()
        accepted = str(row.get("acceptanceDateTime", "")).strip()
        if accn and accepted:
            # SEC currently emits YYYY-MM-DDTHH:MM:SS.fffZ. Preserve it verbatim.
            out[accn] = accepted
    return out


def _load_fact_bundle(path: Path) -> tuple[dict[str, list[dict]], dict[str, str]]:
    by_symbol: dict[str, list[dict]] = {}
    entities: dict[str, str] = {}
    for row in _read_csv(path):
        sym = row.get("historical_symbol", "").upper()
        if not sym:
            continue
        try:
            cand = {
                "tag": row["source_tag"],
                "tag_rank": int(row.get("tag_rank", "1") or 1),
                "val": int(float(row["shares_outstanding"])),
                "end": date.fromisoformat(row["fact_date"]),
                "filed": date.fromisoformat(row["filed_date"]),
                "form": row["form"],
                "accn": row["accession"],
                "frame": "",
            }
        except Exception as exc:
            raise G4Error(f"invalid fact bundle row for {sym}: {exc}") from exc
        by_symbol.setdefault(sym, []).append(cand)
        entities[sym] = row.get("entity_name", "")
    return by_symbol, entities


def _fact_candidates(companyfacts: dict) -> list[dict]:
    facts = companyfacts.get("facts") or {}
    candidates = []
    tag_specs = [
        ("dei", "EntityCommonStockSharesOutstanding", 0),
        ("us-gaap", "CommonStockSharesOutstanding", 1),
    ]
    for taxonomy, tag, rank in tag_specs:
        concept = ((facts.get(taxonomy) or {}).get(tag) or {})
        units = concept.get("units") or {}
        for unit_name, rows in units.items():
            if str(unit_name).lower() not in {"shares", "share"}:
                continue
            for row in rows or []:
                form = str(row.get("form", "")).strip()
                if form not in FORMS:
                    continue
                try:
                    val = int(round(float(row.get("val"))))
                    end = date.fromisoformat(str(row.get("end", ""))[:10])
                    filed = date.fromisoformat(str(row.get("filed", ""))[:10])
                except Exception:
                    continue
                if val <= 0 or val >= 10_000_000_000_000:
                    continue
                candidates.append({
                    "tag": f"{taxonomy}:{tag}",
                    "tag_rank": rank,
                    "val": val,
                    "end": end,
                    "filed": filed,
                    "form": form,
                    "accn": str(row.get("accn", "")).strip(),
                    "frame": str(row.get("frame", "")).strip(),
                })
    return candidates


def _target_cutoff(req: dict[str, str]) -> datetime:
    trade_date = req["trade_date"]
    windows = req.get("window_intervals_local", "")
    starts = []
    for interval in windows.split(";"):
        interval = interval.strip()
        if not interval or "-" not in interval:
            continue
        start = interval.split("-", 1)[0].strip()
        if re.fullmatch(r"\d{1,2}:\d{2}", start):
            starts.append(start)
    hhmm = min(starts) if starts else "23:59"
    return datetime.fromisoformat(f"{trade_date}T{hhmm}:00").replace(tzinfo=NY)


def _parse_acceptance(value: str, fallback_filed: date) -> datetime:
    if value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo:
                return dt.astimezone(NY)
        except ValueError:
            pass
    # Fail conservatively if exact acceptance time is unavailable: consider the filing
    # available only at the very end of its filing date.
    return datetime.fromisoformat(f"{fallback_filed.isoformat()}T23:59:59").replace(tzinfo=NY)


def _select_fact(req: dict[str, str], candidates: list[dict], acceptance: dict[str, str]) -> tuple[dict | None, str]:
    cutoff = _target_cutoff(req)
    td = date.fromisoformat(req["trade_date"])
    valid = []
    for cand in candidates:
        if cand["end"] > td or cand["filed"] > td:
            continue
        available = _parse_acceptance(acceptance.get(cand["accn"], ""), cand["filed"])
        if available > cutoff:
            continue
        stale = (td - cand["end"]).days
        if stale < 0 or stale > MAX_STALENESS_DAYS:
            continue
        valid.append((cand["tag_rank"], stale, -cand["filed"].toordinal(), -cand["end"].toordinal(), cand, available))
    if not valid:
        return None, "no_public_pre_cutoff_share_fact_within_staleness_limit"
    _, stale, _, _, cand, available = sorted(valid, key=lambda x: x[:4])[0]
    chosen = dict(cand)
    chosen["staleness_days"] = stale
    chosen["available"] = available
    return chosen, ""


def build(*, requirements: Path, overrides: Path, start: int, count: int, output: Path, report: Path, fact_bundle: Path | None = None) -> dict:
    all_reqs = _read_csv(requirements)
    if start < 0 or count <= 0 or start + count > len(all_reqs):
        raise G4Error(f"invalid batch bounds start={start} count={count} total={len(all_reqs)}")
    batch = all_reqs[start:start + count]
    symbols = sorted({r["historical_symbol"].upper() for r in batch})

    overrides_map = _load_overrides(overrides)
    cik_map = {sym: overrides_map[sym] for sym in symbols if sym in overrides_map}
    cik_methods = {sym: ("override" if sym in cik_map else "unresolved") for sym in symbols}
    per_cik = {}
    sec_failures = {}
    if fact_bundle is not None:
        bundle, entities = _load_fact_bundle(fact_bundle)
        for sym, cik10 in cik_map.items():
            per_cik.setdefault(cik10, {
                "candidates": bundle.get(sym, []),
                "acceptance": {},
                "entity_name": entities.get(sym, ""),
            })
    else:
        live_cik_map, live_methods = resolve_ciks(symbols, overrides_map)
        cik_map = live_cik_map
        cik_methods = live_methods
        for sym, cik10 in sorted(cik_map.items()):
            if cik10 in per_cik:
                continue
            try:
                facts = _request(COMPANYFACTS.format(cik10=cik10), as_json=True)
                accept = _acceptance_map(cik10)
                per_cik[cik10] = {
                    "candidates": _fact_candidates(facts),
                    "acceptance": accept,
                    "entity_name": str(facts.get("entityName", "")),
                }
            except Exception as exc:
                sec_failures[cik10] = f"{type(exc).__name__}: {exc}"
                per_cik[cik10] = {"candidates": [], "acceptance": {}, "entity_name": ""}

    rows = []
    unresolved_symbols = Counter()
    unresolved_reasons = Counter()
    for offset, req in enumerate(batch):
        idx = start + offset + 1
        sym = req["historical_symbol"].upper()
        cutoff = _target_cutoff(req)
        cik10 = cik_map.get(sym, "")
        selected = None
        reason = ""
        if not cik10:
            reason = "cik_unresolved"
        else:
            selected, reason = _select_fact(req, per_cik[cik10]["candidates"], per_cik[cik10]["acceptance"])

        if selected:
            accn = selected["accn"]
            source_ref = (
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
                f"#accn={accn};tag={selected['tag']};end={selected['end'].isoformat()}"
            )
            rows.append({
                "observation_index": str(idx),
                "historical_symbol": sym,
                "target_trade_date": req["trade_date"],
                "target_cutoff_local": cutoff.isoformat(),
                "cik": cik10,
                "fact_date": selected["end"].isoformat(),
                "available_at": selected["available"].isoformat(),
                "shares_outstanding": str(selected["val"]),
                "source_tag": selected["tag"],
                "form": selected["form"],
                "accession": accn,
                "filed_date": selected["filed"].isoformat(),
                "staleness_days": str(selected["staleness_days"]),
                "source_grade": "A" if selected["tag"].startswith("dei:") else "B",
                "source_reference": source_ref,
                "status": "RESOLVED",
                "unresolved_reason": "",
                "research_use_only": "1",
            })
        else:
            unresolved_symbols[sym] += 1
            unresolved_reasons[reason] += 1
            rows.append({
                "observation_index": str(idx),
                "historical_symbol": sym,
                "target_trade_date": req["trade_date"],
                "target_cutoff_local": cutoff.isoformat(),
                "cik": cik10,
                "fact_date": "",
                "available_at": "",
                "shares_outstanding": "",
                "source_tag": "",
                "form": "",
                "accession": "",
                "filed_date": "",
                "staleness_days": "",
                "source_grade": "",
                "source_reference": "",
                "status": "UNRESOLVED",
                "unresolved_reason": reason,
                "research_use_only": "1",
            })

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    resolved = sum(r["status"] == "RESOLVED" for r in rows)
    report_obj = {
        "schema_version": "1",
        "purpose": "G4 batch point-in-time shares-outstanding evidence from public SEC XBRL facts.",
        "research_use_only": True,
        "batch_start_zero_based": start,
        "batch_count": count,
        "observation_index_first": start + 1,
        "observation_index_last": start + count,
        "unique_symbol_count": len(symbols),
        "resolved_count": resolved,
        "unresolved_count": count - resolved,
        "resolution_rate": resolved / count,
        "cik_resolved_symbol_count": len(cik_map),
        "cik_unresolved_symbols": sorted(set(symbols) - set(cik_map)),
        "cik_resolution_methods": cik_methods,
        "unresolved_observations_by_symbol": dict(sorted(unresolved_symbols.items())),
        "unresolved_reasons": dict(unresolved_reasons),
        "sec_fetch_failures": sec_failures,
        "max_staleness_days": MAX_STALENESS_DAYS,
        "availability_policy": "SEC acceptanceDateTime must be at or before the earliest requested local market window; missing exact acceptance is conservatively placed at 23:59:59 on filed date.",
        "future_filed_facts_prohibited": True,
        "output_path": str(output),
        "fact_bundle_path": str(fact_bundle) if fact_bundle is not None else "",
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(report_obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_obj


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--requirements", type=Path, required=True)
    ap.add_argument("--overrides", type=Path, required=True)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--count", type=int, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--fact-bundle", type=Path)
    args = ap.parse_args()
    print(json.dumps(build(
        requirements=args.requirements,
        overrides=args.overrides,
        start=args.start,
        count=args.count,
        output=args.output,
        report=args.report,
        fact_bundle=args.fact_bundle,
    ), indent=2))


if __name__ == "__main__":
    main()
