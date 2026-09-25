from __future__ import annotations

import json
from pathlib import Path

from . import registry
from .storage import sha256_file


def _snapshot_exists(root: Path, digest: str) -> bool:
    directory = Path(root) / digest
    if not directory.exists():
        return False
    for candidate in directory.glob("original*"):
        if candidate.is_file() and not candidate.is_symlink() and sha256_file(candidate) == digest:
            return True
    return False


def _publicity_clearance_exists(control_dir: Path, digest: str) -> bool:
    root = Path(control_dir) / "publicity_clearances" / digest
    claim = root / "clearance.json"
    signature = root / "clearance.json.sig"
    return (
        claim.is_file()
        and not claim.is_symlink()
        and sha256_file(claim) == digest
        and signature.is_file()
        and not signature.is_symlink()
        and signature.stat().st_size > 0
    )


def _active_contract_issues(db_path: Path, contract: Path) -> list[str]:
    if not contract.exists(): return []
    raw=json.loads(contract.read_text(encoding="utf-8")); issues=[]
    with registry.connect(db_path) as con:
        for source in raw.get("sources",[]):
            source_id=str(source.get("source_id","")); p=Path(str(source.get("path","")))
            if not p.exists() or not p.is_file(): issues.append(f"{source_id}: active source path missing"); continue
            digest=sha256_file(p)
            rows=con.execute("SELECT information_id FROM information_object WHERE source_id=? AND content_sha256=?",(source_id,digest)).fetchall()
            if not rows: issues.append(f"{source_id}: active source lacks control-plane identity"); continue
            if not any(registry.current_state(db_path,str(r["information_id"]))=="ADMITTED_STRUCTURED" for r in rows):
                issues.append(f"{source_id}: active source is not ADMITTED_STRUCTURED")
    return issues


def verify_control_plane(db_path: Path, control_dir: Path, active_contracts: list[Path] | None = None) -> dict:
    db_path=Path(db_path); control_dir=Path(control_dir)
    report={"sqlite_integrity":False,"foreign_keys_clean":False,"event_chains_valid":False,"holding_hashes_valid":False,
            "quarantine_hashes_valid":False,"publicity_clearance_artifacts_valid":False,"active_contract_issues":[],"information_object_count":0,"ok":False}
    if not db_path.exists(): report["error"]="control database missing"; return report
    try:
        with registry.connect(db_path) as con:
            integrity=[str(r[0]) for r in con.execute("PRAGMA integrity_check").fetchall()]; fk=con.execute("PRAGMA foreign_key_check").fetchall()
            objects=[dict(r) for r in con.execute("SELECT * FROM information_object ORDER BY information_id").fetchall()]
        report["sqlite_integrity"]=integrity==["ok"]; report["foreign_keys_clean"]=len(fk)==0; report["information_object_count"]=len(objects)
        report["event_chains_valid"]=all(registry.verify_event_chain(db_path,x["information_id"]) for x in objects)
        holding_ok=True; quarantine_ok=True; publicity_ok=True
        for obj in objects:
            state=registry.current_state(db_path,obj["information_id"])
            if not _snapshot_exists(control_dir/"holding", obj["content_sha256"]):
                holding_ok=False
            if state=="QUARANTINED":
                if not _snapshot_exists(control_dir/"quarantine", obj["content_sha256"]):
                    quarantine_ok=False
            if state=="PUBLICITY_CLEARED":
                detail=registry.latest_event_detail(db_path,obj["information_id"])
                digest=str(detail.get("clearance_sha256",""))
                if not digest or not _publicity_clearance_exists(control_dir,digest):
                    publicity_ok=False
                if detail.get("clearance_signature_verified") is not True:
                    publicity_ok=False
        report["holding_hashes_valid"]=holding_ok; report["quarantine_hashes_valid"]=quarantine_ok; report["publicity_clearance_artifacts_valid"]=publicity_ok
        issues=[]
        for contract in active_contracts or []: issues.extend(_active_contract_issues(db_path,Path(contract)))
        report["active_contract_issues"]=issues
        report["ok"]=bool(report["sqlite_integrity"] and report["foreign_keys_clean"] and report["event_chains_valid"] and holding_ok and quarantine_ok and publicity_ok and not issues)
    except Exception as exc: report["error"]=f"{type(exc).__name__}: {exc}"
    return report
