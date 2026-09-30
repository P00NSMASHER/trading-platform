from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

SCHEMA_VERSION = "0.17.4"
NY = ZoneInfo("America/New_York")
UTC = timezone.utc

ALLOWED_RECORD_KINDS = {
    "announcement_timestamp",
    "security_master",
    "shares_outstanding",
    "control_universe",
}
ALLOWED_SOURCE_FAMILIES = {
    "ibes_announcement",
    "official_newswire_archive",
    "issuer_investor_relations_archive",
    "sec_edgar_submission_header",
    "nyse_daily_taq_master",
    "nasdaq_daily_list",
    "sec_xbrl_companyfacts",
    "samplefirms_research_universe",
    "generic_authorized_reference_data",
    "public_listing_evidence",
    "synthetic_fixture",
}
ALLOWED_CLASSIFICATIONS = {
    "authorized_reference_data",
    "public_official_data",
    "public_research_replication",
    "synthetic_fixture",
}
PROHIBITED_SOURCE_CLASSES = {
    "live_stolen_information",
    "leaked_credentials",
    "accidental_private_disclosure",
    "unauthorized_private_data",
}
PROHIBITED_OUTPUTS = [
    "BUY", "SELL", "expected_return", "target_price", "position_size", "order", "execution_instruction"
]

EXCHANGE_MAP = {
    "N": "XNYS",
    "NYSE": "XNYS",
    "XNYS": "XNYS",
    "Q": "XNAS",
    "NASDAQ": "XNAS",
    "NASDAQ NM": "XNAS",
    "NASDAQ GLOBAL SELECT": "XNAS",
    "NASDAQ GLOBAL SELECT MARKET": "XNAS",
    "NASDAQ GLOBAL MARKET": "XNAS",
    "NASDAQ CAPITAL MARKET": "XNAS",
    "XNAS": "XNAS",
    "A": "XASE",
    "XASE": "XASE",
    "NYSE AMERICAN": "XASE",
    "NYSE MKT": "XASE",
    "P": "ARCX",
    "NYSE ARCA": "ARCX",
    "Z": "BATS",
    "BATS": "BATS",
    "V": "IEXG",
    "IEX": "IEXG",
}

ANNOUNCEMENT_EXACT_KINDS = {"first_public_release", "official_newswire_release"}
ANNOUNCEMENT_PROXY_KINDS = {"edgar_acceptance", "issuer_ir_post", "other_public_proxy"}


@dataclass(frozen=True)
class MetadataSourceContract:
    source_id: str
    record_kind: str
    source_family: str
    path: str
    enabled: bool
    authorized: bool
    data_classification: str
    license_reference: str
    delimiter: str
    encoding: str
    timezone: str
    column_map: dict[str, str]
    notes: str = ""


@dataclass(frozen=True)
class AnnouncementResolution:
    event_id: str
    historical_symbol: str
    event_date: str
    first_documented_illicit_trade_ts: str
    public_announcement_ts: str
    resolution_status: str
    timestamp_kind: str
    source_id: str
    source_family: str
    source_grade: str
    source_reference: str
    timestamp_confidence: str
    information_asymmetry_seconds: str
    research_use_only: int = 1


@dataclass(frozen=True)
class EventExchangeResolution:
    event_id: str
    historical_symbol: str
    trade_date: str
    primary_exchange: str
    resolution_status: str
    source_id: str
    source_family: str
    source_reference: str
    itch_requirement: str
    research_use_only: int = 1


@dataclass(frozen=True)
class SharesResolution:
    historical_symbol: str
    trade_date: str
    shares_outstanding: str
    resolution_status: str
    source_id: str
    source_family: str
    source_reference: str
    fact_date: str
    available_at: str
    staleness_days: str
    research_use_only: int = 1


@dataclass(frozen=True)
class ControlDateReadiness:
    event_date: str
    event_count: int
    candidate_count: int
    candidates_with_pre_event_covariates: int
    readiness_status: str
    source_ids: str
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(path: Path, *, delimiter: str = ",", encoding: str = "utf-8") -> list[dict[str, str]]:
    with path.open(newline="", encoding=encoding) as f:
        return list(csv.DictReader(f, delimiter=delimiter))


def _write_csv(path: Path, rows: Iterable[object]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    dict_rows = [asdict(x) if hasattr(x, "__dataclass_fields__") else dict(x) for x in rows]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(dict_rows[0].keys()))
        w.writeheader(); w.writerows(dict_rows)


def _delim(value: str) -> str:
    value = (value or ",").strip()
    if value in {",", "comma"}: return ","
    if value in {"|", "pipe"}: return "|"
    if value in {"tab", "\\t", "\t"}: return "\t"
    if len(value) != 1: raise ValueError(f"invalid delimiter: {value!r}")
    return value


def _parse_aware(value: str, *, field: str, default_timezone: str = "") -> datetime:
    if not value or not value.strip():
        raise ValueError(f"{field} is blank")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        if not default_timezone:
            raise ValueError(f"{field} must be timezone-aware: {value!r}")
        dt = dt.replace(tzinfo=ZoneInfo(default_timezone))
    return dt.astimezone(UTC)


def _event_trade_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(UTC)


def _fmt_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def load_contract(path: Path) -> tuple[list[MetadataSourceContract], dict]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema_version") != "1":
        raise ValueError("metadata contract schema_version must equal '1'")
    sources = obj.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    out: list[MetadataSourceContract] = []
    for raw in sources:
        if not isinstance(raw, dict): raise ValueError("source row must be an object")
        classification = str(raw.get("data_classification", "")).strip()
        if classification in PROHIBITED_SOURCE_CLASSES:
            raise ValueError(f"prohibited metadata source classification: {classification}")
        if classification not in ALLOWED_CLASSIFICATIONS:
            raise ValueError(f"unsupported data_classification: {classification}")
        kind = str(raw.get("record_kind", "")).strip()
        family = str(raw.get("source_family", "")).strip()
        if kind not in ALLOWED_RECORD_KINDS: raise ValueError(f"unsupported record_kind: {kind}")
        if family not in ALLOWED_SOURCE_FAMILIES: raise ValueError(f"unsupported source_family: {family}")
        cm = raw.get("column_map", {})
        if not isinstance(cm, dict): raise ValueError("column_map must be an object")
        # Contract files must never become credential containers.
        for k in raw:
            lk = k.lower()
            if any(x in lk for x in ("password", "secret", "api_key", "token", "credential")):
                raise ValueError(f"credential-like field prohibited in contract: {k}")
        out.append(MetadataSourceContract(
            source_id=str(raw.get("source_id", "")).strip(), record_kind=kind, source_family=family,
            path=str(raw.get("path", "")).strip(), enabled=bool(raw.get("enabled", True)),
            authorized=bool(raw.get("authorized", False)), data_classification=classification,
            license_reference=str(raw.get("license_reference", "")).strip(),
            delimiter=_delim(str(raw.get("delimiter", ","))), encoding=str(raw.get("encoding", "utf-8")),
            timezone=str(raw.get("timezone", "")).strip(), column_map={str(k):str(v) for k,v in cm.items()},
            notes=str(raw.get("notes", "")).strip(),
        ))
    return out, obj


def _load_source_rows(source: MetadataSourceContract, root: Path) -> tuple[list[dict[str, str]], Path]:
    p = Path(source.path)
    if not p.is_absolute(): p = (root / p).resolve()
    if not source.enabled: return [], p
    if not p.exists():
        raise FileNotFoundError(f"enabled metadata source does not exist: {p}")
    if not source.authorized and source.data_classification == "authorized_reference_data":
        raise ValueError(f"authorized_reference_data source must set authorized=true: {source.source_id}")
    return _read_csv(p, delimiter=source.delimiter, encoding=source.encoding), p


def _get(row: dict[str, str], source: MetadataSourceContract, canonical: str) -> str:
    col = source.column_map.get(canonical, canonical)
    return str(row.get(col, "") or "").strip()


def _match_event(row: dict[str, str], source: MetadataSourceContract, event: dict[str, str]) -> bool:
    rid = _get(row, source, "event_id")
    if rid:
        return rid == event["event_id"]
    sym = _get(row, source, "historical_symbol") or _get(row, source, "symbol")
    d = _get(row, source, "event_date") or _get(row, source, "trade_date")
    return bool(sym and d and sym.upper() == event["historical_symbol"].upper() and d == event["first_documented_illicit_trade_ts"][:10])


def resolve_announcements(events: list[dict[str, str]], sources: list[tuple[MetadataSourceContract, list[dict[str,str]], Path]]) -> list[AnnouncementResolution]:
    ann_sources = [x for x in sources if x[0].record_kind == "announcement_timestamp"]
    out: list[AnnouncementResolution] = []
    for e in events:
        first = _event_trade_dt(e["first_documented_illicit_trade_ts"])
        candidates = []
        for src, rows, path in ann_sources:
            for row in rows:
                if not _match_event(row, src, e): continue
                raw_ts = _get(row, src, "public_announcement_ts") or _get(row, src, "timestamp")
                if not raw_ts: continue
                try: ts = _parse_aware(raw_ts, field="public_announcement_ts", default_timezone=src.timezone)
                except ValueError: continue
                kind = (_get(row, src, "timestamp_kind") or "other_public_proxy").lower()
                grade = (_get(row, src, "source_grade") or "C").upper()
                ref = _get(row, src, "source_reference") or str(path)
                exact = kind in ANNOUNCEMENT_EXACT_KINDS and grade in {"A", "B"}
                status = "resolved_exact_public_timestamp" if exact else "proxy_public_timestamp_not_exact_release"
                priority = (0 if exact else 1, 0 if grade == "A" else 1 if grade == "B" else 2, ts)
                candidates.append((priority, ts, kind, grade, src, ref, status))
        if candidates:
            _, ts, kind, grade, src, ref, status = sorted(candidates, key=lambda x:x[0])[0]
            asym = int((ts-first).total_seconds()) if ts >= first else ""
            confidence = "A-EXACT" if status.startswith("resolved_exact") and grade == "A" else "B-EXACT" if status.startswith("resolved_exact") else "C-PROXY"
            out.append(AnnouncementResolution(
                event_id=e["event_id"], historical_symbol=e["historical_symbol"], event_date=first.astimezone(NY).date().isoformat(),
                first_documented_illicit_trade_ts=_fmt_utc(first), public_announcement_ts=_fmt_utc(ts),
                resolution_status=status, timestamp_kind=kind, source_id=src.source_id, source_family=src.source_family,
                source_grade=grade, source_reference=ref, timestamp_confidence=confidence,
                information_asymmetry_seconds=str(asym),
            ))
        else:
            out.append(AnnouncementResolution(
                event_id=e["event_id"], historical_symbol=e["historical_symbol"], event_date=first.astimezone(NY).date().isoformat(),
                first_documented_illicit_trade_ts=_fmt_utc(first), public_announcement_ts="",
                resolution_status="unresolved", timestamp_kind="", source_id="", source_family="", source_grade="", source_reference="",
                timestamp_confidence="UNRESOLVED", information_asymmetry_seconds="",
            ))
    return out


def _load_reviewed_announcement_exclusions(
    raw_contract: dict,
    root: Path,
    events: list[dict[str, str]],
) -> tuple[set[str], dict]:
    spec = raw_contract.get("reviewed_announcement_exclusions")
    if not spec:
        return set(), {"enabled": False, "applied_count": 0}
    if not isinstance(spec, dict):
        raise ValueError("reviewed_announcement_exclusions must be an object")
    if not bool(spec.get("enabled", False)):
        return set(), {"enabled": False, "applied_count": 0}

    mode = str(spec.get("mode", "")).strip()
    if mode != "reviewed_fail_closed_exclusions":
        raise ValueError("reviewed_announcement_exclusions.mode must equal reviewed_fail_closed_exclusions")

    raw_path = str(spec.get("path", "")).strip()
    expected_sha = str(spec.get("expected_sha256", "")).strip().lower()
    expected_count = int(spec.get("expected_count", 0))
    required_status = str(spec.get("require_resolution_status", "")).strip()
    if not raw_path:
        raise ValueError("reviewed_announcement_exclusions.path is required")
    if len(expected_sha) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha):
        raise ValueError("reviewed_announcement_exclusions.expected_sha256 must be a 64-character SHA-256 digest")
    if expected_count < 0:
        raise ValueError("reviewed_announcement_exclusions.expected_count must be >= 0")
    if not required_status:
        raise ValueError("reviewed_announcement_exclusions.require_resolution_status is required")

    p = Path(raw_path)
    if not p.is_absolute():
        p = (root / p).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"reviewed announcement exclusion receipt not found: {p}")
    actual_sha = _sha256(p)
    if actual_sha != expected_sha:
        raise ValueError("reviewed announcement exclusion receipt SHA-256 mismatch")

    obj = json.loads(p.read_text(encoding="utf-8"))
    if obj.get("schema_version") != "1":
        raise ValueError("reviewed announcement exclusion receipt schema_version must equal '1'")
    if obj.get("research_use_only") is not True:
        raise ValueError("reviewed announcement exclusion receipt must set research_use_only=true")
    rows = obj.get("exclusions")
    if not isinstance(rows, list):
        raise ValueError("reviewed announcement exclusion receipt exclusions must be a list")

    required = {str(e["event_id"]): e for e in events}
    exclusions: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("reviewed announcement exclusion row must be an object")
        if str(row.get("resolution_status", "")).strip() != required_status:
            raise ValueError("reviewed announcement exclusion row has unapproved resolution_status")
        event_id = str(row.get("event_id", "")).strip()
        if not event_id:
            raise ValueError("reviewed announcement exclusion row requires event_id")
        if event_id in exclusions:
            raise ValueError(f"duplicate reviewed announcement exclusion: {event_id}")
        event = required.get(event_id)
        if event is None:
            raise ValueError(f"reviewed announcement exclusion references non-required event: {event_id}")
        if str(row.get("historical_symbol", "")).strip().upper() != str(event["historical_symbol"]).strip().upper():
            raise ValueError(f"reviewed announcement exclusion symbol mismatch: {event_id}")
        if str(row.get("first_documented_illicit_trade_ts", "")).strip() != str(event["first_documented_illicit_trade_ts"]).strip():
            raise ValueError(f"reviewed announcement exclusion first-trade timestamp mismatch: {event_id}")
        exclusions.add(event_id)

    if len(exclusions) != expected_count:
        raise ValueError(
            f"reviewed announcement exclusion count mismatch: expected {expected_count}, got {len(exclusions)}"
        )
    # Exclusions intentionally may be a strict subset of required events.
    # A newly admissible exact timestamp must be removed from this receipt; any
    # non-excluded event that still lacks exact evidence remains unresolved and
    # therefore cannot make the G1 exact-timing gate pass.
    extras = exclusions - set(required)
    if extras:
        raise ValueError(f"reviewed announcement exclusions contain non-required events: {sorted(extras)}")

    return exclusions, {
        "enabled": True,
        "mode": mode,
        "path": raw_path,
        "sha256": actual_sha,
        "expected_count": expected_count,
        "applied_count": 0,
        "downstream_policy": str(spec.get("downstream_policy", "")).strip(),
    }


def _apply_reviewed_announcement_exclusions(
    announcements: list[AnnouncementResolution],
    *,
    raw_contract: dict,
    root: Path,
    events: list[dict[str, str]],
) -> tuple[list[AnnouncementResolution], dict]:
    exclusion_ids, meta = _load_reviewed_announcement_exclusions(raw_contract, root, events)
    if not exclusion_ids:
        return announcements, meta

    out: list[AnnouncementResolution] = []
    applied: set[str] = set()
    for row in announcements:
        if row.event_id not in exclusion_ids:
            out.append(row)
            continue
        if row.resolution_status == "resolved_exact_public_timestamp":
            raise ValueError(
                f"reviewed announcement exclusion is stale because an admissible exact timestamp now resolves {row.event_id}"
            )
        out.append(replace(
            row,
            public_announcement_ts="",
            resolution_status="excluded_fail_closed",
            timestamp_kind="",
            source_id="reviewed-g1-exclusion",
            source_family="",
            source_grade="",
            source_reference=meta["path"],
            timestamp_confidence="EXCLUDED-FAIL-CLOSED",
            information_asymmetry_seconds="",
        ))
        applied.add(row.event_id)

    if applied != exclusion_ids:
        missing = sorted(exclusion_ids - applied)
        raise ValueError(f"reviewed announcement exclusions were not applied to all required events: {missing}")
    meta = {**meta, "applied_count": len(applied)}
    return out, meta


def _normalize_exchange(value: str) -> str:
    v = (value or "").strip().upper()
    return EXCHANGE_MAP.get(v, "")


def _security_rows(sources):
    return [x for x in sources if x[0].record_kind == "security_master"]


def resolve_event_exchanges(events: list[dict[str,str]], sources) -> list[EventExchangeResolution]:
    sec_sources = _security_rows(sources)
    out=[]
    for e in events:
        td = e["first_documented_illicit_trade_ts"][:10]
        matches=[]
        for src, rows, path in sec_sources:
            for row in rows:
                row_event_id = _get(row, src, "event_id")
                if row_event_id and row_event_id != e["event_id"]:
                    continue
                sym = _get(row, src, "historical_symbol") or _get(row, src, "symbol")
                if sym.upper() != e["historical_symbol"].upper(): continue
                eff = _get(row, src, "effective_date") or _get(row, src, "trade_date")
                end = _get(row, src, "effective_to")
                if not eff or eff > td or (end and end < td): continue
                ex = _normalize_exchange(_get(row, src, "primary_exchange") or _get(row, src, "listed_exchange"))
                if not ex: continue
                # Event-bound evidence wins over symbol/date fallback; within each class,
                # prefer exact-date records and then the latest effective record.
                event_bound = 0 if row_event_id else 1
                exact = 0 if eff == td else 1
                ref = _get(row, src, "source_reference") or str(path)
                matches.append(((event_bound, exact, -date.fromisoformat(eff).toordinal()), ex, src, ref))
        if matches:
            _, ex, src, ref = sorted(matches, key=lambda x:x[0])[0]
            itch = "required" if ex == "XNAS" else "not_required_for_primary_market_order_flow"
            out.append(EventExchangeResolution(e["event_id"], e["historical_symbol"], td, ex, "resolved", src.source_id, src.source_family, ref, itch))
        else:
            out.append(EventExchangeResolution(e["event_id"], e["historical_symbol"], td, "", "unresolved", "", "", "", "conditional_pending_exchange_resolution"))
    return out


def _parse_float(value: str) -> float | None:
    try:
        x=float(str(value).replace(",", "").strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _shares_target_cutoff(row: dict[str, str]) -> datetime:
    td = row["trade_date"]
    starts = []
    for interval in str(row.get("window_intervals_local", "") or "").split(";"):
        interval = interval.strip()
        if not interval or "-" not in interval:
            continue
        start = interval.split("-", 1)[0].strip()
        try:
            hh, mm = start.split(":", 1)
            starts.append((int(hh), int(mm)))
        except Exception:
            continue
    if starts:
        hh, mm = min(starts)
        local = datetime.fromisoformat(f"{td}T{hh:02d}:{mm:02d}:00").replace(tzinfo=NY)
    else:
        local = datetime.fromisoformat(td + "T23:59:59").replace(tzinfo=NY)
    return local.astimezone(UTC)


def resolve_shares(symbol_date_rows: list[dict[str,str]], sources, *, max_staleness_days: int = 130) -> list[SharesResolution]:
    candidates=[]
    for src, rows, path in sources:
        if src.record_kind not in {"shares_outstanding", "security_master"}: continue
        for row in rows:
            sym=(_get(row, src, "historical_symbol") or _get(row, src, "symbol")).upper()
            if not sym: continue
            fact_date=_get(row, src, "fact_date") or _get(row, src, "effective_date") or _get(row, src, "trade_date")
            avail=_get(row, src, "available_at")
            raw=_get(row, src, "shares_outstanding")
            millions=_get(row, src, "shares_outstanding_millions")
            val=_parse_float(raw)
            if val is None and millions:
                m=_parse_float(millions); val = m*1_000_000 if m is not None else None
            if not fact_date or val is None or val <= 0: continue
            target_trade_date=_get(row, src, "target_trade_date")
            ref=_get(row, src, "source_reference") or str(path)
            candidates.append((sym, fact_date, avail, val, target_trade_date, src, ref))
    by_sym=defaultdict(list)
    for x in candidates: by_sym[x[0]].append(x)
    for arr in by_sym.values(): arr.sort(key=lambda x:x[1])
    out=[]
    for r in symbol_date_rows:
        sym=r["historical_symbol"].upper(); td=r["trade_date"]
        cutoff=_shares_target_cutoff(r)
        best=None
        for x in by_sym.get(sym,[]):
            _, fd, avail, val, target_trade_date, src, ref=x
            if target_trade_date and target_trade_date != td: continue
            if fd > td: continue
            # Point-in-time shares must have been public before the earliest
            # requested market interval, not merely by the end of the day.
            if avail:
                try:
                    a=_parse_aware(avail, field="available_at", default_timezone=src.timezone)
                    if a > cutoff: continue
                except ValueError: continue
            stale=_days_between(td, fd)
            if stale > max_staleness_days: continue
            exact_bonus=0 if fd==td else 1
            key=(exact_bonus, stale)
            if best is None or key < best[0]: best=(key,x,stale)
        if best:
            _, x, stale=best; _, fd, avail, val, target_trade_date, src, ref=x
            out.append(SharesResolution(sym, td, f"{val:.6f}".rstrip("0").rstrip("."), "resolved", src.source_id, src.source_family, ref, fd, avail, str(stale)))
        else:
            out.append(SharesResolution(sym, td, "", "unresolved", "", "", "", "", "", ""))
    return out


def _load_reviewed_share_exclusions(raw_contract: dict, root: Path, symbol_date_rows: list[dict[str, str]]) -> tuple[set[tuple[str, str]], dict]:
    spec = raw_contract.get("reviewed_share_exclusions")
    if not spec:
        return set(), {"enabled": False, "applied_count": 0}
    if not isinstance(spec, dict):
        raise ValueError("reviewed_share_exclusions must be an object")
    if not bool(spec.get("enabled", False)):
        return set(), {"enabled": False, "applied_count": 0}

    mode = str(spec.get("mode", "")).strip()
    if mode != "reviewed_fail_closed_exclusions":
        raise ValueError("reviewed_share_exclusions.mode must equal reviewed_fail_closed_exclusions")

    raw_path = str(spec.get("path", "")).strip()
    expected_sha = str(spec.get("expected_sha256", "")).strip().lower()
    expected_count = int(spec.get("expected_count", 0))
    required_status = str(spec.get("require_resolution_status", "")).strip()
    if not raw_path:
        raise ValueError("reviewed_share_exclusions.path is required")
    if len(expected_sha) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha):
        raise ValueError("reviewed_share_exclusions.expected_sha256 must be a 64-character SHA-256 digest")
    if expected_count < 1:
        raise ValueError("reviewed_share_exclusions.expected_count must be >= 1")
    if not required_status:
        raise ValueError("reviewed_share_exclusions.require_resolution_status is required")

    p = Path(raw_path)
    if not p.is_absolute():
        p = (root / p).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"reviewed share exclusion receipt not found: {p}")
    actual_sha = _sha256(p)
    if actual_sha != expected_sha:
        raise ValueError("reviewed share exclusion receipt SHA-256 mismatch")

    obj = json.loads(p.read_text(encoding="utf-8"))
    if obj.get("schema_version") != "1":
        raise ValueError("reviewed share exclusion receipt schema_version must equal '1'")
    if obj.get("research_use_only") is not True:
        raise ValueError("reviewed share exclusion receipt must set research_use_only=true")
    blockers = obj.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        raise ValueError("reviewed share exclusion receipt must contain blockers")

    required_keys = {(str(r["historical_symbol"]).upper(), str(r["trade_date"])) for r in symbol_date_rows}
    exclusions: set[tuple[str, str]] = set()
    for blocker in blockers:
        if not isinstance(blocker, dict):
            raise ValueError("reviewed share exclusion blocker must be an object")
        if str(blocker.get("resolution_status", "")).strip() != required_status:
            raise ValueError("reviewed share exclusion blocker has unapproved resolution_status")
        symbol = str(blocker.get("historical_symbol", "")).strip().upper()
        dates = blocker.get("target_trade_dates")
        if not symbol or not isinstance(dates, list) or not dates:
            raise ValueError("reviewed share exclusion blocker requires historical_symbol and target_trade_dates")
        for trade_date in dates:
            key = (symbol, str(trade_date))
            if key in exclusions:
                raise ValueError(f"duplicate reviewed share exclusion: {symbol}|{trade_date}")
            exclusions.add(key)

    if len(exclusions) != expected_count:
        raise ValueError(f"reviewed share exclusion count mismatch: expected {expected_count}, got {len(exclusions)}")
    extras = exclusions - required_keys
    if extras:
        raise ValueError(f"reviewed share exclusions contain non-required symbol-dates: {sorted(extras)}")

    return exclusions, {
        "enabled": True,
        "mode": mode,
        "path": raw_path,
        "sha256": actual_sha,
        "expected_count": expected_count,
        "applied_count": 0,
        "downstream_policy": str(spec.get("downstream_policy", "")).strip(),
    }


def _apply_reviewed_share_exclusions(
    shares: list[SharesResolution],
    *,
    raw_contract: dict,
    root: Path,
    symbol_date_rows: list[dict[str, str]],
) -> tuple[list[SharesResolution], dict]:
    exclusion_keys, meta = _load_reviewed_share_exclusions(raw_contract, root, symbol_date_rows)
    if not exclusion_keys:
        return shares, meta

    out: list[SharesResolution] = []
    applied: set[tuple[str, str]] = set()
    for row in shares:
        key = (row.historical_symbol.upper(), row.trade_date)
        if key not in exclusion_keys:
            out.append(row)
            continue
        if row.resolution_status == "resolved":
            raise ValueError(
                f"reviewed share exclusion is stale because an admissible exact fact now resolves {row.historical_symbol}|{row.trade_date}"
            )
        out.append(replace(
            row,
            resolution_status="excluded_fail_closed",
            source_id="reviewed-g4-exclusion",
            source_family="",
            source_reference=meta["path"],
        ))
        applied.add(key)

    if applied != exclusion_keys:
        missing = sorted(exclusion_keys - applied)
        raise ValueError(f"reviewed share exclusions were not applied to all required rows: {missing}")
    meta = {**meta, "applied_count": len(applied)}
    return out, meta


CONTROL_COVARIATES = [
    "sector", "index_bucket", "market_cap", "price", "volatility_21d", "normal_volume",
    "normal_turnover", "normal_spread", "options_liquidity", "institutional_ownership", "analyst_coverage",
]


def resolve_control_readiness(events: list[dict[str,str]], sources) -> list[ControlDateReadiness]:
    event_dates=defaultdict(list)
    for e in events: event_dates[e["first_documented_illicit_trade_ts"][:10]].append(e)
    control_sources=[x for x in sources if x[0].record_kind=="control_universe"]
    out=[]
    for d, evs in sorted(event_dates.items()):
        candidates={}
        source_ids=set()
        first_cutoff=min(_event_trade_dt(e["first_documented_illicit_trade_ts"]) for e in evs)
        for src, rows, path in control_sources:
            for row in rows:
                if (_get(row, src, "event_date") or _get(row, src, "trade_date")) != d: continue
                sym=(_get(row, src, "historical_symbol") or _get(row, src, "symbol")).upper()
                if not sym: continue
                # Must be a point-in-time candidate universe for model evaluation.
                avail=_get(row, src, "available_at")
                if avail:
                    try:
                        if _parse_aware(avail, field="available_at", default_timezone=src.timezone) > first_cutoff: continue
                    except ValueError: continue
                elif src.source_family == "samplefirms_research_universe":
                    # Useful for retrospective research candidate enumeration but not enough to close live-model gate.
                    pass
                candidates[sym]=(src,row)
                source_ids.add(src.source_id)
        pre=0
        live_candidate_count=0
        for sym,(src,row) in candidates.items():
            if src.source_family != "samplefirms_research_universe" or _get(row, src, "available_at"):
                live_candidate_count += 1
            if all(_get(row, src, c) for c in CONTROL_COVARIATES): pre += 1
        if live_candidate_count >= 3 and pre >= 3:
            status="resolved_for_point_in_time_matching"
        elif candidates:
            status="partial_candidate_universe_missing_pre_event_covariates_or_availability"
        else:
            status="unresolved"
        out.append(ControlDateReadiness(d,len(evs),len(candidates),pre,status,";".join(sorted(source_ids))))
    return out


def _load_reviewed_control_exclusions(
    raw_contract: dict,
    root: Path,
    events: list[dict[str, str]],
) -> tuple[set[str], dict]:
    spec = raw_contract.get("reviewed_control_exclusions")
    if not spec:
        return set(), {"enabled": False, "applied_count": 0}
    if not isinstance(spec, dict):
        raise ValueError("reviewed_control_exclusions must be an object")
    if not bool(spec.get("enabled", False)):
        return set(), {"enabled": False, "applied_count": 0}

    mode = str(spec.get("mode", "")).strip()
    if mode != "reviewed_fail_closed_exclusions":
        raise ValueError("reviewed_control_exclusions.mode must equal reviewed_fail_closed_exclusions")

    raw_path = str(spec.get("path", "")).strip()
    expected_sha = str(spec.get("expected_sha256", "")).strip().lower()
    expected_count = int(spec.get("expected_count", 0))
    required_status = str(spec.get("require_resolution_status", "")).strip()
    if not raw_path:
        raise ValueError("reviewed_control_exclusions.path is required")
    if len(expected_sha) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha):
        raise ValueError("reviewed_control_exclusions.expected_sha256 must be a 64-character SHA-256 digest")
    if expected_count < 0:
        raise ValueError("reviewed_control_exclusions.expected_count must be >= 0")
    if not required_status:
        raise ValueError("reviewed_control_exclusions.require_resolution_status is required")

    p = Path(raw_path)
    if not p.is_absolute():
        p = (root / p).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"reviewed control exclusion receipt not found: {p}")
    actual_sha = _sha256(p)
    if actual_sha != expected_sha:
        raise ValueError("reviewed control exclusion receipt SHA-256 mismatch")

    obj = json.loads(p.read_text(encoding="utf-8"))
    if obj.get("schema_version") != "1":
        raise ValueError("reviewed control exclusion receipt schema_version must equal '1'")
    if obj.get("research_use_only") is not True:
        raise ValueError("reviewed control exclusion receipt must set research_use_only=true")
    rows = obj.get("exclusions")
    if not isinstance(rows, list):
        raise ValueError("reviewed control exclusion receipt exclusions must be a list")

    required_counts: dict[str, int] = defaultdict(int)
    for event in events:
        required_counts[str(event["first_documented_illicit_trade_ts"])[:10]] += 1

    exclusions: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("reviewed control exclusion row must be an object")
        if str(row.get("resolution_status", "")).strip() != required_status:
            raise ValueError("reviewed control exclusion row has unapproved resolution_status")
        event_date = str(row.get("event_date", "")).strip()
        if not event_date:
            raise ValueError("reviewed control exclusion row requires event_date")
        if event_date in exclusions:
            raise ValueError(f"duplicate reviewed control exclusion: {event_date}")
        if event_date not in required_counts:
            raise ValueError(f"reviewed control exclusion references non-required event date: {event_date}")
        if int(row.get("event_count", 0)) != required_counts[event_date]:
            raise ValueError(f"reviewed control exclusion event_count mismatch: {event_date}")
        exclusions.add(event_date)

    if len(exclusions) != expected_count:
        raise ValueError(
            f"reviewed control exclusion count mismatch: expected {expected_count}, got {len(exclusions)}"
        )
    # Exclusions may shrink as genuine point-in-time control evidence arrives.
    # Non-excluded dates that remain unresolved stay unresolved; a stale exclusion
    # still fails closed in _apply_reviewed_control_exclusions.
    extras = exclusions - set(required_counts)
    if extras:
        raise ValueError(f"reviewed control exclusions contain non-required dates: {sorted(extras)}")

    return exclusions, {
        "enabled": True,
        "mode": mode,
        "path": raw_path,
        "sha256": actual_sha,
        "expected_count": expected_count,
        "applied_count": 0,
        "downstream_policy": str(spec.get("downstream_policy", "")).strip(),
    }


def _apply_reviewed_control_exclusions(
    controls: list[ControlDateReadiness],
    *,
    raw_contract: dict,
    root: Path,
    events: list[dict[str, str]],
) -> tuple[list[ControlDateReadiness], dict]:
    exclusion_dates, meta = _load_reviewed_control_exclusions(raw_contract, root, events)
    if not exclusion_dates:
        return controls, meta

    out: list[ControlDateReadiness] = []
    applied: set[str] = set()
    for row in controls:
        if row.event_date not in exclusion_dates:
            out.append(row)
            continue
        if row.readiness_status == "resolved_for_point_in_time_matching":
            raise ValueError(
                f"reviewed control exclusion is stale because admissible point-in-time controls now resolve {row.event_date}"
            )
        if row.readiness_status != "unresolved" or row.candidate_count or row.candidates_with_pre_event_covariates:
            raise ValueError(
                f"reviewed control exclusion requires review because new control-universe evidence now exists for {row.event_date}"
            )
        out.append(replace(
            row,
            candidate_count=0,
            candidates_with_pre_event_covariates=0,
            readiness_status="excluded_fail_closed",
            source_ids="reviewed-g5-exclusion",
        ))
        applied.add(row.event_date)

    if applied != exclusion_dates:
        missing = sorted(exclusion_dates - applied)
        raise ValueError(f"reviewed control exclusions were not applied to all required dates: {missing}")
    meta = {**meta, "applied_count": len(applied)}
    return out, meta


def _read_symbol_dates(path: Path) -> list[dict[str,str]]:
    return _read_csv(path)


def _source_inventory(loaded_sources) -> list[dict]:
    out=[]
    for src, rows, p in loaded_sources:
        out.append({
            "source_id":src.source_id,"record_kind":src.record_kind,"source_family":src.source_family,
            "enabled":src.enabled,"authorized":src.authorized,"data_classification":src.data_classification,
            "path":str(p),"exists":p.exists(),"row_count":len(rows),"sha256":_sha256(p) if p.exists() else "",
            "license_reference_present":bool(src.license_reference),
        })
    return out


def build(events_path: Path, symbol_date_path: Path, contract_path: Path, outdir: Path) -> dict:
    events=_read_csv(events_path)
    symbol_dates=_read_symbol_dates(symbol_date_path)
    contracts, raw_contract=load_contract(contract_path)
    root=contract_path.parent.parent
    loaded=[]
    issues=[]
    for src in contracts:
        if not src.enabled:
            loaded.append((src,[],(root/Path(src.path)).resolve() if not Path(src.path).is_absolute() else Path(src.path)))
            continue
        try:
            rows,p=_load_source_rows(src,root); loaded.append((src,rows,p))
        except Exception as exc:
            issues.append(f"{src.source_id}: {exc}")
            p=Path(src.path); p=(root/p).resolve() if not p.is_absolute() else p
            loaded.append((src,[],p))
    anns=resolve_announcements(events,loaded)
    anns, announcement_exclusion_meta = _apply_reviewed_announcement_exclusions(
        anns, raw_contract=raw_contract, root=root, events=events
    )
    exch=resolve_event_exchanges(events,loaded)
    shares=resolve_shares(symbol_dates,loaded)
    shares, share_exclusion_meta = _apply_reviewed_share_exclusions(
        shares, raw_contract=raw_contract, root=root, symbol_date_rows=symbol_dates
    )
    controls=resolve_control_readiness(events,loaded)
    controls, control_exclusion_meta = _apply_reviewed_control_exclusions(
        controls, raw_contract=raw_contract, root=root, events=events
    )
    outdir.mkdir(parents=True,exist_ok=True)
    _write_csv(outdir/"announcement_resolutions.csv",anns)
    _write_csv(outdir/"event_exchange_resolutions.csv",exch)
    _write_csv(outdir/"shares_outstanding_resolutions.csv",shares)
    _write_csv(outdir/"control_universe_readiness.csv",controls)
    inventory=_source_inventory(loaded)
    (outdir/"metadata_source_inventory.json").write_text(json.dumps(inventory,indent=2),encoding="utf-8")

    exact=sum(x.resolution_status=="resolved_exact_public_timestamp" for x in anns)
    proxies=sum(x.resolution_status.startswith("proxy_") for x in anns)
    ann_exc=sum(x.resolution_status=="excluded_fail_closed" for x in anns)
    ann_unresolved=sum(x.resolution_status=="unresolved" for x in anns)
    ann_accounted=exact+ann_exc
    g1_ready=ann_accounted==len(events) and ann_unresolved==0 and proxies==0
    g1_exact_timing_ready=exact==len(events)
    ex_res=sum(x.resolution_status=="resolved" for x in exch)
    sh_res=sum(x.resolution_status=="resolved" for x in shares)
    sh_exc=sum(x.resolution_status=="excluded_fail_closed" for x in shares)
    sh_unresolved=sum(x.resolution_status=="unresolved" for x in shares)
    sh_accounted=sh_res+sh_exc
    g4_ready=sh_accounted==len(symbol_dates) and sh_unresolved==0
    ctl_res=sum(x.readiness_status=="resolved_for_point_in_time_matching" for x in controls)
    ctl_exc=sum(x.readiness_status=="excluded_fail_closed" for x in controls)
    ctl_partial=sum(x.readiness_status.startswith("partial_") for x in controls)
    ctl_unresolved=sum(x.readiness_status=="unresolved" for x in controls)
    ctl_accounted=ctl_res+ctl_exc
    g5_ready=ctl_accounted==len(controls) and ctl_partial==0 and ctl_unresolved==0
    g5_model_eval_ready=ctl_res==len(controls)
    nasdaq=sum(x.primary_exchange=="XNAS" for x in exch if x.resolution_status=="resolved")
    summary={
        "schema_version":SCHEMA_VERSION,
        "purpose":"Point-in-time metadata resolution for historical market-surveillance research; no trading outputs.",
        "research_use_only":True,
        "events_path":str(events_path),"events_sha256":_sha256(events_path),
        "symbol_date_requirements_path":str(symbol_date_path),"symbol_date_requirements_sha256":_sha256(symbol_date_path),
        "contract_path":str(contract_path),"contract_sha256":_sha256(contract_path),
        "contract_issues":issues,
        "event_count":len(events),"symbol_date_requirement_count":len(symbol_dates),"event_date_count":len(controls),
        "announcement_exact_resolved":exact,
        "announcement_proxy_only":proxies,
        "announcement_events_excluded":ann_exc,
        "announcement_events_accounted_for":ann_accounted,
        "announcement_unresolved":ann_unresolved,
        "announcement_exclusion_receipt":announcement_exclusion_meta,
        "event_exchange_resolved":ex_res,"event_exchange_unresolved":len(exch)-ex_res,"event_exchange_nasdaq":nasdaq,
        "shares_symbol_dates_resolved":sh_res,
        "shares_symbol_dates_excluded":sh_exc,
        "shares_symbol_dates_accounted_for":sh_accounted,
        "shares_symbol_dates_unresolved":sh_unresolved,
        "shares_exclusion_receipt":share_exclusion_meta,
        "control_dates_resolved":ctl_res,
        "control_dates_excluded":ctl_exc,
        "control_dates_accounted_for":ctl_accounted,
        "control_dates_partial":ctl_partial,
        "control_dates_unresolved":ctl_unresolved,
        "control_exclusion_receipt":control_exclusion_meta,
        "ready_g1_announcement_times":g1_ready,
        "ready_g1_exact_timing_analysis":g1_exact_timing_ready,
        "ready_g3_primary_listing_history":ex_res==len(events),
        "ready_g4_shares_outstanding":g4_ready,
        "ready_g5_matched_control_universe":g5_ready,
        "ready_g5_model_evaluation_controls":g5_model_eval_ready,
        "ready_for_step15_real_backfill_metadata": g1_exact_timing_ready and ex_res==len(events) and g4_ready,
        "ready_for_non_synthetic_model_evaluation_metadata": g1_exact_timing_ready and ex_res==len(events) and g4_ready and g5_model_eval_ready,
        "prohibited_outputs":PROHIBITED_OUTPUTS,
        "source_inventory":inventory,
    }
    (outdir/"metadata_readiness_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    g1_status = (
        "READY_WITH_REVIEWED_EXCLUSIONS" if summary["ready_g1_announcement_times"] and ann_exc
        else "READY" if summary["ready_g1_announcement_times"]
        else "BLOCKING"
    )
    g4_status = (
        "READY_WITH_REVIEWED_EXCLUSIONS" if summary["ready_g4_shares_outstanding"] and sh_exc
        else "READY" if summary["ready_g4_shares_outstanding"]
        else "BLOCKING_FOR_TURNOVER"
    )
    g5_status = (
        "READY_WITH_REVIEWED_EXCLUSIONS" if summary["ready_g5_matched_control_universe"] and ctl_exc
        else "READY" if summary["ready_g5_matched_control_universe"]
        else "BLOCKING_FOR_MODEL_EVAL"
    )
    gates=[
        {"gate_id":"G1_ANNOUNCEMENT_TIMES","status":g1_status,"resolved":exact,"excluded":ann_exc,"accounted_for":ann_accounted,"required":len(events),"requirement":"Every event must have an authoritative/authorized exact first-public announcement timestamp or be covered by an immutable reviewed fail-closed exclusion receipt. Excluded events retain blank announcement timestamps and cannot participate in announcement-timing-dependent analysis; EDGAR acceptance, archive timestamps, and inferred BMO/AMC times do not count as exact."},
        {"gate_id":"G3_PRIMARY_LISTING_HISTORY","status":"READY" if summary["ready_g3_primary_listing_history"] else "BLOCKING_FOR_ITCH","resolved":ex_res,"excluded":0,"accounted_for":ex_res,"required":len(events),"requirement":"Point-in-time primary listing exchange at each event date."},
        {"gate_id":"G4_SHARES_OUTSTANDING","status":g4_status,"resolved":sh_res,"excluded":sh_exc,"accounted_for":sh_accounted,"required":len(symbol_dates),"requirement":"Every required symbol-date must have admissible point-in-time shares outstanding or be covered by an immutable reviewed fail-closed exclusion receipt. Future-filed facts, inferred totals, and excluded-row turnover are prohibited."},
        {"gate_id":"G5_MATCHED_CONTROL_UNIVERSE","status":g5_status,"resolved":ctl_res,"excluded":ctl_exc,"accounted_for":ctl_accounted,"required":len(controls),"requirement":"Every event date must have at least three same-day point-in-time candidates with complete pre-event matching covariates or be covered by an immutable reviewed fail-closed exclusion receipt. Excluded dates cannot contribute matched controls or model-evaluation authorization."},
    ]
    _write_csv(outdir/"metadata_unresolved_gates.csv",gates)
    return summary


def main() -> None:
    ap=argparse.ArgumentParser(description="Resolve point-in-time historical metadata for the private surveillance prototype")
    ap.add_argument("--events",type=Path,required=True)
    ap.add_argument("--symbol-dates",type=Path,required=True)
    ap.add_argument("--contract",type=Path,required=True)
    ap.add_argument("--outdir",type=Path,required=True)
    args=ap.parse_args()
    print(json.dumps(build(args.events,args.symbol_dates,args.contract,args.outdir),indent=2))


if __name__=="__main__": main()
