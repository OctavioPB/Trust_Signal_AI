#!/usr/bin/env python3
"""PII audit script for TrustSignal AI.

Scans Python source files and JSON log lines for patterns that indicate
Personally Identifiable Information (PII) may be leaking into code or logs.

CLAUDE.md Hard Rule #6: No candidate names, email addresses, or recruiter
identifiers may appear in logs or Kafka payloads — UUID-only.

Checks
------
- Variable / parameter names that shadow PII fields (candidate_name, etc.)
- String literals that contain email addresses
- JSON log records whose keys look like PII fields

Usage
-----
    python scripts/pii_audit.py                      # scan entire repo
    python scripts/pii_audit.py --path src/          # restrict to subtree
    python scripts/pii_audit.py --log-dir /var/log/trustsignal/

Exit code: 0 = clean, 1 = findings present (suitable for CI).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ── Patterns for Python source files ──────────────────────────────────────────

_PII_VAR_RE = re.compile(
    r"\b("
    r"candidate_name|candidate_email|candidate_phone|"
    r"recruiter_name|recruiter_email|"
    r"full_name|first_name|last_name|"
    r"phone_number|mobile_number|"
    r"date_of_birth|dob|ssn|passport"
    r")\b",
    re.IGNORECASE,
)

# Email literal inside a string (skip our own admin address)
_EMAIL_LITERAL_RE = re.compile(
    r'["\'][a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}["\']'
)
_OWN_DOMAIN = "trustsignal.ai"

# ── Patterns for JSON log records ─────────────────────────────────────────────

_PII_LOG_KEY_RE = re.compile(
    r"^(name|email|phone|mobile|full_name|first_name|last_name|"
    r"candidate_name|recruiter_name|dob|ssn)$",
    re.IGNORECASE,
)

# ── Skip rules ────────────────────────────────────────────────────────────────

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache"}
_SKIP_FILES = {"pii_audit.py"}  # don't flag the audit script itself


# ── Scanners ──────────────────────────────────────────────────────────────────

def _scan_python_file(path: Path) -> list[tuple[int, str, str]]:
    """Return list of (lineno, description, line_snippet) for each finding."""
    findings: list[tuple[int, str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return findings

    for lineno, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        # Skip comment lines (they may legitimately mention PII field names)
        if stripped.startswith("#"):
            continue

        if m := _PII_VAR_RE.search(line):
            findings.append((lineno, f"PII identifier: {m.group()!r}", line.strip()[:120]))

        if m := _EMAIL_LITERAL_RE.search(line):
            if _OWN_DOMAIN not in m.group():
                findings.append((lineno, "Email address literal", line.strip()[:120]))

    return findings


def _scan_log_file(path: Path) -> list[tuple[int, str, str]]:
    """Scan JSON-lines log file for PII key names in records."""
    findings: list[tuple[int, str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return findings

    for lineno, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(record, dict):
            continue

        for key in record:
            if _PII_LOG_KEY_RE.match(str(key)):
                findings.append((lineno, f"PII key in log record: {key!r}", line[:120]))

    return findings


# ── Directory walker ──────────────────────────────────────────────────────────

def _audit(root: Path, log_dir: Path | None) -> dict[str, list[tuple[int, str, str]]]:
    report: dict[str, list[tuple[int, str, str]]] = {}

    for path in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.name in _SKIP_FILES:
            continue
        findings = _scan_python_file(path)
        if findings:
            report[str(path.relative_to(root))] = findings

    if log_dir and log_dir.exists():
        for ext in ("*.log", "*.jsonl"):
            for path in log_dir.rglob(ext):
                findings = _scan_log_file(path)
                if findings:
                    report[str(path)] = findings

    return report


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", default=".", help="Root directory to scan (default: .)")
    parser.add_argument("--log-dir", default=None, help="Directory containing JSON log files")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    log_dir = Path(args.log_dir).resolve() if args.log_dir else None

    print(f"TrustSignal PII audit — scanning {root}")
    report = _audit(root, log_dir)

    if not report:
        print("✓ No PII findings.")
        return 0

    total = sum(len(v) for v in report.values())
    print(f"✗ {total} finding(s) across {len(report)} file(s):\n")
    for filepath, findings in sorted(report.items()):
        print(f"  {filepath}")
        for lineno, desc, snippet in findings:
            print(f"    Line {lineno:4d}: {desc}")
            print(f"             {snippet}")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
