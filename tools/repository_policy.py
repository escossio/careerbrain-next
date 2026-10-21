"""Audit this tree and its future clean Git history, never host-private files."""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

from tools.publication_audit import TOKEN_PATTERNS, check_tree, content_findings

ROOT = Path(__file__).resolve().parents[1]


def violations(text: str) -> bool:
    return any(pattern.search(text) for pattern in TOKEN_PATTERNS)


def check(*, candidate: bool = False) -> list[str]:
    issues = check_tree(ROOT, candidate=candidate)
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in {".git", ".venv", "__pycache__"} for part in path.relative_to(ROOT).parts):
            continue
        ast.parse(path.read_text(), filename=str(path.relative_to(ROOT)))
    if not candidate and (ROOT / ".git").is_dir():
        def git(*args):
            return subprocess.run(["git", "--no-optional-locks", "-C", str(ROOT), *args],
                                  capture_output=True, check=True).stdout
        for row in git("rev-list", "--objects", "--all").decode().splitlines():
            parts = row.split(" ", 1)
            if len(parts) != 2:
                continue
            oid, rel = parts
            if git("cat-file", "-t", oid).strip() != b"blob":
                continue
            # All historical blobs are scanned, including deleted paths.
            text = git("cat-file", "blob", oid).decode("utf-8", errors="strict")
            for category in content_findings(text, rel):
                issues.append(f"historical-{category}:{rel}")
    return sorted(set(issues))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", action="store_true", help="Forbid all Git metadata and non-allowlisted files")
    args = parser.parse_args()
    results = check(candidate=args.candidate)
    for issue in results:
        print(issue)
    print(f"Repository policy: {'FAIL' if results else 'PASS'}")
    sys.exit(bool(results))
