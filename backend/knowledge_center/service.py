from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.research_runtime.models import ResearchEvidence, ResearchExecution, ResearchSource

from .citation import hash_query_text
from .exceptions import FeatureDisabledError, KnowledgeConflictError, KnowledgeNotFoundError, KnowledgePermissionError, KnowledgeValidationError
from .models import KnowledgeAsset, KnowledgeCitation, KnowledgeReview, KnowledgeVersion
from .permissions import can_manage_user, knowledge_flags_enabled
from .search import LocalKeywordKnowledgeIndex, QdrantKnowledgeIndex, query_assets, serialize_asset
from .workflow import (
    _asset_to_dict,
    _citation_to_dict,
    _review_to_dict,
    _source_link_to_dict,
    _version_to_dict,
    archive_asset,
    approve_asset,
    create_draft_from_research_report,
    create_manual_draft,
    create_new_version,
    detect_duplicate,
    get_asset_or_404,
    publish_asset,
    record_citation,
    reject_asset,
    restore_version as restore_version_snapshot,
    submit_for_review,
    update_draft,
)


LOCAL_INDEX = LocalKeywordKnowledgeIndex()
VECTOR_INDEX = QdrantKnowledgeIndex()


def ensure_enabled() -> None:
    if not knowledge_flags_enabled():
        raise FeatureDisabledError("知识资产中心未启用")


def knowledge_health(db: Session) -> dict[str, object]:
    settings = get_settings()
    return {
        "ok": True,
        "status": "healthy",
        "feature_flags": {
            "KNOWLEDGE_CENTER_ENABLED": settings.KNOWLEDGE_CENTER_ENABLED,
            "KNOWLEDGE_SUBMISSION_ENABLED": settings.KNOWLEDGE_SUBMISSION_ENABLED,
            "KNOWLEDGE_PUBLISH_ENABLED": settings.KNOWLEDGE_PUBLISH_ENABLED,
            "KNOWLEDGE_LOCAL_SEARCH_ENABLED": settings.KNOWLEDGE_LOCAL_SEARCH_ENABLED,
            "KNOWLEDGE_VECTOR_SEARCH_ENABLED": settings.KNOWLEDGE_VECTOR_SEARCH_ENABLED,
        },
        "knowledge_total": db.query(KnowledgeAsset).count(),
        "pending_review": db.query(KnowledgeAsset).filter(KnowledgeAsset.status.in_(["待审核", "审核中"])).count(),
        "published": db.query(KnowledgeAsset).filter(KnowledgeAsset.status == "已发布").count(),
        "needs_update": db.query(KnowledgeAsset).filter(KnowledgeAsset.status.in_(["已批准", "已发布"])).count(),
        "archived": db.query(KnowledgeAsset).filter(KnowledgeAsset.status == "已归档").count(),
        "recent_submissions": _recent_assets(db),
        "vector_search": VECTOR_INDEX.health_check(),
        "local_search": LOCAL_INDEX.health_check(),
    }


def list_assets(db: Session, *, query: str | None = None, filters: dict[str, object] | None = None, limit: int = 50, include_unpublished: bool = False) -> dict[str, object]:
    assets = query_assets(db, query=query, limit=limit, include_unpublished=include_unpublished, filters=filters or {})
    return {"items": [serialize_asset(asset, db) for asset in assets], "total": len(assets)}


def get_asset(db: Session, knowledge_id: str) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    return {"knowledge": _asset_to_dict(asset, db)}


def create_draft(db: Session, **payload) -> dict[str, object]:
    return create_manual_draft(db, **payload)


def update_asset(db: Session, knowledge_id: str, **payload) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    return update_draft(db, asset, **payload)


def submit_review(db: Session, knowledge_id: str, **payload) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    return submit_for_review(db, asset, **payload)


def approve(db: Session, knowledge_id: str, **payload) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    return approve_asset(db, asset, **payload)


def reject(db: Session, knowledge_id: str, **payload) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    return reject_asset(db, asset, **payload)


def publish(db: Session, knowledge_id: str, **payload) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    return publish_asset(db, asset, **payload)


def archive(db: Session, knowledge_id: str, **payload) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    return archive_asset(db, asset, **payload)


def create_version(db: Session, knowledge_id: str, **payload) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    version = create_new_version(db, asset, **payload)
    db.commit()
    db.refresh(asset)
    db.refresh(version)
    return {"knowledge": _asset_to_dict(asset, db), "version": _version_to_dict(version, db)}


def list_versions(db: Session, knowledge_id: str) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    versions = db.query(KnowledgeVersion).filter(KnowledgeVersion.knowledge_id == asset.knowledge_id).order_by(KnowledgeVersion.created_at.desc()).all()
    return {"items": [_version_to_dict(version, db) for version in versions]}


def get_version(db: Session, knowledge_id: str, version_id: str) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    version = db.get(KnowledgeVersion, version_id)
    if not version or version.knowledge_id != asset.knowledge_id:
        raise KnowledgeNotFoundError("知识版本不存在")
    return {"version": _version_to_dict(version, db)}


def restore_version(db: Session, knowledge_id: str, version_id: str, *, created_by: str, change_summary: str = "从历史版本恢复", change_reason: str = "知识版本回退") -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    version = db.get(KnowledgeVersion, version_id)
    if not version or version.knowledge_id != asset.knowledge_id:
        raise KnowledgeNotFoundError("知识版本不存在")
    restored = restore_version_snapshot(db, asset, version, created_by=created_by, change_summary=change_summary, change_reason=change_reason)
    db.commit()
    db.refresh(asset)
    db.refresh(restored)
    return {"knowledge": _asset_to_dict(asset, db), "version": _version_to_dict(restored, db)}


def list_sources(db: Session, knowledge_id: str) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    rows = db.query(ResearchSource).filter(ResearchSource.execution_id == asset.source_execution_id).order_by(ResearchSource.created_at.asc()).all() if asset.source_execution_id else []
    links = [row for row in db.query(ResearchEvidence).filter(ResearchEvidence.execution_id == asset.source_execution_id).all()] if asset.source_execution_id else []
    return {
        "items": [_source_link_to_dict(link) for link in _collect_source_links(db, asset.knowledge_id)],
        "research_sources": [_research_source_to_dict(row) for row in rows],
        "research_evidence": [_research_evidence_to_dict(row) for row in links],
    }


def list_citations(db: Session, knowledge_id: str) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    citations = db.query(KnowledgeCitation).filter(KnowledgeCitation.knowledge_id == asset.knowledge_id).order_by(KnowledgeCitation.created_at.desc()).all()
    return {"items": [_citation_to_dict(row) for row in citations]}


def submit_research_report(db: Session, report_id: str, *, submitter_employee_code: str, **payload) -> dict[str, object]:
    duplicate = detect_duplicate(
        db,
        title=payload.get("title") or "",
        summary=payload.get("summary"),
        content=(payload.get("content") or ""),
        source_report_id=report_id,
    )
    if duplicate["duplicate"] and duplicate["severity"] == "exact":
        raise KnowledgeConflictError("重复知识候选，已存在相同内容")
    result = create_draft_from_research_report(db, report_id, submitter_employee_code=submitter_employee_code, **payload)
    result["duplicate_hint"] = duplicate
    return result


def search(db: Session, *, query: str | None = None, limit: int = 20, filters: dict[str, object] | None = None, include_unpublished: bool = False) -> dict[str, object]:
    return list_assets(db, query=query, filters=filters, limit=limit, include_unpublished=include_unpublished)


def record_use(db: Session, knowledge_id: str, **payload) -> dict[str, object]:
    asset = get_asset_or_404(db, knowledge_id)
    version = db.get(KnowledgeVersion, asset.current_version_id) if asset.current_version_id else None
    citation = record_citation(db, knowledge_id=asset.knowledge_id, version_id=version.version_id if version else None, **payload)
    db.commit()
    return {"citation": _citation_to_dict(citation)}


def _collect_source_links(db: Session, knowledge_id: str):
    from .models import KnowledgeSourceLink

    return db.query(KnowledgeSourceLink).filter(KnowledgeSourceLink.knowledge_id == knowledge_id).order_by(KnowledgeSourceLink.created_at.asc()).all()


def _research_source_to_dict(row: ResearchSource) -> dict[str, object]:
    return {
        "source_id": row.source_id,
        "title": row.title,
        "url": row.source_url,
        "domain": row.source_domain,
        "source_type": row.source_type,
        "confidence_level": row.confidence_level,
        "confidence_score": row.confidence_score,
        "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
        "content_hash": row.content_hash,
        "is_primary": row.is_primary,
    }


def _research_evidence_to_dict(row: ResearchEvidence) -> dict[str, object]:
    return {
        "evidence_id": row.evidence_id,
        "title": row.page_title,
        "url": row.raw_url,
        "redacted_url": row.redacted_url,
        "source_type": row.source_type,
        "confidence_level": row.confidence_level,
        "summary": row.citation_summary or "",
        "content_hash": row.evidence_content_hash,
        "collected_at": row.collected_at.isoformat() if row.collected_at else None,
        "relation_type": row.relation_type,
        "validation_status": row.validation_status,
    }


def recent_summary(db: Session) -> list[dict[str, object]]:
    return _recent_assets(db)


def _recent_assets(db: Session) -> list[dict[str, object]]:
    rows = db.query(KnowledgeAsset).order_by(KnowledgeAsset.created_at.desc()).limit(5).all()
    return [_asset_to_dict(row, db) for row in rows]
