from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..config import get_settings
from ..database import get_db
from ..models import User
from ..research_runtime.constants import RESEARCH_EXECUTION_STATUS_LABELS, SOURCE_TYPE_LABELS
from ..research_runtime.models import ResearchClaim, ResearchEvidence, ResearchExecution, ResearchSource


router = APIRouter(prefix="/api/v2/research")
OWNER_ROLES = {"owner", "admin"}


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    settings = get_settings()
    return {
        "ok": True,
        "status": "healthy",
        "capability": "research.public.multi_source",
        "feature_flags": {
            "PUBLIC_RESEARCH_ENABLED": settings.PUBLIC_RESEARCH_ENABLED,
            "PUBLIC_SEARCH_ENABLED": settings.PUBLIC_SEARCH_ENABLED,
        },
    }


@router.get("/executions")
def list_executions(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    rows = db.query(ResearchExecution).order_by(ResearchExecution.created_at.desc()).all()
    return {"items": [execution_to_dict(row, db) for row in rows]}


@router.get("/executions/{execution_id}")
def get_execution(execution_id: str, request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    row = db.get(ResearchExecution, execution_id)
    if not row:
        raise HTTPException(status_code=404, detail="research execution not found")
    return {"execution": execution_to_dict(row, db)}


@router.get("/executions/{execution_id}/sources")
def get_sources(execution_id: str, request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    rows = db.query(ResearchSource).filter(ResearchSource.execution_id == execution_id).order_by(ResearchSource.created_at.asc()).all()
    return {"items": [source_to_dict(row) for row in rows]}


@router.get("/executions/{execution_id}/claims")
def get_claims(execution_id: str, request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    rows = db.query(ResearchClaim).filter(ResearchClaim.execution_id == execution_id).order_by(ResearchClaim.created_at.asc()).all()
    return {"items": [claim_to_dict(row) for row in rows]}


@router.get("/executions/{execution_id}/evidence")
def get_evidence(execution_id: str, request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    rows = db.query(ResearchEvidence).filter(ResearchEvidence.execution_id == execution_id).order_by(ResearchEvidence.created_at.asc()).all()
    return {"items": [evidence_to_dict(row) for row in rows]}


def require_research_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if normalize_role(user.role) not in OWNER_ROLES and user.username != "boss":
        raise HTTPException(status_code=403, detail="无研究中心访问权限")
    return user


def execution_to_dict(row: ResearchExecution, db: Session):
    return {
        "execution_id": row.execution_id,
        "task_id": row.task_id,
        "employee_id": row.employee_id,
        "capability_id": row.capability_id,
        "status": row.status,
        "status_label": RESEARCH_EXECUTION_STATUS_LABELS.get(row.status, row.status),
        "risk_level": row.risk_level,
        "approval_status": row.approval_status,
        "executor_type": row.executor_type,
        "research_topic": row.research_topic,
        "research_goal": row.research_goal,
        "query_count": row.query_count,
        "source_count": row.source_count,
        "valid_source_count": row.valid_source_count,
        "duplicate_count": row.duplicate_count,
        "conclusion_count": row.conclusion_count,
        "conflict_count": row.conflict_count,
        "uncertainty_count": row.uncertainty_count,
        "report_title": row.report_title,
        "report_content": row.report_content,
        "report_hash": row.report_hash,
        "trace_id": row.trace_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "duration_ms": row.duration_ms,
    }


def source_to_dict(row: ResearchSource):
    return {
        "source_id": row.source_id,
        "execution_id": row.execution_id,
        "query_id": row.query_id,
        "source_url": row.source_url,
        "normalized_url": row.normalized_url,
        "redacted_url": row.redacted_url,
        "title": row.title,
        "source_domain": row.source_domain,
        "source_type": row.source_type,
        "source_type_label": SOURCE_TYPE_LABELS.get(row.source_type, row.source_type),
        "confidence_level": row.confidence_level,
        "confidence_score": row.confidence_score,
        "confidence_reason": row.confidence_reason,
        "publication_date": row.publication_date.isoformat() if row.publication_date else None,
        "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
        "content_hash": row.content_hash,
        "summary": row.summary,
        "content_excerpt": row.content_excerpt,
        "is_primary": row.is_primary,
        "duplicate_of_source_id": row.duplicate_of_source_id,
        "provider_name": row.provider_name,
        "validation_status": row.validation_status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def claim_to_dict(row: ResearchClaim):
    return {
        "claim_id": row.claim_id,
        "execution_id": row.execution_id,
        "claim_text": row.claim_text,
        "claim_status": row.claim_status,
        "validation_status": row.validation_status,
        "confidence_level": row.confidence_level,
        "confidence_score": row.confidence_score,
        "support_source_count": row.support_source_count,
        "conflict_source_count": row.conflict_source_count,
        "support_source_ids": _safe_json_list(row.support_source_ids_json),
        "conflict_source_ids": _safe_json_list(row.conflict_source_ids_json),
        "evidence_count": row.evidence_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def evidence_to_dict(row: ResearchEvidence):
    return {
        "evidence_id": row.evidence_id,
        "execution_id": row.execution_id,
        "task_id": row.task_id,
        "source_id": row.source_id,
        "claim_id": row.claim_id,
        "raw_url": row.raw_url,
        "redacted_url": row.redacted_url,
        "page_title": row.page_title,
        "source_type": row.source_type,
        "source_type_label": SOURCE_TYPE_LABELS.get(row.source_type, row.source_type),
        "confidence_level": row.confidence_level,
        "citation_summary": row.citation_summary,
        "evidence_content_hash": row.evidence_content_hash,
        "collected_at": row.collected_at.isoformat() if row.collected_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "relation_type": row.relation_type,
        "validation_status": row.validation_status,
        "trace_id": row.trace_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _safe_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    import json

    try:
        data = json.loads(raw)
    except Exception:
        return []
    return [str(item) for item in data if str(item).strip()] if isinstance(data, list) else []
