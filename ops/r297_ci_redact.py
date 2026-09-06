#!/usr/bin/env python3
"""Redact credentials from text artifacts before CI upload."""

from __future__ import annotations

import re
import sys
from pathlib import Path


_RULES = (
    (
        re.compile(
            r"(&quot;(?:password|token|secret|cookie|key)&quot;\s*[:=]\s*&quot;)[^&<]*(&quot;)",
            re.I,
        ),
        r"\1[REDACTED]\2",
    ),
    (
        re.compile(r'(\"(?:password|token|secret|cookie|key)\"\s*[:=]\s*\")[^\"]*(\")', re.I),
        r"\1[REDACTED]\2",
    ),
    (re.compile(r"(authorization:\s*(?:bearer|device)\s+)[^\s<\"']+", re.I), r"\1[REDACTED]"),
    (re.compile(r"((?:password|token|secret|cookie|key)[=:]\s*)[^\s<\"']+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(postgres(?:ql)?://)[^/@:\s\"']+:[^@/\s\"']+@", re.I), r"\1[REDACTED]@"),
)


def redact(path: Path) -> None:
    value = path.read_text(encoding="utf-8", errors="replace")
    for pattern, replacement in _RULES:
        value = pattern.sub(replacement, value)
    path.write_text(value, encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: r297_ci_redact.py FILE [FILE ...]")
    for value in sys.argv[1:]:
        redact(Path(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
