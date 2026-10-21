"""Conservative allowlist and content checks; final owner review remains mandatory."""

from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path

TOKEN_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{24,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}"),
    re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}"),
    re.compile(r"https?://[^\s/]+:[^\s/@]+@"),
)
OPERATIONS = (
    re.compile(r"/(?:srv|midia|root|home)/"),
    re.compile(r"\bproj_[A-Za-z0-9]{12,}"),
    re.compile(r"\b[a-z][a-z0-9-]+-\d{6}\b"),
    re.compile(r"https://github\.com/[^\s)]+/(?:pull/\d+|actions/runs/\d+)"),
    re.compile(r"\b(?:[A-Fa-f0-9]{2}:){19,31}[A-Fa-f0-9]{2}\b"),
)
HOST = re.compile(r"https?://([A-Za-z0-9.-]+)(?=[:/\s\"'`<>),;]|$)")
ALLOWED_HOSTS = frozenset({
    "example.org", "api.example.org", "careerbrain.invalid", "accounts.google.com",
    "json-schema.org", "docs.github.com", "developers.openai.com", "pypi.org",
    "www.googleapis.com",
})
PRIVATE_IP = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
SYNTHETIC_IPS = frozenset({"127." + "0.0.1", "10." + "0.0.1"})
SYNTHETIC_HOSTS = SYNTHETIC_IPS | frozenset({"localhost", "service.internal", "2130706433"})


def content_findings(text: str, relative: str) -> list[str]:
    findings = []
    if any(pattern.search(text) for pattern in TOKEN_PATTERNS):
        findings.append("credential-pattern")
    if any(pattern.search(text) for pattern in OPERATIONS):
        findings.append("operational-metadata")
    for match in HOST.finditer(text):
        host = match.group(1).lower().rstrip(".")
        if relative == "tests/test_contracts.py" and host in SYNTHETIC_HOSTS:
            continue  # Exact hand-reviewed adversarial fixtures, never arbitrary hosts.
        if host not in ALLOWED_HOSTS:
            findings.append("unapproved-url-host")
    for value in PRIVATE_IP.findall(text):
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if not address.is_global and not (
            relative == "tests/test_contracts.py" and value in SYNTHETIC_IPS
        ):
            findings.append("private-address")
    for address in re.findall(r"\b[\w.+-]+@([\w.-]+\.[A-Za-z]{2,})\b", text):
        if address not in {"example.org", "example.com", "example.invalid"}:
            findings.append("non-synthetic-email")
    return sorted(set(findings))


def check_tree(root: Path, *, candidate: bool = True) -> list[str]:
    root = root.resolve()
    allow_path = root / "public-allowlist.json"
    if allow_path.is_symlink() or not allow_path.is_file():
        return ["missing-or-unsafe-allowlist"]
    try:
        manifest = json.loads(allow_path.read_text())
        entries = manifest["files"]
        allowed = {item["path"] for item in entries}
    except (ValueError, KeyError, TypeError):
        return ["invalid-allowlist"]
    if len(allowed) != len(entries):
        return ["duplicate-allowlist-entry"]
    errors = []
    for rel in allowed:
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
            errors.append("unsafe-allowlist-path")
            continue
        item = root / path
        if any(parent.is_symlink() for parent in [item, *item.parents] if parent != root):
            errors.append(f"symlink:{rel}")
        elif not item.is_file():
            errors.append(f"missing:{rel}")
    actual = set()
    for item in root.rglob("*"):
        relative = item.relative_to(root)
        if not candidate and relative.parts[0] in {".git", ".venv", "__pycache__"}:
            continue
        if not candidate and "__pycache__" in relative.parts:
            continue
        if item.is_symlink():
            errors.append(f"symlink:{relative.as_posix()}")
        if item.name == ".git" or ".git" in relative.parts:
            errors.append("git-metadata-in-candidate")
        if item.is_file():
            actual.add(relative.as_posix())
    errors.extend(f"unexpected:{rel}" for rel in sorted(actual - allowed))
    for rel in sorted(actual & allowed):
        path = root / rel
        if path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            errors.append(f"non-text:{rel}")
            continue
        if not text.endswith("\n") or any(line.rstrip() != line for line in text.splitlines()):
            errors.append(f"whitespace:{rel}")
        for category in content_findings(text, rel):
            errors.append(f"{category}:{rel}")
    return sorted(set(errors))
