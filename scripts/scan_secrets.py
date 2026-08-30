#!/usr/bin/env python3
"""Scan Git-tracked files for credential patterns.

Runs in CI on every push and pull request, and locally before a push:

    python3 scripts/scan_secrets.py

Only tracked files are scanned — anything `.gitignore` excludes cannot reach a
remote, and `backend/.env` legitimately holds real keys on a developer machine.

Findings print the file, line number and pattern name. **The matched value is
never printed**, because CI logs are themselves a place secrets leak from.

Exit codes: 0 clean, 1 findings, 2 could not run.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Patterns for credentials that would be genuinely damaging if published. Each is
# anchored on a vendor-specific prefix rather than on entropy alone, because an
# entropy heuristic on a codebase full of UUIDs and hashes is all false positives.
PATTERNS: dict[str, re.Pattern[str]] = {
    "Google/Gemini API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "OpenAI API key": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    "Anthropic API key": re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    "AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}"),
    "Slack token": re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}"),
    "Private key block": re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\."),
    "URL with embedded password": re.compile(
        r"\b(?:postgres(?:ql)?|mysql|mongodb|redis|amqp)(?:\+\w+)?://"
        r"[^\s:@/]+:[^\s:@/]+@"
    ),
}

# Credentials that are deliberately public: the local development defaults, which
# are documented in the README and identical for every clone. Ignoring them keeps
# the signal high; anything else with an embedded password is a real finding.
ALLOWED = (
    re.compile(r"://anchor:anchor@"),
    re.compile(r"://postgres:postgres@"),
    re.compile(r"://user:password@"),
)

# Binary and vendored paths that would produce noise without adding coverage.
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
    ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".zip", ".gz",
}
SKIP_PARTS = {"node_modules", ".venv", "dist", "build", "__pycache__"}

# This file necessarily contains the patterns it searches for.
SELF = Path(__file__).name


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        print("error: not a Git repository, or git is unavailable.", file=sys.stderr)
        sys.exit(2)
    return [Path(p) for p in result.stdout.split("\0") if p]


def scan(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return []

    findings: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if any(allowed.search(line) for allowed in ALLOWED):
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append((number, label))
    return findings


def main() -> int:
    files = [
        path
        for path in tracked_files()
        if path.suffix.lower() not in SKIP_SUFFIXES
        and not set(path.parts) & SKIP_PARTS
        and path.name != SELF
        and path.is_file()
    ]

    total = 0
    for path in files:
        for number, label in scan(path):
            # Deliberately no value, no snippet: this output goes to a CI log.
            print(f"{path}:{number}: possible {label}")
            total += 1

    print(f"\nscanned {len(files)} tracked files")
    if total:
        print(f"FAILED: {total} possible credential(s) found. Values withheld.")
        print("Remove the credential, rotate it, and purge it from Git history.")
        return 1

    print("OK: no credential patterns found in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
