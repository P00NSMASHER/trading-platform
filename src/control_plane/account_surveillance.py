from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import case_evidence

from . import storage

SCHEMA_VERSION = "1"
ACCOUNT_NOTICE = (
    "Account-level surveillance aggregation is research triage only. "
    "It is not a finding that an account, person, or firm committed misconduct."
)
REQUIRED_COLUMNS = {"account_key", "case_id", "research_use_only"}
PROHIBITED_INPUT_COLUMNS = {
    "name", "full_name", "first_name", "last_name", "email", "phone", "address", "ssn",
    "tax_id", "date_of_birth", "dob", "password", "credential", "api_key", "access_token",
    "buy", "sell", "trade_direction", "expected_return", "target_price", "position_size",
    "order", "order_instruction",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash_obj(obj: object) -> str:
    return hashlib.sha256(_canonical(obj)).hexdigest()


def _research_only(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true"}


def _subject_id(account_key: str) -> str:
    key = str(account_key or "").strip()
    if not key:
        raise ValueError("account_key is required")
    return "acct_" + hashlib.sha256(("account-subject\0" + key).encode("utf-8")).hexdigest()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise ValueError(f"account surveillance database does not exist: {db_path}")
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(db_path: Path) -> Path:
    db_path = Path(db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        db_path.parent.chmod(0o700)
    except OSError:
        pass
    with connect(db_path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS account_subject (
                subject_id TEXT PRIMARY KEY,
                created_at_utc TEXT NOT NULL,
                identity_redacted INTEGER NOT NULL CHECK(identity_redacted=1),
                research_use_only INTEGER NOT NULL CHECK(research_use_only=1)
            );
            CREATE TABLE IF NOT EXISTS account_case_link (
                link_id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id TEXT NOT NULL REFERENCES account_subject(subject_id),
                case_id TEXT NOT NULL,
                case_record_sha256 TEXT NOT NULL,
                source_file_sha256 TEXT NOT NULL,
                source_path_fingerprint TEXT NOT NULL,
                linked_at_utc TEXT NOT NULL,
                research_use_only INTEGER NOT NULL CHECK(research_use_only=1),
                UNIQUE(subject_id, case_id)
            );
            CREATE INDEX IF NOT EXISTS idx_account_case_subject
                ON account_case_link(subject_id, link_id);
            CREATE INDEX IF NOT EXISTS idx_account_case_case
                ON account_case_link(case_id, link_id);
            CREATE TRIGGER IF NOT EXISTS account_subject_no_update
                BEFORE UPDATE ON account_subject BEGIN SELECT RAISE(ABORT, 'account_subject is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS account_subject_no_delete
                BEFORE DELETE ON account_subject BEGIN SELECT RAISE(ABORT, 'account_subject is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS account_case_link_no_update
                BEFORE UPDATE ON account_case_link BEGIN SELECT RAISE(ABORT, 'account_case_link is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS account_case_link_no_delete
                BEFORE DELETE ON account_case_link BEGIN SELECT RAISE(ABORT, 'account_case_link is immutable'); END;
            """
        )
    try:
        db_path.chmod(0o600)
    except OSError:
        pass
    return db_path


def _case_snapshot(case_db: Path, case_id: str) -> dict[str, Any]:
    case_db = Path(case_db).resolve()
    with case_evidence.connect(case_db) as con:
        row = con.execute("SELECT * FROM case_record WHERE case_id=?", (case_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown case_id={case_id!r}")
        case = dict(row)
        sources = [
            dict(r)
            for r in con.execute(
                "SELECT artifact_role,sha256,size_bytes FROM source_artifact "
                "WHERE case_id=? ORDER BY artifact_role,source_id",
                (case_id,),
            ).fetchall()
        ]
    if int(case.get("research_use_only", 0)) != 1:
        raise ValueError("account surveillance requires research-only case evidence")
    if not case_evidence.verify_review_chain(case_db, case_id):
        raise ValueError(f"case review chain is invalid: {case_id}")
    model_sources = [x for x in sources if x["artifact_role"] == "model_bundle"]
    if not model_sources or any(x["sha256"] != case["model_sha256"] for x in model_sources):
        raise ValueError(f"case model provenance is inconsistent: {case_id}")
    snapshot = {
        "case_id": str(case["case_id"]),
        "event_id": str(case["event_id"]),
        "symbol": str(case["symbol"]),
        "minute_ts_utc": str(case["minute_ts_utc"]),
        "surveillance_risk_score": float(case["surveillance_risk_score"]),
        "surveillance_threshold": float(case["surveillance_threshold"]),
        "flagged": int(case["flagged"]),
        "model_sha256": str(case["model_sha256"]),
        "created_at_utc": str(case["created_at_utc"]),
        "research_use_only": 1,
        "source_hashes": sources,
    }
    snapshot["case_record_sha256"] = _hash_obj(snapshot)
    return snapshot


def ingest_links(*, mapping_csv: Path, case_db: Path, account_db: Path) -> dict:
    mapping_csv = Path(mapping_csv).resolve()
    case_db = Path(case_db).resolve()
    account_db = init_db(account_db)
    if not mapping_csv.is_file() or mapping_csv.is_symlink():
        raise ValueError("account mapping must be a regular local file")

    with mapping_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = [str(x or "").strip() for x in (reader.fieldnames or [])]
        normalized = {x.lower() for x in fields}
        prohibited = sorted(normalized & PROHIBITED_INPUT_COLUMNS)
        if prohibited:
            raise ValueError(f"account mapping contains prohibited identity/trading columns: {prohibited}")
        if set(fields) != REQUIRED_COLUMNS or len(fields) != len(REQUIRED_COLUMNS):
            raise ValueError(
                "account mapping columns must be exactly account_key, case_id, research_use_only"
            )
        rows = list(reader)

    source_sha = storage.sha256_file(mapping_csv)
    source_path_fingerprint = storage.path_fingerprint(mapping_csv)
    inserted = 0
    no_op = 0
    subject_ids: set[str] = set()

    with connect(account_db) as con:
        for row_no, row in enumerate(rows, 2):
            if not _research_only(row.get("research_use_only")):
                raise ValueError(f"row {row_no}: research_use_only must be true")
            subject_id = _subject_id(str(row.get("account_key", "")))
            case_id = str(row.get("case_id", "")).strip()
            if not case_id:
                raise ValueError(f"row {row_no}: case_id is required")
            snapshot = _case_snapshot(case_db, case_id)
            subject_ids.add(subject_id)
            now = utc_now()

            existing_subject = con.execute(
                "SELECT * FROM account_subject WHERE subject_id=?", (subject_id,)
            ).fetchone()
            if existing_subject is None:
                con.execute(
                    "INSERT INTO account_subject(subject_id,created_at_utc,identity_redacted,research_use_only) "
                    "VALUES (?,?,1,1)",
                    (subject_id, now),
                )

            existing = con.execute(
                "SELECT * FROM account_case_link WHERE subject_id=? AND case_id=?",
                (subject_id, case_id),
            ).fetchone()
            if existing is not None:
                if str(existing["case_record_sha256"]) != snapshot["case_record_sha256"]:
                    raise ValueError("existing account-case link is bound to different case evidence")
                no_op += 1
                continue

            con.execute(
                """INSERT INTO account_case_link(
                    subject_id,case_id,case_record_sha256,source_file_sha256,
                    source_path_fingerprint,linked_at_utc,research_use_only
                ) VALUES (?,?,?,?,?,?,1)""",
                (
                    subject_id,
                    case_id,
                    snapshot["case_record_sha256"],
                    source_sha,
                    source_path_fingerprint,
                    now,
                ),
            )
            inserted += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "mapping_sha256": source_sha,
        "source_path_fingerprint": source_path_fingerprint,
        "input_row_count": len(rows),
        "inserted_link_count": inserted,
        "no_op_link_count": no_op,
        "subject_count_in_batch": len(subject_ids),
        "raw_account_keys_persisted": False,
        "identity_redacted": True,
        "research_use_only": True,
        "notice": ACCOUNT_NOTICE,
    }


def _current_disposition(case_db: Path, case_id: str) -> str:
    with case_evidence.connect(case_db) as con:
        review = con.execute(
            "SELECT disposition FROM review_history WHERE case_id=? ORDER BY review_id DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        if review is not None:
            return str(review["disposition"])
        case = con.execute(
            "SELECT initial_status FROM case_record WHERE case_id=?", (case_id,)
        ).fetchone()
    if case is None:
        raise ValueError(f"linked case missing from case database: {case_id}")
    return str(case["initial_status"])


def _link_integrity(case_db: Path, row: dict) -> tuple[bool, dict]:
    try:
        snapshot = _case_snapshot(case_db, str(row["case_id"]))
    except Exception as exc:
        return False, {"error": f"{type(exc).__name__}: {exc}"}
    ok = snapshot["case_record_sha256"] == str(row["case_record_sha256"])
    return ok, snapshot


def list_accounts(*, account_db: Path, case_db: Path, limit: int = 500) -> list[dict]:
    account_db = Path(account_db).resolve()
    case_db = Path(case_db).resolve()
    with connect_readonly(account_db) as con:
        subjects = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM account_subject ORDER BY subject_id LIMIT ?",
                (int(limit),),
            ).fetchall()
        ]
        links = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM account_case_link ORDER BY subject_id,link_id"
            ).fetchall()
        ]
    by_subject: dict[str, list[dict]] = {}
    for row in links:
        by_subject.setdefault(str(row["subject_id"]), []).append(row)

    out: list[dict] = []
    for subject in subjects:
        subject_id = str(subject["subject_id"])
        cases: list[dict] = []
        integrity_ok = True
        for link in by_subject.get(subject_id, []):
            ok, snap = _link_integrity(case_db, link)
            integrity_ok = integrity_ok and ok
            if not ok:
                continue
            cases.append(snap | {"current_disposition": _current_disposition(case_db, snap["case_id"])})
        scores = [float(x["surveillance_risk_score"]) for x in cases]
        symbols = {str(x["symbol"]) for x in cases}
        out.append(
            {
                "subject_id": subject_id,
                "linked_case_count": len(cases),
                "flagged_case_count": sum(int(x["flagged"]) for x in cases),
                "distinct_symbol_count": len(symbols),
                "max_surveillance_risk_score": max(scores) if scores else 0.0,
                "latest_case_ts_utc": max((str(x["minute_ts_utc"]) for x in cases), default=""),
                "integrity_ok": integrity_ok,
                "identity_redacted": True,
                "research_use_only": True,
            }
        )
    out.sort(
        key=lambda x: (
            int(x["flagged_case_count"]),
            float(x["max_surveillance_risk_score"]),
            int(x["linked_case_count"]),
            str(x["subject_id"]),
        ),
        reverse=True,
    )
    return out


def account_detail(*, account_db: Path, case_db: Path, subject_id: str) -> dict:
    account_db = Path(account_db).resolve()
    case_db = Path(case_db).resolve()
    subject_id = str(subject_id or "").strip()
    with connect_readonly(account_db) as con:
        subject = con.execute(
            "SELECT * FROM account_subject WHERE subject_id=?", (subject_id,)
        ).fetchone()
        if subject is None:
            raise KeyError(subject_id)
        links = [
            dict(r)
            for r in con.execute(
                "SELECT * FROM account_case_link WHERE subject_id=? ORDER BY link_id",
                (subject_id,),
            ).fetchall()
        ]
    cases = []
    integrity_ok = True
    for link in links:
        ok, snap = _link_integrity(case_db, link)
        integrity_ok = integrity_ok and ok
        row = {
            "case_id": str(link["case_id"]),
            "case_record_sha256": str(link["case_record_sha256"]),
            "link_integrity_ok": ok,
        }
        if ok:
            row.update(
                {
                    "event_id": snap["event_id"],
                    "symbol": snap["symbol"],
                    "minute_ts_utc": snap["minute_ts_utc"],
                    "surveillance_risk_score": snap["surveillance_risk_score"],
                    "flagged": snap["flagged"],
                    "model_sha256": snap["model_sha256"],
                    "current_disposition": _current_disposition(case_db, snap["case_id"]),
                }
            )
        cases.append(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "subject_id": subject_id,
        "identity_redacted": True,
        "linked_cases": cases,
        "integrity_ok": integrity_ok,
        "research_use_only": True,
        "notice": ACCOUNT_NOTICE,
    }


def verify_account_surveillance(*, account_db: Path, case_db: Path) -> dict:
    account_db = Path(account_db).resolve()
    case_db = Path(case_db).resolve()
    with connect_readonly(account_db) as con:
        sqlite_ok = [str(r[0]) for r in con.execute("PRAGMA integrity_check").fetchall()] == ["ok"]
        fk_clean = len(con.execute("PRAGMA foreign_key_check").fetchall()) == 0
        subjects = int(con.execute("SELECT COUNT(*) FROM account_subject").fetchone()[0])
        links = [dict(r) for r in con.execute("SELECT * FROM account_case_link ORDER BY link_id").fetchall()]
    link_errors = []
    for row in links:
        ok, _ = _link_integrity(case_db, row)
        if not ok:
            link_errors.append({"subject_id": row["subject_id"], "case_id": row["case_id"]})
    return {
        "schema_version": SCHEMA_VERSION,
        "sqlite_integrity": sqlite_ok,
        "foreign_keys_clean": fk_clean,
        "subject_count": subjects,
        "link_count": len(links),
        "case_link_errors": link_errors,
        "raw_account_keys_persisted": False,
        "identity_redacted": True,
        "research_use_only": True,
        "ok": bool(sqlite_ok and fk_clean and not link_errors),
    }
