from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import current_user
from backend.auth_data import normalize_role
from backend.database import get_db
from backend.knowledge_center.exceptions import (
    FeatureDisabledError,
    KnowledgeConflictError,
    KnowledgeNotFoundError,
    KnowledgePermissionError,
    KnowledgeValidationError,
)
from backend.knowledge_center.schemas import (
    KnowledgeCitationCreateRequest,
    KnowledgeDraftCreateRequest,
    KnowledgeDraftUpdateRequest,
    KnowledgeReviewRequest,
    KnowledgeSearchQuery,
    KnowledgeSubmissionRequest,
)
from backend.knowledge_center.service import (
    approve,
    archive,
    create_draft,
    create_version,
    get_asset,
    get_version,
    knowledge_health,
    list_assets,
    list_citations,
    list_sources,
    list_versions,
    publish,
    record_use,
    reject,
    search,
    submit_research_report,
    submit_review,
    ensure_enabled,
    restore_version,
    update_asset,
)


router = APIRouter(prefix="/api/v2/knowledge")
HEALTH_ROUTER = APIRouter(prefix="/api/v2/knowledge-center")
OWNER_ROLES = {"owner", "admin"}


@HEALTH_ROUTER.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    require_knowledge_reader(request, db, require_feature=False)
    return knowledge_health(db)


@router.get("")
def list_knowledge_assets(request: Request, q: str | None = None, category: str | None = None, tag: str | None = None, knowledge_type: str | None = None, status: str | None = None, owner_department: str | None = None, risk_level: str | None = None, min_confidence: int | None = None, limit: int = 50, include_unpublished: bool = False, db: Session = Depends(get_db)):
    require_knowledge_reader(request, db)
    filters = {
        "category": category,
        "tag": tag,
        "knowledge_type": knowledge_type,
        "status": status,
        "owner_department": owner_department,
        "risk_level": risk_level,
        "min_confidence": min_confidence,
    }
    return search(db, query=q, limit=limit, filters=filters, include_unpublished=include_unpublished)


@router.post("")
def create_knowledge_asset(request: Request, payload: KnowledgeDraftCreateRequest, db: Session = Depends(get_db)):
    require_knowledge_manager(request, db)
    return create_draft(
        db,
        title=payload.title,
        summary=payload.summary,
        content=payload.content,
        knowledge_type=payload.knowledge_type,
        category=payload.category,
        visibility=payload.visibility,
        risk_level=payload.risk_level,
        owner_employee_id=payload.owner_employee_id,
        owner_department=payload.owner_department,
        created_by=active_actor(request, db),
        tags=payload.tags,
    )


@router.get("/search")
def search_knowledge_assets(request: Request, q: str | None = None, category: str | None = None, tag: str | None = None, knowledge_type: str | None = None, status: str | None = None, owner_department: str | None = None, risk_level: str | None = None, min_confidence: int | None = None, limit: int = 20, db: Session = Depends(get_db)):
    require_knowledge_reader(request, db)
    return search(
        db,
        query=q,
        limit=limit,
        filters={
            "category": category,
            "tag": tag,
            "knowledge_type": knowledge_type,
            "status": status,
            "owner_department": owner_department,
            "risk_level": risk_level,
            "min_confidence": min_confidence,
        },
    )


@router.get("/{knowledge_id}")
def get_knowledge_asset(knowledge_id: str, request: Request, db: Session = Depends(get_db)):
    require_knowledge_reader(request, db)
    return get_asset(db, knowledge_id)


@router.patch("/{knowledge_id}")
def patch_knowledge_asset(knowledge_id: str, request: Request, payload: KnowledgeDraftUpdateRequest, db: Session = Depends(get_db)):
    require_knowledge_manager(request, db)
    return update_asset(
        db,
        knowledge_id,
        title=payload.title,
        summary=payload.summary,
        knowledge_type=payload.knowledge_type,
        category=payload.category,
        visibility=payload.visibility,
        risk_level=payload.risk_level,
        owner_employee_id=payload.owner_employee_id,
        owner_department=payload.owner_department,
        content=payload.content,
        tags=payload.tags,
        updated_by=active_actor(request, db),
    )


@router.post("/{knowledge_id}/submit-review")
def submit_knowledge_review(knowledge_id: str, request: Request, payload: KnowledgeReviewRequest, db: Session = Depends(get_db)):
    require_knowledge_manager(request, db)
    try:
        return submit_review(
            db,
            knowledge_id,
            reviewer_employee_code=payload.reviewer_employee_code,
            review_comment=payload.review_comment,
            boss_confirmed=payload.boss_confirmed,
            sensitive_check_passed=payload.sensitive_check_passed,
        )
    except KnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KnowledgeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{knowledge_id}/approve")
def approve_knowledge(knowledge_id: str, request: Request, payload: KnowledgeReviewRequest, db: Session = Depends(get_db)):
    require_knowledge_manager(request, db)
    try:
        return approve(
            db,
            knowledge_id,
            reviewer_employee_code=payload.reviewer_employee_code,
            review_comment=payload.review_comment,
            boss_confirmed=payload.boss_confirmed,
            sensitive_check_passed=payload.sensitive_check_passed,
        )
    except KnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KnowledgeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{knowledge_id}/reject")
def reject_knowledge(knowledge_id: str, request: Request, payload: KnowledgeReviewRequest, db: Session = Depends(get_db)):
    require_knowledge_manager(request, db)
    try:
        return reject(
            db,
            knowledge_id,
            reviewer_employee_code=payload.reviewer_employee_code,
            review_comment=payload.review_comment,
            boss_confirmed=payload.boss_confirmed,
            sensitive_check_passed=payload.sensitive_check_passed,
        )
    except KnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{knowledge_id}/publish")
def publish_knowledge(knowledge_id: str, request: Request, payload: KnowledgeReviewRequest, db: Session = Depends(get_db)):
    require_knowledge_manager(request, db)
    try:
        return publish(
            db,
            knowledge_id,
            publisher_employee_code=payload.reviewer_employee_code,
            review_comment=payload.review_comment,
            boss_confirmed=payload.boss_confirmed,
            sensitive_check_passed=payload.sensitive_check_passed,
        )
    except KnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KnowledgeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{knowledge_id}/archive")
def archive_knowledge(knowledge_id: str, request: Request, payload: KnowledgeReviewRequest, db: Session = Depends(get_db)):
    require_knowledge_manager(request, db)
    try:
        return archive(db, knowledge_id, archiver_employee_code=payload.reviewer_employee_code, review_comment=payload.review_comment)
    except KnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{knowledge_id}/versions")
def knowledge_versions(knowledge_id: str, request: Request, db: Session = Depends(get_db)):
    require_knowledge_reader(request, db)
    return list_versions(db, knowledge_id)


@router.get("/{knowledge_id}/versions/{version_id}")
def knowledge_version_detail(knowledge_id: str, version_id: str, request: Request, db: Session = Depends(get_db)):
    require_knowledge_reader(request, db)
    return get_version(db, knowledge_id, version_id)


@router.post("/{knowledge_id}/versions")
def create_knowledge_version(knowledge_id: str, request: Request, payload: KnowledgeDraftCreateRequest, db: Session = Depends(get_db)):
    require_knowledge_manager(request, db)
    return create_version(
        db,
        knowledge_id,
        title=payload.title,
        summary=payload.summary,
        content=payload.content,
        change_summary="创建知识新版本",
        change_reason="手动新版本",
        source_type="manual",
        source_execution_id=None,
        source_report_id=None,
        created_by=active_actor(request, db),
    )


@router.post("/{knowledge_id}/versions/{version_id}/restore")
def restore_knowledge_version(knowledge_id: str, version_id: str, request: Request, db: Session = Depends(get_db)):
    require_knowledge_manager(request, db)
    try:
        return restore_version(db, knowledge_id, version_id, created_by=active_actor(request, db))
    except KnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{knowledge_id}/sources")
def knowledge_sources(knowledge_id: str, request: Request, db: Session = Depends(get_db)):
    require_knowledge_reader(request, db)
    return list_sources(db, knowledge_id)


@router.get("/{knowledge_id}/citations")
def knowledge_citations(knowledge_id: str, request: Request, db: Session = Depends(get_db)):
    require_knowledge_reader(request, db)
    return list_citations(db, knowledge_id)


@router.post("/{knowledge_id}/cite")
def cite_knowledge(knowledge_id: str, payload: KnowledgeCitationCreateRequest, request: Request, db: Session = Depends(get_db)):
    require_knowledge_reader(request, db)
    return record_use(
        db,
        knowledge_id,
        task_id=payload.task_id,
        execution_id=payload.execution_id,
        employee_id=payload.employee_id,
        usage_type=payload.usage_type,
        query_text=payload.query_text,
        citation_summary=payload.citation_summary,
        chunk_id=payload.chunk_id,
    )


@router.post("/search")
def search_knowledge_assets_post(request: Request, payload: KnowledgeSearchQuery, db: Session = Depends(get_db)):
    require_knowledge_reader(request, db)
    return search(
        db,
        query=payload.q,
        limit=payload.limit,
        filters={
            "category": payload.category,
            "tag": payload.tag,
            "knowledge_type": payload.knowledge_type,
            "status": payload.status,
            "owner_department": payload.owner_department,
            "risk_level": payload.risk_level,
            "min_confidence": payload.min_confidence,
        },
    )


@router.post("/research/{report_id}/submit-to-knowledge")
def submit_report_to_knowledge(report_id: str, payload: KnowledgeSubmissionRequest, request: Request, db: Session = Depends(get_db)):
    require_knowledge_manager(request, db)
    try:
        return submit_research_report(
            db,
            report_id,
            submitter_employee_code=payload.submitter_employee_code,
            title=payload.title,
            summary=payload.summary,
            knowledge_type=payload.knowledge_type,
            category=payload.category,
            visibility=payload.visibility,
            owner_employee_id=payload.owner_employee_id,
            owner_department=payload.owner_department,
            tags=payload.tags,
        )
    except KnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KnowledgeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def require_knowledge_reader(request: Request, db: Session, require_feature: bool = True):
    if require_feature:
        require_knowledge_feature_enabled()
    user = current_user(request, db)
    if normalize_role(user.role) in OWNER_ROLES:
        return user
    permissions = _permissions_for_user(db, user)
    if "knowledge.read" not in permissions and "knowledge.manage" not in permissions:
        raise HTTPException(status_code=403, detail="没有知识资产访问权限")
    return user


def require_knowledge_manager(request: Request, db: Session):
    require_knowledge_feature_enabled()
    user = current_user(request, db)
    if normalize_role(user.role) in OWNER_ROLES:
        return user
    permissions = _permissions_for_user(db, user)
    if "knowledge.manage" not in permissions:
        raise HTTPException(status_code=403, detail="没有知识资产管理权限")
    return user


def require_knowledge_feature_enabled():
    try:
        ensure_enabled()
    except FeatureDisabledError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _permissions_for_user(db: Session, user) -> set[str]:
    from backend.auth import get_role_permissions

    return get_role_permissions(db, normalize_role(user.role))


def active_actor(request: Request, db: Session) -> str:
    user = current_user(request, db)
    return normalize_role(user.role) or user.username
