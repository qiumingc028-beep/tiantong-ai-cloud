from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


KNOWLEDGE_MEMORY: list[dict[str, Any]] = []
MAX_KNOWLEDGE_ITEMS = 500


def save_knowledge(item: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_knowledge_item(item)
    KNOWLEDGE_MEMORY.insert(0, normalized)
    del KNOWLEDGE_MEMORY[MAX_KNOWLEDGE_ITEMS:]
    return normalized


def save_many(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [save_knowledge(item) for item in items]


def list_knowledge(limit: int = 50, knowledge_type: str | None = None) -> list[dict[str, Any]]:
    safe_limit = min(max(int(limit or 50), 1), MAX_KNOWLEDGE_ITEMS)
    rows = KNOWLEDGE_MEMORY
    if knowledge_type:
        rows = [row for row in rows if row.get("knowledge_type") == knowledge_type]
    return rows[:safe_limit]


def clear_knowledge() -> None:
    KNOWLEDGE_MEMORY.clear()


def normalize_knowledge_item(item: dict[str, Any]) -> dict[str, Any]:
    source = item if isinstance(item, dict) else {}
    knowledge_type = str(source.get("knowledge_type") or "execution_case")
    title = str(source.get("title") or "未命名知识")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "knowledge_id": source.get("knowledge_id") or f"know-{len(KNOWLEDGE_MEMORY) + 1}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "knowledge_type": knowledge_type,
        "title": title,
        "summary": str(source.get("summary") or ""),
        "content": source.get("content") if isinstance(source.get("content"), dict) else {"text": str(source.get("content") or "")},
        "tags": source.get("tags") if isinstance(source.get("tags"), list) else [],
        "source": str(source.get("source") or "tianwu_learning_center"),
        "status": "stored",
        "created_at": now,
        "can_auto_modify_prompt": False,
        "can_auto_modify_rule": False,
        "requires_tian_shen_approval": True,
    }
