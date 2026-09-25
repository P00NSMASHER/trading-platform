from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import registry, signature_trust, storage

SCHEMA_VERSION="1"
NAMESPACE="mnpi-publicity-clearance"
DEFAULT_NAMESPACE=NAMESPACE


def _utc(value: str) -> str:
    text=str(value or "").strip()
    if not text: raise ValueError("public_release_timestamp_utc is required")
    try: parsed=datetime.fromisoformat(text[:-1]+"+00:00" if text.endswith("Z") else text)
    except ValueError as exc: raise ValueError("public_release_timestamp_utc must be ISO-8601") from exc
    if parsed.tzinfo is None: raise ValueError("public_release_timestamp_utc must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")


def _holding(control_dir: Path, digest: str) -> Path:
    digest=signature_trust.validated_sha256(digest,label="holding_sha256")
    candidates=[p for p in (Path(control_dir).resolve()/"holding"/digest).glob("original*") if p.is_file() and not p.is_symlink()]
    valid=[p for p in candidates if storage.sha256_file(p)==digest]
    if len(valid)!=1: raise ValueError("exactly one hash-valid HOLDING snapshot is required")
    return valid[0]


def _validate(claim: dict[str,Any]) -> None:
    required=("information_id","source_id","content_sha256","holding_sha256","public_release_reference","public_release_timestamp_utc","public_release_evidence_sha256","preclearance_event_head")
    if claim.get("schema_version")!=SCHEMA_VERSION or claim.get("clearance_type")!="unstructured_publicity_clearance": raise ValueError("unsupported publicity clearance schema/type")
    if claim.get("signature_namespace")!=NAMESPACE: raise ValueError(f"signature_namespace must equal {NAMESPACE!r}")
    if claim.get("publicity_status")!="PUBLIC" or claim.get("decision_scope")!="publicity_only": raise ValueError("clearance must be PUBLIC and publicity_only")
    if claim.get("research_use_only") is not True or claim.get("model_plane_eligible") is not False: raise ValueError("clearance must remain research-only and model-ineligible")
    for key in required:
        if not str(claim.get(key,"")).strip(): raise ValueError(f"publicity clearance requires {key}")
    for key in ("content_sha256","holding_sha256","public_release_evidence_sha256"):
        signature_trust.validated_sha256(str(claim[key]),label=key)
    _utc(str(claim["public_release_timestamp_utc"]))


def build_clearance(*, control_dir: Path, information_id: str, public_release_evidence: Path,
                    public_release_reference: str, public_release_timestamp_utc: str) -> dict[str,Any]:
    control_dir=Path(control_dir).resolve(); db=control_dir/"control.sqlite"; info=registry.get_information(db,information_id)
    if info["domain"]!="unstructured" or registry.current_state(db,information_id)!="PUBLICITY_PENDING": raise ValueError("information object is not an unstructured PUBLICITY_PENDING object")
    evidence=Path(public_release_evidence).resolve()
    if not evidence.is_file(): raise FileNotFoundError(evidence)
    _holding(control_dir,str(info["content_sha256"])); reference=str(public_release_reference or "").strip()
    if not reference: raise ValueError("public_release_reference is required")
    return {"schema_version":SCHEMA_VERSION,"clearance_type":"unstructured_publicity_clearance","signature_namespace":NAMESPACE,
            "generated_at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z"),
            "information_id":information_id,"source_id":str(info["source_id"]),"content_sha256":str(info["content_sha256"]),"holding_sha256":str(info["content_sha256"]),
            "preclearance_event_head":registry.event_head(db,information_id),"publicity_status":"PUBLIC","public_release_reference":reference,
            "public_release_timestamp_utc":_utc(public_release_timestamp_utc),"public_release_evidence_sha256":storage.sha256_file(evidence),
            "decision_scope":"publicity_only","research_use_only":True,"model_plane_eligible":False}


def write_clearance(path: Path, claim: dict[str,Any]) -> Path:
    _validate(claim); path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(claim,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    try: path.chmod(0o600)
    except OSError: pass
    return path


def sign_clearance(*, root: Path, clearance: Path, private_key: Path) -> Path:
    claim=json.loads(Path(clearance).read_text(encoding="utf-8")); _validate(claim)
    return signature_trust.sign_file(root=root,payload=clearance,private_key=private_key,namespace=NAMESPACE)


def _archive(control_dir: Path, claim: bytes, signature: bytes) -> tuple[str,Path]:
    digest=signature_trust.sha256_bytes(claim); root=Path(control_dir).resolve()/"publicity_clearances"/digest; root.mkdir(parents=True,exist_ok=True)
    c=root/"clearance.json"; s=root/"clearance.json.sig"
    if c.exists() and c.read_bytes()!=claim: raise ValueError("existing publicity clearance artifact does not match its digest")
    if s.exists() and s.read_bytes()!=signature: raise ValueError("existing publicity clearance signature differs for the same claim")
    c.write_bytes(claim); s.write_bytes(signature)
    if storage.sha256_file(c)!=digest: raise ValueError("archived publicity clearance hash mismatch")
    return digest,c


def verify_and_apply_clearance(*, root: Path, control_dir: Path, clearance: Path, signature: Path, public_release_evidence: Path,
                               allowed_signers: Path, expected_allowed_signers_sha256: str, identity: str) -> dict[str,Any]:
    control_dir=Path(control_dir).resolve(); db=control_dir/"control.sqlite"; claim_bytes=Path(clearance).read_bytes(); sig_bytes=Path(signature).read_bytes()
    try: claim=json.loads(claim_bytes.decode("utf-8"))
    except Exception as exc: raise ValueError("clearance must be valid UTF-8 JSON") from exc
    if not isinstance(claim,dict): raise ValueError("clearance JSON root must be an object")
    if claim.get("signature_namespace")!=NAMESPACE: raise ValueError(f"signature_namespace must equal {NAMESPACE!r}")
    allowed_hash=signature_trust.verify_bytes(root=root,control_dir=control_dir,payload=claim_bytes,signature=sig_bytes,allowed_signers=allowed_signers,
                                              expected_allowed_signers_sha256=expected_allowed_signers_sha256,identity=identity,namespace=NAMESPACE)
    _validate(claim); iid=str(claim["information_id"]); info=registry.get_information(db,iid)
    if info["domain"]!="unstructured" or registry.current_state(db,iid)!="PUBLICITY_PENDING": raise ValueError("clearance subject is not currently PUBLICITY_PENDING")
    if registry.event_head(db,iid)!=str(claim["preclearance_event_head"]): raise ValueError("clearance is stale or bound to the wrong control-event head")
    if str(info["source_id"])!=str(claim["source_id"]): raise ValueError("clearance source_id does not match the registry")
    if str(info["content_sha256"])!=str(claim["content_sha256"]): raise ValueError("clearance content_sha256 does not match the registry")
    if str(info["content_sha256"])!=str(claim["holding_sha256"]): raise ValueError("clearance holding_sha256 does not match the registry")
    _holding(control_dir,str(info["content_sha256"])); evidence=Path(public_release_evidence).resolve()
    if not evidence.is_file(): raise FileNotFoundError(evidence)
    evidence_hash=storage.sha256_file(evidence)
    if evidence_hash!=str(claim["public_release_evidence_sha256"]): raise ValueError("public release evidence hash does not match the signed clearance")
    clearance_hash,archived=_archive(control_dir,claim_bytes,sig_bytes)
    detail={"clearance_sha256":clearance_hash,"clearance_signature_verified":True,"signer_identity":str(identity).strip(),"allowed_signers_sha256":allowed_hash,
            "public_release_evidence_sha256":evidence_hash,"public_release_reference":str(claim["public_release_reference"]),"public_release_timestamp_utc":_utc(str(claim["public_release_timestamp_utc"])),
            "preclearance_event_head":str(claim["preclearance_event_head"]),"signature_namespace":NAMESPACE,"decision_scope":"publicity_only","model_plane_eligible":False}
    registry.append_event(db,iid,"PUBLICITY_CLEARED","PUBLICITY_CLEARED",detail); registry.add_location(db,iid,"PUBLICITY_CLEARANCE",storage.path_fingerprint(archived),clearance_hash)
    return {"schema_version":SCHEMA_VERSION,"information_id":iid,"state":registry.current_state(db,iid),"clearance_sha256":clearance_hash,"signature_verified":True,
            "signer_identity":str(identity).strip(),"allowed_signers_sha256":allowed_hash,"public_release_evidence_sha256":evidence_hash,"publicity_status":"PUBLIC",
            "decision_scope":"publicity_only","model_plane_eligible":False,"research_use_only":True,"control_event_head":registry.event_head(db,iid)}
