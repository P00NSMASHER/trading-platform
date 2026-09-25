from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HoldingSnapshot:
    path: Path
    sha256: str
    size_bytes: int
    source_path_fingerprint: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def path_fingerprint(path: Path) -> str:
    return hashlib.sha256(str(Path(path).resolve()).encode("utf-8")).hexdigest()


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _private_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _snapshot_name(source: Path) -> str:
    """Preserve only format-relevant suffixes while keeping the original name private."""
    suffixes = [s.lower() for s in Path(source).suffixes]
    if suffixes[-2:] in ([".csv", ".gz"], [".txt", ".gz"], [".json", ".gz"]):
        return "original" + "".join(suffixes[-2:])
    if suffixes and suffixes[-1] in {".gz", ".csv", ".txt", ".json"}:
        return "original" + suffixes[-1]
    return "original"


def receive_to_holding(source: Path, control_dir: Path) -> HoldingSnapshot:
    source = Path(source).resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(source)
    control_dir = Path(control_dir).resolve()
    holding_root = control_dir / "holding"
    tmp_root = control_dir / "_tmp"
    _private_dir(control_dir); _private_dir(holding_root); _private_dir(tmp_root)
    h = hashlib.sha256(); size = 0
    fd, tmp_name = tempfile.mkstemp(prefix="holding-", dir=tmp_root)
    tmp = Path(tmp_name)
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk: break
                h.update(chunk); size += len(chunk); dst.write(chunk)
            dst.flush(); os.fsync(dst.fileno())
        digest = h.hexdigest()
        final_dir = holding_root / digest; _private_dir(final_dir)
        final = final_dir / _snapshot_name(source)
        if final.exists():
            if sha256_file(final) != digest or final.stat().st_size != size:
                raise ValueError("existing HOLDING snapshot does not match expected digest")
            tmp.unlink(missing_ok=True)
        else:
            os.replace(tmp, final); _private_file(final)
        if sha256_file(final) != digest:
            raise ValueError("HOLDING snapshot hash mismatch after atomic placement")
        return HoldingSnapshot(final, digest, size, path_fingerprint(source))
    finally:
        tmp.unlink(missing_ok=True)


def quarantine_snapshot(snapshot: HoldingSnapshot, control_dir: Path) -> Path:
    control_dir = Path(control_dir).resolve()
    root = control_dir / "quarantine" / snapshot.sha256
    tmp_root = control_dir / "_tmp"
    _private_dir(root); _private_dir(tmp_root)
    final = root / snapshot.path.name
    if final.exists():
        if sha256_file(final) != snapshot.sha256:
            raise ValueError("existing quarantine snapshot hash mismatch")
        return final
    fd, tmp_name = tempfile.mkstemp(prefix="quarantine-", dir=tmp_root); os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copyfile(snapshot.path, tmp); _private_file(tmp)
        if sha256_file(tmp) != snapshot.sha256:
            raise ValueError("quarantine copy hash mismatch")
        os.replace(tmp, final); _private_file(final)
        return final
    finally:
        tmp.unlink(missing_ok=True)
