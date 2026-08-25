from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.config import get_settings

from .chunking import chunk_text
from .models import KnowledgeAsset, KnowledgeChunk, KnowledgeTag, KnowledgeTagRelation, KnowledgeVersion
from .sanitizer import normalize_text


@dataclass
class KnowledgeSearchDocument:
    knowledge_id: str
    version_id: str | None
    title: str
    summary: str
    content: str
    category: str
    knowledge_type: str
    status: str
    visibility: str
    risk_level: str
    updated_at: str | None
    source_count: int
    source_reliability: float
    tags: list[str]


class LocalKeywordKnowledgeIndex:
    def index_knowledge(self, db: Session, knowledge_id: str) -> dict[str, Any]:
        asset = db.get(KnowledgeAsset, knowledge_id)
        if not asset:
            return {"ok": False, "indexed": 0}
        version = db.get(KnowledgeVersion, asset.current_version_id) if asset.current_version_id else None
        if not version:
            return {"ok": True, "indexed": 0}
        existing = db.query(KnowledgeChunk).filter(KnowledgeChunk.version_id == version.version_id).all()
        if not existing:
            from .chunking import chunk_text

            for chunk in chunk_text(version.content or ""):
                db.add(
                    KnowledgeChunk(
                        chunk_id=f"chunk-{version.version_id}-{chunk['chunk_index']}",
                        knowledge_id=asset.knowledge_id,
                        version_id=version.version_id,
                        chunk_index=int(chunk["chunk_index"]),
                        heading=str(chunk["heading"]),
                        content=str(chunk["content"]),
                        token_estimate=int(chunk["token_estimate"]),
                        content_hash=str(chunk["content_hash"]),
                        metadata_json=json.dumps(chunk["metadata"], ensure_ascii=False),
                    )
                )
            db.commit()
        return {"ok": True, "indexed": len(existing) or len(chunk_text(version.content or ""))}

    def delete_index(self, db: Session, knowledge_id: str) -> dict[str, Any]:
        deleted = db.query(KnowledgeChunk).filter(KnowledgeChunk.knowledge_id == knowledge_id).delete()
        db.commit()
        return {"ok": True, "deleted": deleted}

    def search(self, db: Session, query: str, *, limit: int = 10, include_unpublished: bool = False) -> list[dict[str, Any]]:
        rows = query_assets(db, query=query, limit=limit, include_unpublished=include_unpublished)
        return [serialize_asset(row, db=db) for row in rows]

    def health_check(self) -> dict[str, Any]:
        settings = get_settings()
        return {"ok": True, "provider": "local_keyword", "vector_enabled": settings.KNOWLEDGE_VECTOR_SEARCH_ENABLED}

    def get_metadata(self) -> dict[str, Any]:
        return {"provider": "local_keyword", "supports_vector": False, "supports_filters": True}


class QdrantKnowledgeIndex:
    def index_knowledge(self, db: Session, knowledge_id: str) -> dict[str, Any]:
        return {"ok": False, "indexed": 0, "reason": "vector_search_disabled"}

    def delete_index(self, db: Session, knowledge_id: str) -> dict[str, Any]:
        return {"ok": False, "reason": "vector_search_disabled"}

    def search(self, db: Session, query: str, *, limit: int = 10, include_unpublished: bool = False) -> list[dict[str, Any]]:
        return []

    def health_check(self) -> dict[str, Any]:
        return {"ok": False, "provider": "qdrant", "enabled": False}

    def get_metadata(self) -> dict[str, Any]:
        return {"provider": "qdrant", "enabled": False}


def tokenize(value: str | None) -> list[str]:
    text = normalize_text(value).lower()
    if not text:
        return []
    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", text)


def _score_asset(asset: KnowledgeAsset, tokens: list[str], query: str | None = None) -> int:
    if not tokens and not query:
        return 1
    parts = [
        normalize_text(asset.title),
        normalize_text(asset.summary),
        normalize_text(asset.knowledge_code),
        normalize_text(asset.knowledge_type),
        normalize_text(asset.category),
        normalize_text(asset.status),
        normalize_text(asset.visibility),
        normalize_text(asset.risk_level),
        normalize_text(asset.owner_department),
    ]
    haystack = " ".join(parts).lower()
    title = normalize_text(asset.title).lower()
    score = 0
    for token in tokens or tokenize(query):
        if not token:
            continue
        if token in title:
            score += 3
        elif token in haystack:
            score += 1
    if query and normalize_text(query).lower() in haystack:
        score += 2
    if asset.status == "已发布":
        score += 1
    return score


def query_assets(db: Session, *, query: str | None = None, limit: int = 20, include_unpublished: bool = False, filters: dict[str, Any] | None = None):
    filters = filters or {}
    rows = db.query(KnowledgeAsset).order_by(KnowledgeAsset.updated_at.desc()).all()
    if not include_unpublished:
        rows = [row for row in rows if row.status == "已发布"]
    if filters.get("category"):
        rows = [row for row in rows if row.category == filters["category"]]
    if filters.get("tag"):
        tag_ids = {
            relation.knowledge_id
            for relation in db.query(KnowledgeTagRelation).join(KnowledgeTag, KnowledgeTag.tag_id == KnowledgeTagRelation.tag_id).filter(KnowledgeTag.tag_name == filters["tag"]).all()
        }
        rows = [row for row in rows if row.knowledge_id in tag_ids]
    if filters.get("knowledge_type"):
        rows = [row for row in rows if row.knowledge_type == filters["knowledge_type"]]
    if filters.get("status"):
        rows = [row for row in rows if row.status == filters["status"]]
    if filters.get("owner_department"):
        rows = [row for row in rows if row.owner_department == filters["owner_department"]]
    if filters.get("risk_level"):
        rows = [row for row in rows if row.risk_level == filters["risk_level"]]
    if filters.get("min_confidence") is not None:
        rows = [row for row in rows if (row.source_count or 0) >= int(filters["min_confidence"])]
    if query:
        tokens = tokenize(query)
        scored = []
        for row in rows:
            score = _score_asset(row, tokens, query)
            if score:
                scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1].updated_at or item[1].created_at))
        rows = [row for _, row in scored]
    return rows[: max(1, min(int(limit or 20), 100))]


def serialize_asset(asset: KnowledgeAsset, db: Session | None = None) -> dict[str, Any]:
    version = None
    if db is not None and asset.current_version_id:
        version = db.get(KnowledgeVersion, asset.current_version_id)
    tags = []
    citations = []
    if db is not None:
        from .models import KnowledgeCitation, KnowledgeTagRelation

        tags = [
            row.tag.tag_name
            for row in db.query(KnowledgeTagRelation).filter(KnowledgeTagRelation.knowledge_id == asset.knowledge_id).all()
            if row.tag and row.tag.enabled
        ]
        citations = db.query(KnowledgeCitation).filter(KnowledgeCitation.knowledge_id == asset.knowledge_id).all()
    return {
        "knowledge_id": asset.knowledge_id,
        "knowledge_code": asset.knowledge_code,
        "title": asset.title,
        "summary": asset.summary or "",
        "knowledge_type": asset.knowledge_type,
        "category": asset.category or "",
        "status": asset.status,
        "visibility": asset.visibility,
        "risk_level": asset.risk_level,
        "current_version_id": asset.current_version_id,
        "owner_employee_id": asset.owner_employee_id or "",
        "owner_department": asset.owner_department or "",
        "created_by": asset.created_by or "",
        "approved_by": asset.approved_by or "",
        "approved_at": asset.approved_at.isoformat() if asset.approved_at else None,
        "published_at": asset.published_at.isoformat() if asset.published_at else None,
        "archived_at": asset.archived_at.isoformat() if asset.archived_at else None,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
        "source_count": asset.source_count,
        "primary_source_count": asset.primary_source_count,
        "cross_validated": asset.cross_validated,
        "conflict_count": asset.conflict_count,
        "unverified_count": asset.unverified_count,
        "evidence_hash": asset.evidence_hash or "",
        "version_number": version.version_number if version else None,
        "version_hash": version.content_hash if version else None,
        "tag_names": tags,
        "citation_count": len(citations),
    }
