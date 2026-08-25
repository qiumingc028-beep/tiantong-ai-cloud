from __future__ import annotations

import hashlib
from datetime import datetime, timezone


def hash_query_text(query_text: str | None) -> str:
    return hashlib.sha256((query_text or "").strip().encode("utf-8")).hexdigest()


def citation_payload(
    *,
    knowledge_id: str,
    version_id: str,
    chunk_id: str | None,
    task_id: int | None,
    execution_id: str | None,
    employee_id: str | None,
    usage_type: str,
    query_text: str | None,
    citation_summary: str | None,
) -> dict[str, object]:
    return {
        "citation_id": f"cit-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "knowledge_id": knowledge_id,
        "version_id": version_id,
        "chunk_id": chunk_id,
        "task_id": task_id,
        "execution_id": execution_id,
        "employee_id": employee_id,
        "usage_type": usage_type,
        "query_text_hash": hash_query_text(query_text),
        "citation_summary": citation_summary or "",
        "created_at": datetime.now(timezone.utc),
    }
