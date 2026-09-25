from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validated_sha256(value: str, *, label: str) -> str:
    value=str(value or "").strip().lower()
    if len(value)!=64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{label} must be a trusted 64-character SHA-256 hex digest")
    return value


def external_path(root: Path, path: Path, *, label: str) -> Path:
    root=Path(root).resolve(); resolved=Path(path).expanduser().resolve()
    try: resolved.relative_to(root)
    except ValueError: return resolved
    raise ValueError(f"{label} must be stored outside the repository root")


def sign_file(*, root: Path, payload: Path, private_key: Path, namespace: str) -> Path:
    private_key=external_path(root,private_key,label="private publicity-clearance signing key")
    payload=Path(payload)
    if not payload.is_file(): raise FileNotFoundError(payload)
    if not private_key.is_file(): raise FileNotFoundError(private_key)
    subprocess.run(["ssh-keygen","-Y","sign","-f",str(private_key),"-n",namespace,str(payload)],check=True)
    signature=Path(str(payload)+".sig")
    if not signature.is_file(): raise RuntimeError("ssh-keygen did not create the expected detached signature")
    return signature


def verify_bytes(*, root: Path, control_dir: Path, payload: bytes, signature: bytes, allowed_signers: Path,
                 expected_allowed_signers_sha256: str, identity: str, namespace: str) -> str:
    identity=str(identity or "").strip()
    if not identity: raise ValueError("signer identity is required")
    allowed_signers=external_path(root,allowed_signers,label="publicity allowed-signers trust file")
    allowed=allowed_signers.read_bytes(); actual=sha256_bytes(allowed)
    expected=validated_sha256(expected_allowed_signers_sha256,label="expected_allowed_signers_sha256")
    if actual!=expected: raise ValueError(f"allowed-signers hash mismatch: actual={actual}; expected={expected}")
    tmp=Path(control_dir).resolve()/"_tmp"; tmp.mkdir(parents=True,exist_ok=True)
    afd,aname=tempfile.mkstemp(prefix="publicity-allowed-",dir=tmp); sfd,sname=tempfile.mkstemp(prefix="publicity-signature-",dir=tmp)
    try:
        with os.fdopen(afd,"wb") as f: f.write(allowed); f.flush(); os.fsync(f.fileno())
        with os.fdopen(sfd,"wb") as f: f.write(signature); f.flush(); os.fsync(f.fileno())
        proc=subprocess.run(["ssh-keygen","-Y","verify","-f",aname,"-I",identity,"-n",namespace,"-s",sname],input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if proc.returncode!=0:
            raise PermissionError("publicity clearance signature verification failed: "+proc.stderr.decode("utf-8","replace").strip())
    finally:
        Path(aname).unlink(missing_ok=True); Path(sname).unlink(missing_ok=True)
    return actual
