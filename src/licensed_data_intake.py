from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = "1.0.0"

TEXT_EXTENSIONS = {".csv", ".txt"}
COMPRESSED_TEXT_EXTENSIONS = {".gz"}
RAW_BINARY_EXTENSIONS = {".bin", ".itch"}
DATE_PATTERNS = (
    re.compile(r"(?<!\d)(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2})([01]\d)([0-3]\d)(?!\d)"),
)

CANONICAL_ALIASES = {
    "timestamp": {"timestamp", "datetime", "date_time", "time_stamp", "ts"},
    "date": {"date", "trade_date", "tradedate"},
    "time": {"time", "trade_time", "tradetime"},
    "symbol": {"symbol", "ticker", "stock", "root", "underlying"},
    "underlying_symbol": {"underlying_symbol", "underlying", "root", "underlying_ticker"},
    "option_symbol": {"option_symbol", "optionsymbol", "osi_symbol", "contract_symbol"},
    "expiration": {"expiration", "expiry", "expiration_date", "exp_date"},
    "strike": {"strike", "strike_price"},
    "option_type": {"option_type", "put_call", "call_put", "cp_flag"},
    "price": {"price", "trade_price", "tradeprice", "execution_price"},
    "size": {"size", "trade_size", "volume", "trade_volume", "shares"},
    "bid": {"bid", "bid_price", "best_bid"},
    "ask": {"ask", "ask_price", "best_ask", "offer"},
    "bid_size": {"bid_size", "bidsize", "best_bid_size"},
    "ask_size": {"ask_size", "asksize", "best_ask_size", "offer_size"},
    "exchange": {"exchange", "venue", "market", "exch"},
    "conditions": {"conditions", "condition", "sale_condition", "trade_conditions"},
    "message_type": {"message_type", "messagetype", "type"},
    "order_reference": {"order_reference", "order_ref", "orderreference"},
    "side": {"side", "buy_sell", "bs_indicator"},
    "executed_shares": {"executed_shares", "execution_size", "executed_size"},
    "execution_price": {"execution_price", "executionprice"},
    "match_number": {"match_number", "matchnumber", "match_id"},
    "printable": {"printable"},
    "cancelled_shares": {"cancelled_shares", "canceled_shares", "cancel_size"},
    "new_order_reference": {"new_order_reference", "new_order_ref"},
}

REQUIRED = {
    "equity_trade": {"timestamp_or_date_time", "symbol", "price", "size"},
    "equity_quote": {"timestamp_or_date_time", "symbol", "bid", "ask", "bid_size", "ask_size"},
    "option_trade": {
        "timestamp_or_date_time", "underlying_symbol", "option_symbol",
        "expiration", "strike", "option_type", "price", "size",
    },
    "option_quote": {
        "timestamp_or_date_time", "underlying_symbol", "option_symbol",
        "expiration", "strike", "option_type", "bid", "ask", "bid_size", "ask_size",
    },
    "itch_decoded": {
        "timestamp_or_date_time", "message_type", "symbol", "order_reference",
        "side", "shares", "match_number",
    },
}


@dataclass(frozen=True)
class IntakeFile:
    path: str
    relative_path: str
    size_bytes: int
    sha256: str
    file_kind: str
    readable_header: int
    detected_trade_date: str
    candidate_record_kind: str
    candidate_source_family: str
    candidate_format_version: str
    confidence: str
    status: str
    reason: str
    header_fields: str
    proposed_column_map: str
    research_use_only: int = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _detect_date(name: str) -> str:
    for pattern in DATE_PATTERNS:
        m = pattern.search(name)
        if not m:
            continue
        y, mo, d = m.groups()
        try:
            from datetime import date
            return date(int(y), int(mo), int(d)).isoformat()
        except ValueError:
            continue
    return ""


def _open_header(path: Path) -> tuple[list[str], str]:
    """Read only enough bytes for a delimited header; never parse whole vendor files."""
    suffixes = [s.lower() for s in path.suffixes]
    opener = gzip.open if suffixes and suffixes[-1] == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8-sig", errors="strict", newline="") as f:
            first = f.readline(256 * 1024)
    except (UnicodeDecodeError, OSError, EOFError):
        return [], ""
    if not first or "\x00" in first:
        return [], ""
    candidates = [",", "|", "\t", ";"]
    delimiter = max(candidates, key=lambda d: first.count(d))
    if first.count(delimiter) == 0:
        return [], ""
    try:
        row = next(csv.reader([first], delimiter=delimiter))
    except Exception:
        return [], ""
    fields = [x.strip() for x in row if x.strip()]
    return fields, delimiter


def _canonical_map(fields: list[str]) -> dict[str, str]:
    normalized = {_normalize(x): x for x in fields}
    out: dict[str, str] = {}
    for canonical, aliases in CANONICAL_ALIASES.items():
        for alias in aliases:
            key = _normalize(alias)
            if key in normalized:
                out[canonical] = normalized[key]
                break
    # "shares" is a canonical ITCH field but also a common trade-size alias.
    if "shares" not in out and "shares" in normalized:
        out["shares"] = normalized["shares"]
    return out


def _timestamp_ok(mapping: dict[str, str]) -> bool:
    return "timestamp" in mapping or ("date" in mapping and "time" in mapping)


def _coverage_set(mapping: dict[str, str]) -> set[str]:
    keys = set(mapping)
    if _timestamp_ok(mapping):
        keys.add("timestamp_or_date_time")
    return keys


def _family_for(kind: str, filename: str, version: str) -> str:
    low = filename.lower()
    if kind in {"equity_trade", "equity_quote"}:
        return "nyse_daily_taq" if any(x in low for x in ("taq", "ct", "cq", "trade", "quote")) else "generic_authorized_market_data"
    if kind == "option_trade":
        return "cboe_option_trades" if any(x in low for x in ("cboe", "option", "opra")) else "generic_authorized_market_data"
    if kind == "option_quote":
        return "cboe_option_quotes" if any(x in low for x in ("cboe", "option", "opra")) else "generic_authorized_market_data"
    if kind == "itch_decoded":
        return "nasdaq_itch_4_1_decoded" if version == "ITCH-4.1" else "nasdaq_itch_5_0_decoded"
    return "generic_authorized_market_data"


def _itch_version(path: Path, trade_date: str) -> str:
    low = path.name.lower()
    if any(x in low for x in ("4.1", "41", "itch41", "itch_41")):
        return "ITCH-4.1"
    if any(x in low for x in ("5.0", "50", "itch50", "itch_50")):
        return "ITCH-5.0"
    if trade_date:
        return "ITCH-4.1" if trade_date < "2014-04-08" else "ITCH-5.0"
    return ""


def _classify_text(path: Path, fields: list[str]) -> tuple[str, str, str, str, str, dict[str, str]]:
    mapping = _canonical_map(fields)
    coverage = _coverage_set(mapping)
    scored: list[tuple[int, int, str]] = []
    for kind, required in REQUIRED.items():
        missing = required - coverage
        scored.append((len(required) - len(missing), len(required), kind))
    scored.sort(reverse=True)
    best_hits, best_total, best_kind = scored[0]
    complete = REQUIRED[best_kind].issubset(coverage)

    # Prefer quote over trade when quote fields are fully present, and option over
    # equity when option identifiers are fully present.
    priority = ["option_quote", "option_trade", "equity_quote", "equity_trade", "itch_decoded"]
    completes = [k for k in priority if REQUIRED[k].issubset(coverage)]
    if completes:
        best_kind = completes[0]
        complete = True

    trade_date = _detect_date(path.name)
    version = _itch_version(path, trade_date) if best_kind == "itch_decoded" else ""
    family = _family_for(best_kind, path.name, version)
    if complete:
        confidence = "high"
        status = "PENDING_AUTHORIZATION_AND_REVIEW"
        reason = "header contains all canonical fields required for candidate record kind"
    elif best_hits >= max(3, best_total - 2):
        confidence = "medium"
        status = "PENDING_SCHEMA_MAPPING"
        missing = sorted(REQUIRED[best_kind] - coverage)
        reason = "candidate header is close but incomplete; missing=" + ",".join(missing)
    else:
        confidence = "low"
        status = "UNCLASSIFIED"
        reason = "header does not safely identify a supported market-data record kind"
        best_kind = ""
        family = ""
        version = ""
    return best_kind, family, version, confidence, status + "|" + reason, mapping


def inspect_file(path: Path, root: Path) -> IntakeFile:
    rel = str(path.relative_to(root))
    trade_date = _detect_date(path.name)
    fields, _delimiter = _open_header(path)
    suffixes = [s.lower() for s in path.suffixes]

    if fields:
        kind, family, version, confidence, packed, mapping = _classify_text(path, fields)
        status, reason = packed.split("|", 1)
        file_kind = "delimited_text"
        return IntakeFile(
            str(path), rel, path.stat().st_size, _sha256(path), file_kind, 1,
            trade_date, kind, family, version, confidence, status, reason,
            ";".join(fields), json.dumps(mapping, sort_keys=True),
        )

    # Raw ITCH is deliberately inventory-only. Decoding is a separate authorized step.
    low = path.name.lower()
    binary_like = any(s in RAW_BINARY_EXTENSIONS for s in suffixes) or "itch" in low
    if binary_like:
        version = _itch_version(path, trade_date)
        family = "nasdaq_itch_4_1_decoded" if version == "ITCH-4.1" else (
            "nasdaq_itch_5_0_decoded" if version == "ITCH-5.0" else ""
        )
        return IntakeFile(
            str(path), rel, path.stat().st_size, _sha256(path), "raw_binary", 0,
            trade_date, "itch_raw_binary", family, version, "medium",
            "REQUIRES_AUTHORIZED_DECODER",
            "binary/raw ITCH is never passed directly to the canonical importer",
            "", "{}",
        )

    return IntakeFile(
        str(path), rel, path.stat().st_size, _sha256(path), "unknown", 0,
        trade_date, "", "", "", "low", "UNCLASSIFIED",
        "file could not be safely classified from header or filename", "", "{}",
    )


def scan(input_dir: Path, output_dir: Path, *, license_reference: str = "") -> dict:
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"input directory not found: {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    ignored_names = {"desktop.ini", "thumbs.db"}
    files = [
        p for p in input_dir.rglob("*")
        if p.is_file() and p.name.lower() not in ignored_names
    ]
    rows = [inspect_file(p, input_dir) for p in sorted(files)]

    csv_path = output_dir / "intake_files.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        names = list(asdict(rows[0]).keys()) if rows else [
            "path", "relative_path", "size_bytes", "sha256", "file_kind",
            "readable_header", "detected_trade_date", "candidate_record_kind",
            "candidate_source_family", "candidate_format_version", "confidence",
            "status", "reason", "header_fields", "proposed_column_map",
            "research_use_only",
        ]
        w = csv.DictWriter(f, fieldnames=names)
        w.writeheader()
        for row in rows:
            w.writerow(asdict(row))

    contract_candidates = []
    for row in rows:
        if row.status != "PENDING_AUTHORIZATION_AND_REVIEW":
            continue
        mapping = json.loads(row.proposed_column_map)
        contract_candidates.append({
            "source_id": "PENDING-" + row.sha256[:12],
            "source_family": row.candidate_source_family,
            "record_kind": row.candidate_record_kind,
            "path": row.path,
            # Intentionally false. Human/operator review or a separate trusted
            # entitlement process must make the authorization assertion.
            "authorized": False,
            "data_classification": "authorized_historical_market_data",
            "license_reference": license_reference,
            "trade_date": row.detected_trade_date,
            "timezone": "America/New_York",
            "delimiter": "AUTO_DETECTED_PENDING_REVIEW",
            "encoding": "utf-8",
            "format_version": row.candidate_format_version or "PENDING_REVIEW",
            "column_map": mapping,
            "notes": "Generated by licensed-data intake scanner; not executable until reviewed.",
        })

    pending_contract = {
        "schema_version": "1",
        "purpose": (
            "NON-EXECUTABLE draft generated from local licensed-data intake. "
            "Authorization remains false until reviewed."
        ),
        "sources": contract_candidates,
    }
    (output_dir / "market_contract.pending.json").write_text(
        json.dumps(pending_contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    kind_counts: dict[str, int] = {}
    for row in rows:
        if row.candidate_record_kind:
            kind_counts[row.candidate_record_kind] = kind_counts.get(row.candidate_record_kind, 0) + 1

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "purpose": (
            "Local, read-only intake inventory for lawfully obtained historical market data. "
            "This tool never downloads data, reads credentials, or asserts authorization."
        ),
        "research_use_only": True,
        "input_dir": str(input_dir),
        "file_count": len(rows),
        "total_bytes": sum(r.size_bytes for r in rows),
        "status_counts": dict(sorted(counts.items())),
        "candidate_record_kind_counts": dict(sorted(kind_counts.items())),
        "high_confidence_contract_candidates": len(contract_candidates),
        "license_reference_supplied": bool(license_reference.strip()),
        "authorization_policy": {
            "generated_contract_authorized_value": False,
            "authorization_must_be_reviewed_separately": True,
            "schema_guessing_never_unlocks_replay": True,
            "raw_itch_requires_authorized_decoder": True,
        },
        "outputs": {
            "file_inventory": str(csv_path),
            "pending_market_contract": str(output_dir / "market_contract.pending.json"),
        },
    }
    (output_dir / "intake_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description="Inventory a local licensed-data drop without asserting authorization.")
    p.add_argument("--input-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--license-reference", default="")
    args = p.parse_args()
    print(json.dumps(scan(args.input_dir, args.output_dir, license_reference=args.license_reference), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
