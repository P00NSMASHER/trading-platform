from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ALLOW_MARKER = "secret-scan: allow"
PLACEHOLDER_MARKERS = (
    "example", "placeholder", "dummy", "synthetic", "test-only", "test_", "changeme",
    "redacted", "not-a-secret", "not_a_secret", "do-not-store", "do_not_store",
)

DANGEROUS_BASENAMES = {
    ".env", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
}
DANGEROUS_SUFFIXES = {
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore",
}
ALLOWED_DANGEROUS_NAME_SUFFIXES = {
    ".example", ".example.txt",
}

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{20,255})\b")),
    ("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
)

GENERIC_SECRET = re.compile(
    r"""(?ix)
    \b(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|client[_-]?secret|
        secret[_-]?key|password|passwd)\b
    \s*["']?\s*[:=]\s*["']([^"'\s]{12,})["']
    """
)

DEFAULT_SKIP_PREFIXES = (
    ".git/",
    ".pytest_cache/",
    "__pycache__/",
)
DEFAULT_SKIP_PATHS = {
    "scripts/secret_scan.py",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(value)
    return -sum((count / n) * math.log2(count / n) for count in counts.values())


def _looks_placeholder(value: str) -> bool:
    low = value.lower()
    return any(marker in low for marker in PLACEHOLDER_MARKERS)


def _tracked_files(root: Path) -> list[Path]:
    root = root.resolve()
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        rels = [p for p in proc.stdout.decode("utf-8").split("\0") if p]
        return [root / rel for rel in rels]
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _dangerous_path(rel: str) -> bool:
    p = Path(rel)
    name = p.name.lower()
    if name.endswith(tuple(ALLOWED_DANGEROUS_NAME_SUFFIXES)):
        return False
    if name in DANGEROUS_BASENAMES:
        return True
    return p.suffix.lower() in DANGEROUS_SUFFIXES


def scan_paths(root: Path, paths: Iterable[Path] | None = None) -> list[Finding]:
    root = root.resolve()
    findings: list[Finding] = []
    paths = list(paths) if paths is not None else _tracked_files(root)

    for path in paths:
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        if rel in DEFAULT_SKIP_PATHS or any(rel.startswith(prefix) for prefix in DEFAULT_SKIP_PREFIXES):
            continue

        if _dangerous_path(rel):
            findings.append(Finding(rel, 0, "dangerous_secret_filename"))

        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if _is_binary(raw):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        for line_no, line in enumerate(text.splitlines(), 1):
            if ALLOW_MARKER in line.lower():
                continue
            for kind, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append(Finding(rel, line_no, kind))
            generic = GENERIC_SECRET.search(line)
            if generic:
                value = generic.group(1)
                if (
                    not _looks_placeholder(value)
                    and len(value) >= 16
                    and _entropy(value) >= 3.2
                ):
                    findings.append(Finding(rel, line_no, "generic_secret_literal"))

    # Stable, deduplicated output without printing secret contents.
    unique = {(f.path, f.line, f.kind): f for f in findings}
    return [unique[k] for k in sorted(unique)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan tracked repository text for likely committed secrets.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    findings = scan_paths(args.root)
    if findings:
        print(f"secret scan failed: {len(findings)} finding(s)")
        for f in findings:
            location = f"{f.path}:{f.line}" if f.line else f.path
            print(f"- {location} [{f.kind}]")
        return 1

    print("secret scan passed: no likely committed secrets detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
