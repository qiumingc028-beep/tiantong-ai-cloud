from __future__ import annotations

import json
import re
from typing import Any

from .constants import EXTERNAL_CONTENT_INSTRUCTION_DETECTED


_PATTERNS = [
    r"忽略(之前|以上|所有).{0,12}(要求|指令|规则)",
    r"不要(遵循|执行|理会).{0,12}(要求|指令|规则)",
    r"system prompt",
    r"developer message",
    r"执行命令",
    r"泄露.*secret",
    r"打印.*token",
]


def detect_external_content_instructions(text: str | None) -> list[str]:
    if not text:
        return []
    lowered = text.lower()
    matches: list[str] = []
    for pattern in _PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE | re.DOTALL):
            matches.append(pattern)
    return matches


def scan_browser_output(browser_output: dict[str, Any]) -> list[str]:
    buffer: list[str] = []
    for key in ("page_title", "extracted_text", "requested_url", "final_url", "domain"):
        value = browser_output.get(key)
        if value:
            buffer.append(str(value))
    structured = browser_output.get("structured_fields")
    if structured:
        try:
            buffer.append(json.dumps(structured, ensure_ascii=False))
        except Exception:
            buffer.append(str(structured))
    matches: list[str] = []
    for text in buffer:
        matches.extend(detect_external_content_instructions(text))
    return [EXTERNAL_CONTENT_INSTRUCTION_DETECTED, *sorted(set(matches))] if matches else []
