from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import metadata_resolver as mr

SCHEMA_VERSION = "0.19.0"
UTC = timezone.utc
NY = ZoneInfo("America/New_York")

# Quality is deliberately stricter than resolution. A record may be resolvable yet still be quarantined.
ANNOUNCEMENT_CONFLICT_SECONDS = 60
SHARES_CONFLICT_REL_TOL = 0.02
SHARES_NEARBY_DAYS = 7
SHARES_NEARBY_REL_TOL = 0.10
SHARES_JUMP_REL_TOL = 0.50
CONTROL_NUMERIC_REL_TOL = 0.05

SOURCE_PRIORITY = {
    "official_newswire_archive": 10,
    "ibes_announcement": 20,
    "nyse_daily_taq_master": 10,
    "nasdaq_daily_list": 10,
    "sec_xbrl_companyfacts": 20,
    "generic_authorized_reference_data": 30,
    "sec_edgar_submission_header": 60,
    "samplefirms_research_universe": 70,
    "synthetic_fixture": 90,
}

SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "BLOCKING": 2}


@dataclass(frozen=True)
class QualityIssue:
    issue_id: str
    domain: str
    key: str
    severity: str
    code: str
    message: str
    source_ids: str
    values: str
    quarantined: int
    research_use_only: int = 1


@dataclass(frozen=True)
class DomainQuality:
    domain: str
    required_count: int
    resolver_ready_count: int
    quality_clear_count: int
    quarantined_count: int
    warning_count: int
    quality_score: float
    status: str
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: Iterable[object]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    vals = [asdict(x) if hasattr(x, "__dataclass_fields__") else dict(x) for x in rows]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(vals[0].keys()))
        w.writeheader(); w.writerows(vals)


def _fmt(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_dt(v: str, tz: str = "") -> datetime | None:
    try:
        return mr._parse_aware(v, field="timestamp", default_timezone=tz)
    except Exception:
        return None


def _priority(src: mr.MetadataSourceContract) -> int:
    return SOURCE_PRIORITY.get(src.source_family, 50)


def _load_sources(contract_path: Path):
    contracts, _ = mr.load_contract(contract_path)
    root = contract_path.parent.parent
    loaded = []
    issues = []
    for src in contracts:
        if not src.enabled:
            continue
        try:
            rows, p = mr._load_source_rows(src, root)
            loaded.append((src, rows, p))
        except Exception as exc:
            issues.append(f"{src.source_id}: {exc}")
    return loaded, issues


def _issue(domain: str, key: str, severity: str, code: str, message: str,
           source_ids: Iterable[str] = (), values: Iterable[str] = (), quarantine: bool = False) -> QualityIssue:
    raw = f"{domain}|{key}|{severity}|{code}|{'|'.join(sorted(source_ids))}|{'|'.join(map(str, values))}"
    iid = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return QualityIssue(iid, domain, key, severity, code, message,
                        ";".join(sorted(set(source_ids))), ";".join(map(str, values)), int(quarantine))


def _announcement_candidates(events, loaded):
    by_event = defaultdict(list)
    for e in events:
        for src, rows, path in loaded:
            if src.record_kind != "announcement_timestamp":
                continue
            for row in rows:
                if not mr._match_event(row, src, e):
                    continue
                raw_ts = mr._get(row, src, "public_announcement_ts") or mr._get(row, src, "timestamp")
                ts = _parse_dt(raw_ts, src.timezone) if raw_ts else None
                if ts is None:
                    continue
                kind = (mr._get(row, src, "timestamp_kind") or "other_public_proxy").lower()
                grade = (mr._get(row, src, "source_grade") or "C").upper()
                exact = kind in mr.ANNOUNCEMENT_EXACT_KINDS and grade in {"A", "B"}
                by_event[e["event_id"]].append({
                    "ts": ts, "kind": kind, "grade": grade, "exact": exact,
                    "source_id": src.source_id, "source_family": src.source_family,
                    "priority": _priority(src), "path": str(path),
                })
    return by_event


def audit_announcements(events, resolver_rows, loaded) -> tuple[list[QualityIssue], set[str], int]:
    issues: list[QualityIssue] = []
    quarantined: set[str] = set()
    candidates = _announcement_candidates(events, loaded)
    resolver = {r["event_id"]: r for r in resolver_rows}
    warnings = 0

    for e in events:
        eid = e["event_id"]
        first = mr._event_trade_dt(e["first_documented_illicit_trade_ts"])
        cands = candidates.get(eid, [])
        exact = sorted([x for x in cands if x["exact"]], key=lambda x: (x["priority"], x["ts"]))
        if exact:
            times = [x["ts"] for x in exact]
            spread = (max(times) - min(times)).total_seconds()
            if spread > ANNOUNCEMENT_CONFLICT_SECONDS:
                quarantined.add(eid)
                issues.append(_issue("announcement", eid, "BLOCKING", "ANN_EXACT_CONFLICT",
                    f"Authoritative exact-release candidates disagree by {int(spread)} seconds (> {ANNOUNCEMENT_CONFLICT_SECONDS}s).",
                    [x["source_id"] for x in exact], [_fmt(x["ts"]) for x in exact], True))
            elif len(exact) > 1 and spread > 0:
                warnings += 1
                issues.append(_issue("announcement", eid, "WARNING", "ANN_EXACT_MINOR_DISAGREEMENT",
                    f"Exact-release candidates differ by {int(spread)} seconds but remain within reconciliation tolerance.",
                    [x["source_id"] for x in exact], [_fmt(x["ts"]) for x in exact]))
            earliest = min(times)
            if earliest <= first:
                quarantined.add(eid)
                issues.append(_issue("announcement", eid, "BLOCKING", "ANN_NOT_AFTER_FIRST_TRADE",
                    "Resolved first-public timestamp is not after the documented first illicit trade; event-clock semantics require manual review.",
                    [x["source_id"] for x in exact], [_fmt(first), _fmt(earliest)], True))
        row = resolver.get(eid, {})
        if row.get("resolution_status") == "resolved_exact_public_timestamp":
            if row.get("timestamp_confidence") not in {"A-EXACT", "B-EXACT"}:
                quarantined.add(eid)
                issues.append(_issue("announcement", eid, "BLOCKING", "ANN_WEAK_EXACT_CLASSIFICATION",
                    "Resolver marked the event exact but the confidence class is not A/B exact.",
                    [row.get("source_id", "")], [row.get("timestamp_confidence", "")], True))
    return issues, quarantined, warnings


def _security_candidates(symbol: str, td: str, loaded):
    out = []
    for src, rows, path in loaded:
        if src.record_kind != "security_master":
            continue
        for row in rows:
            sym = (mr._get(row, src, "historical_symbol") or mr._get(row, src, "symbol")).upper()
            if sym != symbol.upper():
                continue
            eff = mr._get(row, src, "effective_date") or mr._get(row, src, "trade_date")
            end = mr._get(row, src, "effective_to")
            if not eff or eff > td or (end and end < td):
                continue
            ex = mr._normalize_exchange(mr._get(row, src, "primary_exchange") or mr._get(row, src, "listed_exchange"))
            if ex:
                out.append({"exchange": ex, "effective": eff, "source_id": src.source_id,
                            "source_family": src.source_family, "priority": _priority(src), "path": str(path)})
    return out


def audit_exchanges(events, resolver_rows, loaded) -> tuple[list[QualityIssue], set[str], int]:
    issues: list[QualityIssue] = []
    quarantined: set[str] = set()
    warnings = 0
    for e in events:
        eid, sym, td = e["event_id"], e["historical_symbol"], e["first_documented_illicit_trade_ts"][:10]
        cands = _security_candidates(sym, td, loaded)
        exchanges = sorted(set(x["exchange"] for x in cands))
        if len(exchanges) > 1:
            quarantined.add(eid)
            issues.append(_issue("exchange", eid, "BLOCKING", "EXCHANGE_OVERLAP_CONFLICT",
                "Overlapping point-in-time security-master records disagree on primary listing exchange.",
                [x["source_id"] for x in cands], exchanges, True))
        # Same exchange across multiple sources is positive corroboration, not a conflict.
        if len(cands) > 1 and len(exchanges) == 1:
            issues.append(_issue("exchange", eid, "INFO", "EXCHANGE_CORROBORATED",
                "Multiple effective records agree on primary exchange.",
                [x["source_id"] for x in cands], exchanges))
    return issues, quarantined, warnings


def _shares_candidates(symbol: str, td: str, loaded):
    target_end = datetime.fromisoformat(td + "T23:59:59").replace(tzinfo=NY).astimezone(UTC)
    out = []
    for src, rows, path in loaded:
        if src.record_kind not in {"shares_outstanding", "security_master"}:
            continue
        for row in rows:
            sym = (mr._get(row, src, "historical_symbol") or mr._get(row, src, "symbol")).upper()
            if sym != symbol.upper():
                continue
            fd = mr._get(row, src, "fact_date") or mr._get(row, src, "effective_date") or mr._get(row, src, "trade_date")
            if not fd or fd > td:
                continue
            raw = mr._get(row, src, "shares_outstanding")
            millions = mr._get(row, src, "shares_outstanding_millions")
            val = mr._parse_float(raw)
            if val is None and millions:
                m = mr._parse_float(millions); val = m * 1_000_000 if m is not None else None
            if val is None or val <= 0:
                continue
            avail = mr._get(row, src, "available_at")
            if avail:
                a = _parse_dt(avail, src.timezone)
                if a is None or a > target_end:
                    continue
            stale = (date.fromisoformat(td) - date.fromisoformat(fd)).days
            out.append({"value": float(val), "fact_date": fd, "stale": stale, "source_id": src.source_id,
                        "source_family": src.source_family, "priority": _priority(src), "available_at": avail,
                        "path": str(path)})
    return out


def _rel_diff(a: float, b: float) -> float:
    d = max(abs(a), abs(b), 1.0)
    return abs(a - b) / d


def audit_shares(symbol_dates, resolver_rows, loaded, max_staleness_days: int = 130) -> tuple[list[QualityIssue], set[str], int]:
    issues: list[QualityIssue] = []
    quarantined: set[str] = set()
    warnings = 0
    by_key = {(r["historical_symbol"].upper(), r["trade_date"]): r for r in resolver_rows}

    for req in symbol_dates:
        sym, td = req["historical_symbol"].upper(), req["trade_date"]
        key = f"{sym}|{td}"
        cands = _shares_candidates(sym, td, loaded)
        if not cands:
            continue
        freshest = min(x["stale"] for x in cands)
        peers = [x for x in cands if x["stale"] == freshest]
        if len(peers) > 1:
            vals = [x["value"] for x in peers]
            if max(vals) > 0 and _rel_diff(min(vals), max(vals)) > SHARES_CONFLICT_REL_TOL:
                quarantined.add(key)
                issues.append(_issue("shares", key, "BLOCKING", "SHARES_SAME_DATE_CONFLICT",
                    f"Equally fresh shares-outstanding candidates differ by more than {SHARES_CONFLICT_REL_TOL:.0%}.",
                    [x["source_id"] for x in peers], [f"{x['fact_date']}:{x['value']:.0f}" for x in peers], True))
        # Nearby published facts should not diverge sharply without an explicit corporate-action explanation.
        recent = sorted([x for x in cands if x["stale"] <= freshest + SHARES_NEARBY_DAYS], key=lambda x: x["fact_date"], reverse=True)
        if len(recent) >= 2:
            vals = [x["value"] for x in recent]
            if _rel_diff(min(vals), max(vals)) > SHARES_NEARBY_REL_TOL:
                quarantined.add(key)
                issues.append(_issue("shares", key, "BLOCKING", "SHARES_NEARBY_FACT_CONFLICT",
                    f"Nearby point-in-time shares facts differ by more than {SHARES_NEARBY_REL_TOL:.0%}; corporate-action reconciliation required.",
                    [x["source_id"] for x in recent], [f"{x['fact_date']}:{x['value']:.0f}" for x in recent], True))
        rr = by_key.get((sym, td), {})
        if rr.get("resolution_status") == "resolved":
            stale = int(rr.get("staleness_days") or 0)
            if stale > max_staleness_days:
                quarantined.add(key)
                issues.append(_issue("shares", key, "BLOCKING", "SHARES_STALE_RESOLUTION",
                    f"Resolved shares fact is {stale} days old, exceeding {max_staleness_days} days.",
                    [rr.get("source_id", "")], [rr.get("fact_date", "")], True))
            elif stale > 90:
                warnings += 1
                issues.append(_issue("shares", key, "WARNING", "SHARES_AGING_FACT",
                    f"Resolved shares fact is {stale} days old; still within hard limit but should be reviewed.",
                    [rr.get("source_id", "")], [rr.get("fact_date", "")]))

    # Across requested dates, abrupt jumps are quarantined unless exact-date source history itself explains them.
    by_sym = defaultdict(list)
    for r in resolver_rows:
        if r.get("resolution_status") == "resolved" and r.get("shares_outstanding"):
            by_sym[r["historical_symbol"].upper()].append(r)
    for sym, rows in by_sym.items():
        rows.sort(key=lambda x: x["trade_date"])
        for a, b in zip(rows, rows[1:]):
            va, vb = float(a["shares_outstanding"]), float(b["shares_outstanding"])
            if _rel_diff(va, vb) > SHARES_JUMP_REL_TOL and a["fact_date"] == b["fact_date"]:
                # Same effective fact with a value jump is logically inconsistent.
                key = f"{sym}|{b['trade_date']}"
                quarantined.add(key)
                issues.append(_issue("shares", key, "BLOCKING", "SHARES_SERIES_INCONSISTENT",
                    "Shares series changes sharply while claiming the same effective fact date.",
                    [a.get("source_id", ""), b.get("source_id", "")], [str(va), str(vb)], True))
    return issues, quarantined, warnings


def _num(v: str) -> float | None:
    try:
        x = float(str(v).replace(",", ""))
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _control_rows_for_date(d: str, first_cutoff: datetime, loaded):
    by_sym = defaultdict(list)
    for src, rows, path in loaded:
        if src.record_kind != "control_universe":
            continue
        for row in rows:
            rd = mr._get(row, src, "event_date") or mr._get(row, src, "trade_date")
            if rd != d:
                continue
            sym = (mr._get(row, src, "historical_symbol") or mr._get(row, src, "symbol")).upper()
            if not sym:
                continue
            avail = mr._get(row, src, "available_at")
            if avail:
                a = _parse_dt(avail, src.timezone)
                if a is None or a > first_cutoff:
                    continue
            by_sym[sym].append((src, row, path))
    return by_sym


def _control_conflict(a_src, a_row, b_src, b_row) -> list[str]:
    fields = []
    for c in mr.CONTROL_COVARIATES:
        av, bv = mr._get(a_row, a_src, c), mr._get(b_row, b_src, c)
        if not av or not bv:
            continue
        an, bn = _num(av), _num(bv)
        if an is not None and bn is not None:
            if _rel_diff(an, bn) > CONTROL_NUMERIC_REL_TOL:
                fields.append(c)
        elif av.strip().upper() != bv.strip().upper():
            fields.append(c)
    return fields


def audit_controls(events, resolver_rows, loaded) -> tuple[list[QualityIssue], set[str], int]:
    issues: list[QualityIssue] = []
    quarantined: set[str] = set()
    warnings = 0
    by_date = defaultdict(list)
    for e in events:
        by_date[e["first_documented_illicit_trade_ts"][:10]].append(e)
    rr = {r["event_date"]: r for r in resolver_rows}
    for d, evs in sorted(by_date.items()):
        first_cutoff = min(mr._event_trade_dt(e["first_documented_illicit_trade_ts"]) for e in evs)
        candidates = _control_rows_for_date(d, first_cutoff, loaded)
        for sym, arr in candidates.items():
            if len(arr) < 2:
                continue
            conflicting = set()
            for i in range(len(arr)):
                for j in range(i + 1, len(arr)):
                    conflicting.update(_control_conflict(arr[i][0], arr[i][1], arr[j][0], arr[j][1]))
            if conflicting:
                quarantined.add(d)
                issues.append(_issue("control_universe", d, "BLOCKING", "CONTROL_DUPLICATE_CONFLICT",
                    f"Duplicate point-in-time control rows for {sym} disagree on matching covariates: {','.join(sorted(conflicting))}.",
                    [x[0].source_id for x in arr], sorted(conflicting), True))
        row = rr.get(d, {})
        if row.get("readiness_status") == "resolved_for_point_in_time_matching" and int(row.get("candidates_with_pre_event_covariates") or 0) < 3:
            quarantined.add(d)
            issues.append(_issue("control_universe", d, "BLOCKING", "CONTROL_FALSE_READY",
                "Resolver readiness is inconsistent with fewer than three complete point-in-time candidates.",
                str(row.get("source_ids", "")).split(";"), [row.get("candidates_with_pre_event_covariates", "")], True))
    return issues, quarantined, warnings


def _domain_quality(domain: str, required: int, resolver_ready: int, quarantine_count: int,
                    warning_count: int) -> DomainQuality:
    quality_clear = max(0, resolver_ready - quarantine_count)
    if required == 0:
        score = 100.0
    else:
        score = 100.0 * quality_clear / required
        score = max(0.0, score - min(10.0, warning_count * 0.5))
    if resolver_ready < required:
        status = "BLOCKED_INCOMPLETE"
    elif quarantine_count:
        status = "QUARANTINED_CONFLICTS"
    elif warning_count:
        status = "READY_WITH_WARNINGS"
    else:
        status = "QUALITY_CLEAR"
    return DomainQuality(domain, required, resolver_ready, quality_clear, quarantine_count, warning_count, round(score, 2), status)


def build(*, events_path: Path, symbol_dates_path: Path, contract_path: Path,
          resolver_dir: Path, outdir: Path) -> dict:
    events = _read_csv(events_path)
    symbol_dates = _read_csv(symbol_dates_path)
    loaded, contract_issues = _load_sources(contract_path)
    anns = _read_csv(resolver_dir / "announcement_resolutions.csv")
    exch = _read_csv(resolver_dir / "event_exchange_resolutions.csv")
    shares = _read_csv(resolver_dir / "shares_outstanding_resolutions.csv")
    controls = _read_csv(resolver_dir / "control_universe_readiness.csv")
    readiness_path = resolver_dir / "metadata_readiness_summary.json"
    if not readiness_path.exists():
        raise FileNotFoundError(f"resolver summary not found: {readiness_path}")
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))

    ann_issues, ann_quarantine, ann_warn = audit_announcements(events, anns, loaded)
    ex_issues, ex_quarantine, ex_warn = audit_exchanges(events, exch, loaded)
    sh_issues, sh_quarantine, sh_warn = audit_shares(symbol_dates, shares, loaded)
    ct_issues, ct_quarantine, ct_warn = audit_controls(events, controls, loaded)
    issues = ann_issues + ex_issues + sh_issues + ct_issues

    domains = [
        _domain_quality("announcement", len(events), int(readiness.get("announcement_exact_resolved", 0)), len(ann_quarantine), ann_warn),
        _domain_quality("exchange", len(events), int(readiness.get("event_exchange_resolved", 0)), len(ex_quarantine), ex_warn),
        _domain_quality("shares", len(symbol_dates), int(readiness.get("shares_symbol_dates_resolved", 0)), len(sh_quarantine), sh_warn),
        _domain_quality("control_universe", len(controls), int(readiness.get("control_dates_resolved", 0)), len(ct_quarantine), ct_warn),
    ]
    blocking = [x for x in issues if x.severity == "BLOCKING"]
    warnings = [x for x in issues if x.severity == "WARNING"]
    info = [x for x in issues if x.severity == "INFO"]
    coverage_ready = bool(readiness.get("ready_for_non_synthetic_model_evaluation_metadata"))
    all_quality_clear = all(d.status in {"QUALITY_CLEAR", "READY_WITH_WARNINGS"} for d in domains)
    quality_cleared = coverage_ready and all_quality_clear and not blocking and not contract_issues

    # Synthetic/demo data can exercise the plumbing but cannot authorize a real evaluation by itself.
    source_classes = {src.data_classification for src, _, _ in loaded}
    only_synthetic = bool(loaded) and source_classes <= {"synthetic_fixture"}
    real_eval_cleared = quality_cleared and not only_synthetic

    outdir.mkdir(parents=True, exist_ok=True)
    _write_csv(outdir / "metadata_quality_issues.csv", issues)
    _write_csv(outdir / "metadata_domain_quality.csv", domains)
    _write_csv(outdir / "metadata_quarantine.csv", [
        {"domain":"announcement","key":k,"reason":"blocking_quality_issue","research_use_only":1} for k in sorted(ann_quarantine)
    ] + [
        {"domain":"exchange","key":k,"reason":"blocking_quality_issue","research_use_only":1} for k in sorted(ex_quarantine)
    ] + [
        {"domain":"shares","key":k,"reason":"blocking_quality_issue","research_use_only":1} for k in sorted(sh_quarantine)
    ] + [
        {"domain":"control_universe","key":k,"reason":"blocking_quality_issue","research_use_only":1} for k in sorted(ct_quarantine)
    ])

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "Metadata quality/reconciliation gate for historical market-surveillance research; no trading outputs.",
        "research_use_only": True,
        "events_path": str(events_path), "events_sha256": _sha256(events_path),
        "symbol_dates_path": str(symbol_dates_path), "symbol_dates_sha256": _sha256(symbol_dates_path),
        "contract_path": str(contract_path), "contract_sha256": _sha256(contract_path),
        "resolver_dir": str(resolver_dir), "resolver_summary_sha256": _sha256(readiness_path),
        "contract_issues": contract_issues,
        "blocking_issue_count": len(blocking), "warning_issue_count": len(warnings), "info_issue_count": len(info),
        "quarantined_announcement_events": len(ann_quarantine),
        "quarantined_exchange_events": len(ex_quarantine),
        "quarantined_share_symbol_dates": len(sh_quarantine),
        "quarantined_control_dates": len(ct_quarantine),
        "coverage_ready_before_quality": coverage_ready,
        "quality_gate_clear": quality_cleared,
        "only_synthetic_sources": only_synthetic,
        "quality_cleared_for_non_synthetic_model_evaluation": real_eval_cleared,
        "status": "READY" if real_eval_cleared else ("SYNTHETIC_ONLY" if quality_cleared and only_synthetic else "BLOCKED"),
        "domain_quality": [asdict(x) for x in domains],
        "reconciliation_policy": {
            "announcement_exact_conflict_seconds": ANNOUNCEMENT_CONFLICT_SECONDS,
            "shares_same_freshness_relative_tolerance": SHARES_CONFLICT_REL_TOL,
            "shares_nearby_days": SHARES_NEARBY_DAYS,
            "shares_nearby_relative_tolerance": SHARES_NEARBY_REL_TOL,
            "control_numeric_relative_tolerance": CONTROL_NUMERIC_REL_TOL,
            "source_priority": SOURCE_PRIORITY,
            "rule": "coverage cannot unlock evaluation unless Step-19 quality gate is also clear",
        },
        "prohibited_outputs": mr.PROHIBITED_OUTPUTS,
    }
    (outdir / "metadata_quality_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    gate = [{
        "gate_id": "G6_METADATA_QUALITY_RECONCILIATION",
        "status": "READY" if real_eval_cleared else "BLOCKING",
        "coverage_ready": int(coverage_ready),
        "quality_gate_clear": int(quality_cleared),
        "non_synthetic_sources": int(not only_synthetic),
        "blocking_issues": len(blocking),
        "requirement": "All Step-17/18 metadata gates complete, no blocking cross-source conflicts, and at least one non-synthetic authorized/public source.",
        "research_use_only": 1,
    }]
    _write_csv(outdir / "metadata_quality_gate.csv", gate)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit and reconcile point-in-time metadata before model evaluation")
    ap.add_argument("--events", type=Path, required=True)
    ap.add_argument("--symbol-dates", type=Path, required=True)
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--resolver-dir", type=Path, required=True)
    ap.add_argument("--outdir", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(build(events_path=args.events, symbol_dates_path=args.symbol_dates,
                           contract_path=args.contract, resolver_dir=args.resolver_dir, outdir=args.outdir), indent=2))


if __name__ == "__main__":
    main()
