from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .contracts import INFORMATION_STATES


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _information_id(domain: str, source_id: str, content_sha256: str) -> str:
    return "info_" + hashlib.sha256(f"{domain}\0{source_id}\0{content_sha256}".encode("utf-8")).hexdigest()


def init_db(db_path: Path) -> Path:
    db_path = Path(db_path); db_path.parent.mkdir(parents=True, exist_ok=True)
    try: db_path.parent.chmod(0o700)
    except OSError: pass
    with sqlite3.connect(db_path) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS information_object (
            information_id TEXT PRIMARY KEY, domain TEXT NOT NULL, source_id TEXT NOT NULL,
            content_sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
            received_at_utc TEXT NOT NULL, source_contract_sha256 TEXT NOT NULL,
            data_classification TEXT NOT NULL, record_kind TEXT NOT NULL, source_family TEXT NOT NULL,
            research_use_only INTEGER NOT NULL CHECK(research_use_only = 1),
            UNIQUE(domain, source_id, content_sha256)
        );
        CREATE TABLE IF NOT EXISTS information_event (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            information_id TEXT NOT NULL REFERENCES information_object(information_id),
            sequence INTEGER NOT NULL, event_type TEXT NOT NULL, state_after TEXT NOT NULL,
            occurred_at_utc TEXT NOT NULL, detail_json TEXT NOT NULL,
            previous_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE,
            UNIQUE(information_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS information_location (
            location_id INTEGER PRIMARY KEY AUTOINCREMENT,
            information_id TEXT NOT NULL REFERENCES information_object(information_id),
            location_class TEXT NOT NULL, path_fingerprint TEXT NOT NULL,
            content_sha256 TEXT NOT NULL, observed_at_utc TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS information_object_no_update BEFORE UPDATE ON information_object BEGIN SELECT RAISE(ABORT, 'information_object is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS information_object_no_delete BEFORE DELETE ON information_object BEGIN SELECT RAISE(ABORT, 'information_object is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS information_event_no_update BEFORE UPDATE ON information_event BEGIN SELECT RAISE(ABORT, 'information_event is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS information_event_no_delete BEFORE DELETE ON information_event BEGIN SELECT RAISE(ABORT, 'information_event is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS information_location_no_update BEFORE UPDATE ON information_location BEGIN SELECT RAISE(ABORT, 'information_location is append-only'); END;
        CREATE TRIGGER IF NOT EXISTS information_location_no_delete BEFORE DELETE ON information_location BEGIN SELECT RAISE(ABORT, 'information_location is append-only'); END;
        """)
    try: db_path.chmod(0o600)
    except OSError: pass
    return db_path


def connect(db_path: Path) -> sqlite3.Connection:
    init_db(db_path); con = sqlite3.connect(db_path); con.row_factory = sqlite3.Row; con.execute("PRAGMA foreign_keys=ON"); return con


def register_information(db_path: Path, *, domain: str, source_id: str, content_sha256: str, size_bytes: int,
                         source_contract_sha256: str, data_classification: str, record_kind: str, source_family: str) -> dict:
    info_id = _information_id(domain, source_id, content_sha256); received = utc_now()
    with connect(db_path) as con:
        existing = con.execute("SELECT * FROM information_object WHERE information_id=?", (info_id,)).fetchone()
        if existing is not None:
            immutable = {"domain":domain,"source_id":source_id,"content_sha256":content_sha256,"size_bytes":int(size_bytes),
                         "source_contract_sha256":source_contract_sha256,"data_classification":data_classification,
                         "record_kind":record_kind,"source_family":source_family}
            for key, expected in immutable.items():
                if existing[key] != expected: raise ValueError(f"information identity collision/mismatch for {key}")
            return {"information_id":info_id,"received_at_utc":existing["received_at_utc"],"created":False}
        con.execute("""INSERT INTO information_object(
            information_id,domain,source_id,content_sha256,size_bytes,received_at_utc,source_contract_sha256,
            data_classification,record_kind,source_family,research_use_only) VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
            (info_id,domain,source_id,content_sha256,int(size_bytes),received,source_contract_sha256,data_classification,record_kind,source_family))
    return {"information_id":info_id,"received_at_utc":received,"created":True}


def append_event(db_path: Path, information_id: str, event_type: str, state_after: str, detail: dict | None = None) -> dict:
    if state_after not in INFORMATION_STATES: raise ValueError(f"unsupported state_after={state_after!r}")
    with connect(db_path) as con:
        prior=con.execute("SELECT sequence,event_hash FROM information_event WHERE information_id=? ORDER BY sequence DESC LIMIT 1",(information_id,)).fetchone()
        sequence=(int(prior["sequence"])+1) if prior else 1; previous=str(prior["event_hash"]) if prior else "GENESIS"; occurred=utc_now()
        detail_json=json.dumps(detail or {},sort_keys=True,separators=(",",":"))
        payload={"information_id":information_id,"sequence":sequence,"event_type":event_type,"state_after":state_after,
                 "occurred_at_utc":occurred,"detail_json":detail_json,"previous_event_hash":previous}
        event_hash=hashlib.sha256(_canonical(payload)).hexdigest()
        con.execute("""INSERT INTO information_event(information_id,sequence,event_type,state_after,occurred_at_utc,detail_json,previous_event_hash,event_hash)
                       VALUES (?,?,?,?,?,?,?,?)""",(information_id,sequence,event_type,state_after,occurred,detail_json,previous,event_hash))
    return payload|{"event_hash":event_hash}


def add_location(db_path: Path, information_id: str, location_class: str, path_fingerprint: str, content_sha256: str) -> None:
    with connect(db_path) as con:
        con.execute("INSERT INTO information_location(information_id,location_class,path_fingerprint,content_sha256,observed_at_utc) VALUES (?,?,?,?,?)",
                    (information_id,location_class,path_fingerprint,content_sha256,utc_now()))


def current_state(db_path: Path, information_id: str) -> str:
    with connect(db_path) as con:
        row=con.execute("SELECT state_after FROM information_event WHERE information_id=? ORDER BY sequence DESC LIMIT 1",(information_id,)).fetchone()
    return str(row["state_after"]) if row else ""


def event_head(db_path: Path, information_id: str) -> str:
    with connect(db_path) as con:
        row=con.execute("SELECT event_hash FROM information_event WHERE information_id=? ORDER BY sequence DESC LIMIT 1",(information_id,)).fetchone()
    return str(row["event_hash"]) if row else ""


def verify_event_chain(db_path: Path, information_id: str) -> bool:
    with connect(db_path) as con:
        rows=con.execute("SELECT * FROM information_event WHERE information_id=? ORDER BY sequence",(information_id,)).fetchall()
    previous="GENESIS"
    for expected_sequence,row in enumerate(rows,1):
        if int(row["sequence"])!=expected_sequence or row["previous_event_hash"]!=previous: return False
        payload={"information_id":row["information_id"],"sequence":int(row["sequence"]),"event_type":row["event_type"],"state_after":row["state_after"],
                 "occurred_at_utc":row["occurred_at_utc"],"detail_json":row["detail_json"],"previous_event_hash":row["previous_event_hash"]}
        if hashlib.sha256(_canonical(payload)).hexdigest()!=row["event_hash"]: return False
        previous=row["event_hash"]
    return bool(rows)
