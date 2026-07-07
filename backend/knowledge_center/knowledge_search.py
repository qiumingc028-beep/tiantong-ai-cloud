from __future__ import annotations

import re
from typing import Any

from .knowledge_storage import list_knowledge


def search_knowledge(query: str, limit: int = 10, knowledge_type: str | None = None) -> dict[str, Any]:
    safe_query = (query or "").strip()
    rows = list_knowledge(500, knowledge_type)
    ranked = sorted(
        [score_item(row, safe_query) for row in rows],
        key=lambda row: row["similarity_score"],
        reverse=True,
    )
    matches = [row for row in ranked if row["similarity_score"] > 0][: max(1, min(limit, 50))]
    return {
        "query": safe_query,
        "matches": matches,
        "total_matches": len(matches),
        "search_mode": "local_similarity_search",
        "external_vector_db_used": False,
    }


def score_item(item: dict[str, Any], query: str) -> dict[str, Any]:
    text = searchable_text(item)
    query_tokens = tokenize(query)
    if not query_tokens:
        score = 0
    else:
        score = sum(1 for token in query_tokens if token in text)
        if query and query in text:
            score += 3
    return {**item, "similarity_score": score}


def searchable_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    return f"{item.get('title', '')} {item.get('summary', '')} {content} {' '.join(item.get('tags') or [])}".lower()


def tokenize(value: str) -> list[str]:
    text = value.lower()
    tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", text)
    if not tokens and text:
        tokens = [text]
    return tokens
