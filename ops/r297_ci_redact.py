#!/usr/bin/env python3
"""Redact credentials from text artifacts before CI upload."""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


_SENSITIVE_KEY = r"[A-Za-z0-9_.-]*(?:password|token|secret|cookie|key|authorization|signature)[A-Za-z0-9_.-]*"
_UNQUOTED_SENSITIVE_KEY = r"[A-Za-z0-9_.-]*(?:password|token|secret|cookie|key|signature)[A-Za-z0-9_.-]*"
_HEADER_RULES = (
    (
        re.compile(
            r"(\b(?:authorization|proxy-authorization)\s*:)(?!\s*(?:bearer|device)\b)\s*[^\r\n]*",
            re.I,
        ),
        r"\1 [REDACTED]",
    ),
    (re.compile(r"(\b(?:cookie|set-cookie)\s*:\s*)[^\r\n]*", re.I), r"\1[REDACTED]"),
)

_CLOSED_QUOTED_VALUE = re.compile(
    r"(?P<prefix>(?P<key_quote>['\"]?)"
    + _SENSITIVE_KEY
    + r"(?P=key_quote)\s*[:=]\s*(?P<value_quote>['\"]))"
    r"(?P<value>(?:\\.|(?!(?P=value_quote)|\r?\n(?=\s*(?:[\[{]|[^\r\n]{0,80}[:=])))[\s\S])*?)"
    r"(?P<closing>(?P=value_quote))",
    re.I,
)
_TRUNCATED_QUOTED_VALUE = re.compile(
    r"(?P<prefix>(?P<key_quote>['\"]?)"
    + _SENSITIVE_KEY
    + r"(?P=key_quote)\s*[:=]\s*(?P<value_quote>['\"]))"
    r"(?P<value>(?:\\.|(?!(?P=value_quote))[^\r\n])*)(?=\r?$)",
    re.I | re.M,
)
_UNQUOTED_VALUE = re.compile(
    r"(?P<prefix>(?P<key_quote>['\"]?)"
    + _UNQUOTED_SENSITIVE_KEY
    + r"(?P=key_quote)\s*[:=]\s*)(?P<value>[^\s,<}\]\[\"']+)",
    re.I,
)

_RULES = (
    (re.compile(r"(authorization:\s*(?:bearer|device)\s+)[^\s<\"']+", re.I), r"\1[REDACTED]"),
    (re.compile(r"(postgres(?:ql)?://)[^/@:\s\"']+:[^@/\s\"']+@", re.I), r"\1[REDACTED]@"),
)


def _redact_text(value: str) -> str:
    for pattern, replacement in _HEADER_RULES:
        value = pattern.sub(replacement, value)
    value = _CLOSED_QUOTED_VALUE.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]{match.group('closing')}",
        value,
    )
    value = _TRUNCATED_QUOTED_VALUE.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]",
        value,
    )
    for pattern, replacement in _RULES:
        value = pattern.sub(replacement, value)
    value = _UNQUOTED_VALUE.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]",
        value,
    )
    return value


def redact(path: Path) -> None:
    value = path.read_text(encoding="utf-8", errors="replace")
    try:
        root = ET.fromstring(value)
    except ET.ParseError:
        path.write_text(_redact_text(value), encoding="utf-8")
        return

    for element in root.iter():
        element.attrib.update({key: _redact_text(item) for key, item in element.attrib.items()})
        if element.text:
            element.text = _redact_text(element.text)
        if element.tail:
            element.tail = _redact_text(element.tail)
    ET.ElementTree(root).write(path, encoding="unicode")


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: r297_ci_redact.py FILE [FILE ...]")
    for value in sys.argv[1:]:
        redact(Path(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
