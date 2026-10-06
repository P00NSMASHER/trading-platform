from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
from pathlib import Path


SCHEMA_VERSION = "1"
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class OwnershipRow:
    event_date: str
    symbol: str
    effective_ts_utc: str
    institutional_ownership: str
    institutional_shares: str
    shares_outstanding: str
    cusip: str
    report_period: str
    source_name: str = "SEC_13F_STRUCTURED_DATA"
    authorization_reference: str = "PUBLIC_SEC_13F_DATASETS"
    research_use_only: int = 1


@dataclass(frozen=True)
class OwnershipGap:
    event_date: str
    symbol: str
    reason: str
    cusip: str = ""
    research_use_only: int = 1


class G5Sec13FOwnershipError(ValueError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_delimited(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    sample = path.read_text(encoding="utf-8-sig", errors="strict")[:4096]
    delimiter = "\t" if "\t" in sample.splitlines()[0] else ","
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(k): str(v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    return fields, rows


def _norm_fields(row: dict[str, str]) -> dict[str, str]:
    return {str(k).strip().upper(): str(v or "").strip() for k, v in row.items()}


def _get(row: dict[str, str], *names: str) -> str:
    upper = _norm_fields(row)
    for name in names:
        value = upper.get(name.upper(), "")
        if value:
            return value
    return ""


def _parse_date(value: str, *, label: str) -> date:
    raw = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise G5Sec13FOwnershipError(
            f"{label} must be YYYY-MM-DD"
        ) from exc


def _parse_aware(value: str, *, label: str) -> datetime:
    raw = str(value or "").strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G5Sec13FOwnershipError(
            f"{label} must be ISO timestamp"
        ) from exc
    if dt.tzinfo is None:
        raise G5Sec13FOwnershipError(f"{label} must include timezone")
    return dt.astimezone(timezone.utc)


def _normalize_cusip(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _load_targets(path: Path) -> list[dict[str, object]]:
    fields, rows = _read_delimited(path)
    required = {
        "event_date",
        "candidate_symbol",
        "latest_acceptable_effective_ts_utc",
    }
    missing = required.difference(fields)
    if missing:
        raise G5Sec13FOwnershipError(
            f"target file missing columns: {sorted(missing)}"
        )
    out = []
    seen = set()
    for row_no, row in enumerate(rows, 2):
        event_date = _parse_date(
            row["event_date"], label=f"target row {row_no} event_date"
        )
        symbol = row["candidate_symbol"].upper()
        cutoff = _parse_aware(
            row["latest_acceptable_effective_ts_utc"],
            label=f"target row {row_no} cutoff",
        )
        key = (event_date.isoformat(), symbol)
        if key in seen:
            raise G5Sec13FOwnershipError(
                f"duplicate target {event_date}|{symbol}"
            )
        seen.add(key)
        out.append({"event_date": event_date, "symbol": symbol, "cutoff": cutoff})
    return out


def _load_cusip_map(path: Path) -> dict[str, list[dict[str, object]]]:
    fields, rows = _read_delimited(path)
    required = {"historical_symbol", "cusip"}
    missing = required.difference(fields)
    if missing:
        raise G5Sec13FOwnershipError(
            f"CUSIP map missing columns: {sorted(missing)}"
        )
    out: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row_no, row in enumerate(rows, 2):
        symbol = row["historical_symbol"].upper()
        cusip = _normalize_cusip(row["cusip"])
        if len(cusip) != 9:
            raise G5Sec13FOwnershipError(
                f"CUSIP map row {row_no}: CUSIP must normalize to 9 characters"
            )
        valid_from = (
            _parse_date(row["valid_from"], label=f"CUSIP row {row_no} valid_from")
            if row.get("valid_from")
            else None
        )
        valid_through = (
            _parse_date(
                row["valid_through"],
                label=f"CUSIP row {row_no} valid_through",
            )
            if row.get("valid_through")
            else None
        )
        out[symbol].append(
            {
                "cusip": cusip,
                "valid_from": valid_from,
                "valid_through": valid_through,
            }
        )
    return out


def _resolve_cusip(
    mappings: dict[str, list[dict[str, object]]],
    *,
    symbol: str,
    event_date: date,
) -> str:
    matches = []
    for row in mappings.get(symbol, []):
        valid_from = row["valid_from"]
        valid_through = row["valid_through"]
        if valid_from is not None and event_date < valid_from:
            continue
        if valid_through is not None and event_date > valid_through:
            continue
        matches.append(str(row["cusip"]))
    matches = sorted(set(matches))
    if len(matches) > 1:
        raise G5Sec13FOwnershipError(
            f"multiple CUSIPs apply to {symbol}|{event_date}: {matches}"
        )
    return matches[0] if matches else ""


def _load_shares(path: Path) -> dict[tuple[str, str], list[dict[str, object]]]:
    fields, rows = _read_delimited(path)
    required = {"event_date", "symbol", "available_at", "shares_outstanding"}
    missing = required.difference(fields)
    if missing:
        raise G5Sec13FOwnershipError(
            f"shares source missing columns: {sorted(missing)}"
        )
    out: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row_no, row in enumerate(rows, 2):
        event_date = _parse_date(
            row["event_date"], label=f"shares row {row_no} event_date"
        )
        symbol = row["symbol"].upper()
        available_at = _parse_aware(
            row["available_at"], label=f"shares row {row_no} available_at"
        )
        try:
            shares = int(float(row["shares_outstanding"]))
        except ValueError as exc:
            raise G5Sec13FOwnershipError(
                f"shares row {row_no}: shares_outstanding invalid"
            ) from exc
        if shares <= 0:
            raise G5Sec13FOwnershipError(
                f"shares row {row_no}: shares_outstanding must be positive"
            )
        out[(event_date.isoformat(), symbol)].append(
            {"available_at": available_at, "shares": shares}
        )
    return out


def _submission_index(path: Path) -> dict[str, dict[str, str]]:
    _fields, rows = _read_delimited(path)
    out = {}
    for row_no, row in enumerate(rows, 2):
        accession = _get(row, "ACCESSION_NUMBER", "ACCESSIONNUMBER")
        cik = _get(row, "CIK")
        filing_date = _get(row, "FILING_DATE", "FILINGDATE")
        report_period = _get(
            row,
            "PERIODOFREPORT",
            "REPORTCALENDARORQUARTER",
            "REPORT_PERIOD",
        )
        form = _get(row, "SUBMISSIONTYPE", "FORM_TYPE", "FORM")
        if not accession or not cik or not filing_date or not report_period:
            continue
        if form and not form.upper().startswith("13F-HR"):
            continue
        out[accession] = {
            "accession": accession,
            "manager_cik": cik.zfill(10) if cik.isdigit() else cik,
            "filing_date": _parse_date(
                filing_date, label=f"submission row {row_no} filing_date"
            ).isoformat(),
            "report_period": _parse_date(
                report_period, label=f"submission row {row_no} report_period"
            ).isoformat(),
        }
    return out


def _load_holdings(
    *,
    infotable_path: Path,
    submissions: dict[str, dict[str, str]],
) -> dict[tuple[str, str], int]:
    _fields, rows = _read_delimited(infotable_path)
    holdings: dict[tuple[str, str], int] = defaultdict(int)
    for row_no, row in enumerate(rows, 2):
        accession = _get(row, "ACCESSION_NUMBER", "ACCESSIONNUMBER")
        if accession not in submissions:
            continue
        cusip = _normalize_cusip(_get(row, "CUSIP"))
        if len(cusip) != 9:
            continue
        amount_type = _get(row, "SSHPRNAMTTYPE", "SHPRNAMTTYPE").upper()
        put_call = _get(row, "PUTCALL").upper()
        if amount_type != "SH" or put_call in {"PUT", "CALL"}:
            continue
        raw_amount = _get(row, "SSHPRNAMT", "SHPRNAMT")
        try:
            amount = int(float(raw_amount))
        except ValueError:
            continue
        if amount < 0:
            raise G5Sec13FOwnershipError(
                f"infotable row {row_no}: negative SSHPRNAMT"
            )
        holdings[(accession, cusip)] += amount
    return holdings


def _selected_accessions_for_target(
    submissions: dict[str, dict[str, str]],
    *,
    event_date: date,
    report_period: str,
) -> dict[str, str]:
    selected: dict[str, tuple[str, str]] = {}
    for accession, meta in submissions.items():
        if meta["report_period"] != report_period:
            continue
        # The flat dataset only gives filing date, not intraday acceptance time.
        # Same-day filings therefore remain excluded.
        if meta["filing_date"] >= event_date.isoformat():
            continue
        manager = meta["manager_cik"]
        candidate = (meta["filing_date"], accession)
        prior = selected.get(manager)
        if prior is None or candidate > prior:
            selected[manager] = candidate
    return {manager: value[1] for manager, value in selected.items()}


def _conservative_filing_available_at(filing_date: str) -> datetime:
    # Treat a filing-date-only record as available at the end of that filing day
    # in New York. This avoids pretending the flat quarterly dataset supplied an
    # intraday timestamp it does not contain.
    local = datetime.combine(
        date.fromisoformat(filing_date),
        time(23, 59, 59),
        tzinfo=NY,
    )
    return local.astimezone(timezone.utc)


def build(
    *,
    targets_path: Path,
    cusip_map_path: Path,
    shares_path: Path,
    submission_path: Path,
    infotable_path: Path,
    output_dir: Path,
) -> dict:
    targets = _load_targets(targets_path)
    mappings = _load_cusip_map(cusip_map_path)
    shares = _load_shares(shares_path)
    submissions = _submission_index(submission_path)
    holdings = _load_holdings(
        infotable_path=infotable_path,
        submissions=submissions,
    )

    report_periods = sorted(
        {meta["report_period"] for meta in submissions.values()}
    )
    rows: list[OwnershipRow] = []
    gaps: list[OwnershipGap] = []

    for target in sorted(
        targets,
        key=lambda row: (str(row["event_date"]), str(row["symbol"])),
    ):
        event_date = target["event_date"]
        symbol = str(target["symbol"])
        cutoff = target["cutoff"]
        assert isinstance(event_date, date)
        assert isinstance(cutoff, datetime)

        cusip = _resolve_cusip(
            mappings, symbol=symbol, event_date=event_date
        )
        if not cusip:
            gaps.append(
                OwnershipGap(
                    event_date=event_date.isoformat(),
                    symbol=symbol,
                    reason="NO_EXACT_HISTORICAL_CUSIP_MAPPING",
                )
            )
            continue

        # Flat quarterly datasets do not provide a reliable intraday acceptance
        # timestamp. Be conservative: only use filings dated strictly before the
        # event date.
        admissible_reports = []
        for report_period in report_periods:
            selected = _selected_accessions_for_target(
                submissions,
                event_date=event_date,
                report_period=report_period,
            )
            selected_accessions = set(selected.values())
            institutional_shares = sum(
                amount
                for (accession, holding_cusip), amount in holdings.items()
                if accession in selected_accessions and holding_cusip == cusip
            )
            if institutional_shares <= 0:
                continue
            latest_filing_date = max(
                submissions[accession]["filing_date"]
                for accession in selected_accessions
            )
            available_at = _conservative_filing_available_at(
                latest_filing_date
            )
            if available_at > cutoff:
                continue
            admissible_reports.append(
                (
                    report_period,
                    available_at,
                    institutional_shares,
                )
            )

        if not admissible_reports:
            gaps.append(
                OwnershipGap(
                    event_date=event_date.isoformat(),
                    symbol=symbol,
                    reason="NO_PRE_EVENT_STRUCTURED_13F_HOLDINGS",
                    cusip=cusip,
                )
            )
            continue

        report_period, filing_available_at, institutional_shares = max(
            admissible_reports,
            key=lambda item: (item[0], item[1]),
        )

        share_candidates = [
            item
            for item in shares.get((event_date.isoformat(), symbol), [])
            if item["available_at"] <= cutoff
        ]
        if not share_candidates:
            gaps.append(
                OwnershipGap(
                    event_date=event_date.isoformat(),
                    symbol=symbol,
                    reason="NO_PRE_CUTOFF_SHARES_OUTSTANDING_DENOMINATOR",
                    cusip=cusip,
                )
            )
            continue
        denominator = max(
            share_candidates, key=lambda item: item["available_at"]
        )
        shares_outstanding = int(denominator["shares"])
        ratio = institutional_shares / shares_outstanding
        if ratio < 0:
            raise G5Sec13FOwnershipError("institutional ownership cannot be negative")

        # Values above 1 can occur from filing/reporting overlap or share-count
        # timing differences. Do not silently clip them into plausible-looking data.
        if ratio > 1.25:
            gaps.append(
                OwnershipGap(
                    event_date=event_date.isoformat(),
                    symbol=symbol,
                    reason="OWNERSHIP_RATIO_IMPLAUSIBLE_GT_1_25",
                    cusip=cusip,
                )
            )
            continue

        effective = filing_available_at
        rows.append(
            OwnershipRow(
                event_date=event_date.isoformat(),
                symbol=symbol,
                effective_ts_utc=effective.isoformat(
                    timespec="seconds"
                ).replace("+00:00", "Z"),
                institutional_ownership=format(ratio, ".15g"),
                institutional_shares=str(institutional_shares),
                shares_outstanding=str(shares_outstanding),
                cusip=cusip,
                report_period=report_period,
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = output_dir / "g5_sec_13f_ownership_source.csv"
    gap_path = output_dir / "g5_sec_13f_ownership_gaps.csv"

    with source_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(OwnershipRow.__dataclass_fields__)
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    with gap_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(OwnershipGap.__dataclass_fields__)
        )
        writer.writeheader()
        for row in gaps:
            writer.writerow(asdict(row))

    summary = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Derive public point-in-time institutional ownership fractions from "
            "SEC structured Form 13F holdings only when exact historical CUSIP "
            "identity and a pre-cutoff shares-outstanding denominator are supplied."
        ),
        "research_use_only": True,
        "target_count": len(targets),
        "resolved_ownership_target_count": len(rows),
        "ownership_gap_target_count": len(gaps),
        "submission_accession_count": len(submissions),
        "holding_report_cusip_count": len(holdings),
        "inputs": {
            "targets": {"path": str(targets_path), "sha256": _sha256(targets_path)},
            "historical_cusip_map": {
                "path": str(cusip_map_path),
                "sha256": _sha256(cusip_map_path),
            },
            "shares": {"path": str(shares_path), "sha256": _sha256(shares_path)},
            "submission": {
                "path": str(submission_path),
                "sha256": _sha256(submission_path),
            },
            "infotable": {
                "path": str(infotable_path),
                "sha256": _sha256(infotable_path),
            },
        },
        "outputs": {
            "ownership_source": str(source_path),
            "gaps": str(gap_path),
        },
        "policy": {
            "exact_historical_cusip_required": True,
            "issuer_name_fuzzy_matching_allowed": False,
            "same_day_13f_filings_allowed": False,
            "put_call_rows_counted_as_common_ownership": False,
            "share_principal_amount_type_required": "SH",
            "latest_pre_event_manager_report_period_filing_only": True,
            "post_event_amendments_cannot_replace_pre_event_filings": True,
            "filing_date_only_records_use_conservative_end_of_day_availability": True,
            "pre_cutoff_shares_outstanding_required": True,
            "ratio_clipping_allowed": False,
            "source_rows_are_canonical_g5_readiness": False,
            "purchase_performed": False,
        },
        "canonical_g5_dates_resolved_change": 0,
        "release_claimed": False,
    }
    (output_dir / "g5_sec_13f_ownership_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build public SEC 13F institutional ownership source for G5."
    )
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--historical-cusip-map", type=Path, required=True)
    parser.add_argument("--shares", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--infotable", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    result = build(
        targets_path=args.targets,
        cusip_map_path=args.historical_cusip_map,
        shares_path=args.shares,
        submission_path=args.submission,
        infotable_path=args.infotable,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
