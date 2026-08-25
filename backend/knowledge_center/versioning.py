from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from .chunking import chunk_text


def next_version_number(existing_numbers: Iterable[str | int | None]) -> str:
    values: list[int] = []
    for raw in existing_numbers:
        if raw is None:
            continue
        try:
            values.append(int(str(raw).split(".", 1)[0]))
        except Exception:
            continue
    return str((max(values) if values else 0) + 1)


def make_version_payload(*, knowledge_id: str, title: str, summary: str, content: str, content_format: str, change_summary: str, change_reason: str, source_type: str, source_execution_id: str | None, source_report_id: str | None, created_by: str | None, reviewed_by: str | None = None, approved_by: str | None = None) -> dict[str, object]:
    version_id = str(uuid4())
    normalized_content = content or ""
    return {
        "version_id": version_id,
        "knowledge_id": knowledge_id,
        "version_number": None,
        "title": title,
        "summary": summary,
        "content": normalized_content,
        "content_format": content_format,
        "change_summary": change_summary,
        "change_reason": change_reason,
        "source_type": source_type,
        "source_execution_id": source_execution_id,
        "source_report_id": source_report_id,
        "content_hash": _content_hash(normalized_content),
        "created_by": created_by,
        "reviewed_by": reviewed_by,
        "approved_by": approved_by,
        "created_at": datetime.now(timezone.utc),
        "approved_at": None,
        "chunks": chunk_text(normalized_content),
    }


def _content_hash(content: str) -> str:
    import hashlib

    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()
