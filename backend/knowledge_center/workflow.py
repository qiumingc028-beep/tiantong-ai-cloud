from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.ai_employees.registry import normalize_employee_code, employee_name
from backend.models import TaskCenterTask
from backend.research_runtime.models import ResearchEvidence, ResearchExecution, ResearchSource

from .citation import citation_payload, hash_query_text
from .chunking import chunk_text
from .constants import (
    DEFAULT_CATEGORY_SUGGESTIONS,
    DEFAULT_TAGS,
    KNOWLEDGE_RISK_LEVELS,
    KNOWLEDGE_STATUSES,
    KNOWLEDGE_TYPES,
)
from .exceptions import KnowledgeConflictError, KnowledgeNotFoundError, KnowledgePermissionError, KnowledgeValidationError
from .models import (
    KnowledgeAsset,
    KnowledgeCitation,
    KnowledgeChunk,
    KnowledgeReview,
    KnowledgeSourceLink,
    KnowledgeTag,
    KnowledgeTagRelation,
    KnowledgeVersion,
)
from .permissions import (
    can_archive_employee,
    can_manage_user,
    can_publish_employee,
    can_review_employee,
    can_submit_employee,
)
from .sanitizer import detect_prompt_injection, normalize_text, redact_sensitive_text, redact_url, stable_text_hash, strip_html_like_noise
from .versioning import next_version_number


def generate_knowledge_code(title: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in normalize_text(title)[:32]).strip("-").lower() or "knowledge"
    return f"knw-{slug}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"


def suggest_category(title: str, summary: str | None, content: str | None) -> str:
    source = f"{title} {summary or ''} {content or ''}"
    for keyword, category in DEFAULT_CATEGORY_SUGGESTIONS.items():
        if keyword in source:
            return category
    return "其他"


def suggest_tags(title: str, summary: str | None, content: str | None, source_tags: list[str] | None = None) -> list[str]:
    tags = list(dict.fromkeys([*(source_tags or []), *DEFAULT_TAGS.get(suggest_category(title, summary, content), ["知识"])]))
    return [tag for tag in tags if tag]


def infer_risk_level(category: str | None, source_count: int, conflict_count: int, prompt_injection: bool) -> str:
    if prompt_injection:
        return "高风险"
    if conflict_count > 0:
        return "中风险"
    if source_count < 2:
        return "中风险"
    if category in {"法务规则", "财务规则", "安全规则"}:
        return "高风险"
    return "低风险"


def create_draft_from_research_report(
    db: Session,
    report_id: str,
    *,
    submitter_employee_code: str,
    title: str | None = None,
    summary: str | None = None,
    knowledge_type: str = "研究报告",
    category: str | None = None,
    visibility: str = "部门可见",
    owner_employee_id: str | None = None,
    owner_department: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, object]:
    submitter_result = can_submit_employee(submitter_employee_code)
    if not submitter_result.allowed:
        raise KnowledgePermissionError(submitter_result.reason)
    execution = db.get(ResearchExecution, report_id)
    if not execution:
        raise KnowledgeNotFoundError("研究报告不存在")

    source_sources = db.query(ResearchSource).filter(ResearchSource.execution_id == execution.execution_id).all()
    source_evidence = db.query(ResearchEvidence).filter(ResearchEvidence.execution_id == execution.execution_id).all()
    source_hash = stable_text_hash("|".join(sorted(row.content_hash for row in source_sources if row.content_hash)))
    report_content = execution.report_content or ""
    safe_content = redact_sensitive_text(strip_html_like_noise(report_content))
    prompt_injection_detected = detect_prompt_injection(report_content)
    if not title:
        title = execution.report_title or execution.research_topic or "未命名知识"
    if not summary:
        summary = redact_sensitive_text(normalize_text((report_content or execution.research_goal or "")[:240]) or execution.research_goal[:240])
    category = category or suggest_category(title, summary, report_content)
    safe_tags = suggest_tags(title, summary, report_content, tags)
    source_count = len(source_sources)
    conflict_count = len([row for row in source_sources if row.validation_status not in {"已交叉验证", "交叉验证通过"}])
    risk_level = infer_risk_level(category, source_count, conflict_count, prompt_injection_detected)
    knowledge_id = str(uuid4())
    knowledge_code = generate_knowledge_code(title)
    created_at = datetime.now(timezone.utc)
    asset = KnowledgeAsset(
        knowledge_id=knowledge_id,
        knowledge_code=knowledge_code,
        title=title,
        summary=summary,
        knowledge_type=knowledge_type,
        category=category,
        status="草稿",
        visibility=visibility,
        risk_level=risk_level,
        owner_employee_id=owner_employee_id or submitter_employee_code,
        owner_department=owner_department or "数据资产军团",
        created_by=submitter_employee_code,
        source_report_id=execution.execution_id,
        source_execution_id=execution.execution_id,
        source_count=source_count,
        primary_source_count=len([row for row in source_sources if row.is_primary]),
        cross_validated=all(row.validation_status == "已交叉验证" for row in source_sources) if source_sources else False,
        conflict_count=conflict_count,
        unverified_count=len([row for row in source_sources if row.validation_status != "已交叉验证"]),
        evidence_hash=source_hash,
        created_at=created_at,
        updated_at=created_at,
    )
    version = _create_version(
        asset.knowledge_id,
        title=title,
        summary=summary,
        content=safe_content or report_content,
        content_format="markdown",
        change_summary="由多来源研究报告自动生成知识候选",
        change_reason="天采提交知识候选",
        source_type="research_report",
        source_execution_id=execution.execution_id,
        source_report_id=execution.execution_id,
        created_by=submitter_employee_code,
    )
    asset.current_version_id = version["version_id"]
    db.add(asset)
    db.flush()
    version_row = _persist_version(db, version)
    _persist_tags(db, asset.knowledge_id, version_row.version_id, safe_tags)
    _persist_sources(db, asset.knowledge_id, version_row.version_id, execution, source_sources, source_evidence)
    _persist_reviews(
        db,
        asset.knowledge_id,
        version_row.version_id,
        submitter_employee_code=submitter_employee_code,
        prompt_injection_detected=prompt_injection_detected,
        risk_level=risk_level,
        source_count=source_count,
        conflict_count=conflict_count,
    )
    _index_chunks(db, asset.knowledge_id, version_row.version_id, version_row.content)
    db.commit()
    db.refresh(asset)
    db.refresh(version_row)
    return {
        "knowledge": _asset_to_dict(asset, db),
        "version": _version_to_dict(version_row, db),
        "source_count": source_count,
        "primary_source_count": asset.primary_source_count,
        "prompt_injection_detected": prompt_injection_detected,
        "tags": safe_tags,
    }


def create_manual_draft(
    db: Session,
    *,
    title: str,
    summary: str | None,
    content: str,
    knowledge_type: str,
    category: str | None,
    visibility: str,
    risk_level: str,
    owner_employee_id: str | None,
    owner_department: str | None,
    created_by: str,
    tags: list[str] | None,
) -> dict[str, object]:
    knowledge_id = str(uuid4())
    knowledge_code = generate_knowledge_code(title)
    safe_content = redact_sensitive_text(strip_html_like_noise(content))
    candidate_tags = suggest_tags(title, summary, safe_content, tags)
    version = _create_version(
        knowledge_id,
        title=title,
        summary=summary,
        content=safe_content,
        content_format="markdown",
        change_summary="创建知识草稿",
        change_reason="手动创建",
        source_type="manual",
        source_execution_id=None,
        source_report_id=None,
        created_by=created_by,
    )
    asset = KnowledgeAsset(
        knowledge_id=knowledge_id,
        knowledge_code=knowledge_code,
        title=title,
        summary=summary,
        knowledge_type=knowledge_type,
        category=category or suggest_category(title, summary, safe_content),
        status="草稿",
        visibility=visibility,
        risk_level=risk_level,
        owner_employee_id=owner_employee_id,
        owner_department=owner_department,
        created_by=created_by,
        source_count=0,
        primary_source_count=0,
        cross_validated=False,
        conflict_count=0,
        unverified_count=0,
    )
    asset.current_version_id = version["version_id"]
    db.add(asset)
    db.flush()
    version_row = _persist_version(db, version)
    _persist_tags(db, asset.knowledge_id, version_row.version_id, candidate_tags)
    _index_chunks(db, asset.knowledge_id, version_row.version_id, version_row.content)
    db.commit()
    db.refresh(asset)
    return {"knowledge": _asset_to_dict(asset, db), "version": _version_to_dict(version_row, db)}


def update_draft(
    db: Session,
    asset: KnowledgeAsset,
    *,
    title: str | None = None,
    summary: str | None = None,
    knowledge_type: str | None = None,
    category: str | None = None,
    visibility: str | None = None,
    risk_level: str | None = None,
    owner_employee_id: str | None = None,
    owner_department: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
    updated_by: str | None = None,
) -> dict[str, object]:
    if asset.status not in {"草稿", "已驳回", "待审核"}:
        raise KnowledgeConflictError("只有草稿或驳回状态的知识可以编辑")
    if title is not None:
        asset.title = title
    if summary is not None:
        asset.summary = summary
    if knowledge_type is not None:
        asset.knowledge_type = knowledge_type
    if category is not None:
        asset.category = category
    if visibility is not None:
        asset.visibility = visibility
    if risk_level is not None:
        asset.risk_level = risk_level
    if owner_employee_id is not None:
        asset.owner_employee_id = owner_employee_id
    if owner_department is not None:
        asset.owner_department = owner_department
    asset.updated_at = datetime.now(timezone.utc)
    db.flush()
    version = db.get(KnowledgeVersion, asset.current_version_id) if asset.current_version_id else None
    if version and content is not None:
        version.content = redact_sensitive_text(strip_html_like_noise(content))
        version.content_hash = stable_text_hash(version.content)
        version.summary = asset.summary
        version.title = asset.title
        version.version_number = version.version_number or "1"
        db.flush()
        db.query(KnowledgeChunk).filter(KnowledgeChunk.version_id == version.version_id).delete()
        _index_chunks(db, asset.knowledge_id, version.version_id, version.content)
    if tags is not None:
        db.query(KnowledgeTagRelation).filter(KnowledgeTagRelation.knowledge_id == asset.knowledge_id).delete()
        _persist_tags(db, asset.knowledge_id, asset.current_version_id, tags)
    db.commit()
    db.refresh(asset)
    return {"knowledge": _asset_to_dict(asset, db)}


def submit_for_review(
    db: Session,
    asset: KnowledgeAsset,
    *,
    reviewer_employee_code: str,
    review_comment: str | None = None,
    boss_confirmed: bool = False,
    sensitive_check_passed: bool = True,
) -> dict[str, object]:
    reviewer = can_review_employee(reviewer_employee_code)
    if not reviewer.allowed and reviewer_employee_code != asset.owner_employee_id:
        raise KnowledgePermissionError(reviewer.reason)
    asset.status = "待审核"
    review = KnowledgeReview(
        review_id=str(uuid4()),
        knowledge_id=asset.knowledge_id,
        version_id=asset.current_version_id,
        review_stage="提交审核",
        review_status="审核中",
        reviewer_employee_code=normalize_employee_code(reviewer_employee_code) or reviewer_employee_code,
        reviewer_name=employee_name(reviewer_employee_code) or reviewer_employee_code,
        review_comment=review_comment,
        risk_level=asset.risk_level,
        source_check_result=json.dumps({"source_count": asset.source_count, "primary_source_count": asset.primary_source_count, "cross_validated": asset.cross_validated}, ensure_ascii=False),
        sensitive_check_result=json.dumps({"passed": sensitive_check_passed}, ensure_ascii=False),
        prompt_injection_detected=False,
        boss_confirmed=boss_confirmed,
    )
    db.add(review)
    db.commit()
    db.refresh(asset)
    return {"knowledge": _asset_to_dict(asset, db), "review": _review_to_dict(review)}


def approve_asset(
    db: Session,
    asset: KnowledgeAsset,
    *,
    reviewer_employee_code: str,
    review_comment: str | None = None,
    boss_confirmed: bool = False,
    sensitive_check_passed: bool = True,
) -> dict[str, object]:
    reviewer = can_review_employee(reviewer_employee_code)
    if not reviewer.allowed and reviewer_employee_code != asset.owner_employee_id:
        raise KnowledgePermissionError(reviewer.reason)
    if asset.risk_level in {"高风险", "极高风险"} and not boss_confirmed:
        raise KnowledgeValidationError("高风险知识必须由老板确认")
    asset.status = "已批准"
    asset.approved_by = normalize_employee_code(reviewer_employee_code) or reviewer_employee_code
    asset.approved_at = datetime.now(timezone.utc)
    review = KnowledgeReview(
        review_id=str(uuid4()),
        knowledge_id=asset.knowledge_id,
        version_id=asset.current_version_id,
        review_stage="审核",
        review_status="已批准",
        reviewer_employee_code=normalize_employee_code(reviewer_employee_code) or reviewer_employee_code,
        reviewer_name=employee_name(reviewer_employee_code) or reviewer_employee_code,
        review_comment=review_comment or "已批准",
        risk_level=asset.risk_level,
        source_check_result=json.dumps({"source_count": asset.source_count, "primary_source_count": asset.primary_source_count, "cross_validated": asset.cross_validated}, ensure_ascii=False),
        sensitive_check_result=json.dumps({"passed": sensitive_check_passed}, ensure_ascii=False),
        prompt_injection_detected=False,
        boss_confirmed=boss_confirmed,
    )
    db.add(review)
    db.commit()
    db.refresh(asset)
    return {"knowledge": _asset_to_dict(asset, db), "review": _review_to_dict(review)}


def reject_asset(
    db: Session,
    asset: KnowledgeAsset,
    *,
    reviewer_employee_code: str,
    review_comment: str | None = None,
    boss_confirmed: bool = False,
    sensitive_check_passed: bool = True,
) -> dict[str, object]:
    reviewer = can_review_employee(reviewer_employee_code)
    if not reviewer.allowed and reviewer_employee_code != asset.owner_employee_id:
        raise KnowledgePermissionError(reviewer.reason)
    asset.status = "已驳回"
    review = KnowledgeReview(
        review_id=str(uuid4()),
        knowledge_id=asset.knowledge_id,
        version_id=asset.current_version_id,
        review_stage="审核",
        review_status="已驳回",
        reviewer_employee_code=normalize_employee_code(reviewer_employee_code) or reviewer_employee_code,
        reviewer_name=employee_name(reviewer_employee_code) or reviewer_employee_code,
        review_comment=review_comment or "已驳回",
        risk_level=asset.risk_level,
        source_check_result=json.dumps({"source_count": asset.source_count, "primary_source_count": asset.primary_source_count, "cross_validated": asset.cross_validated}, ensure_ascii=False),
        sensitive_check_result=json.dumps({"passed": sensitive_check_passed}, ensure_ascii=False),
        prompt_injection_detected=False,
        boss_confirmed=boss_confirmed,
    )
    db.add(review)
    db.commit()
    db.refresh(asset)
    return {"knowledge": _asset_to_dict(asset, db), "review": _review_to_dict(review)}


def publish_asset(
    db: Session,
    asset: KnowledgeAsset,
    *,
    publisher_employee_code: str,
    review_comment: str | None = None,
    boss_confirmed: bool = False,
    sensitive_check_passed: bool = True,
) -> dict[str, object]:
    publisher = can_publish_employee(publisher_employee_code)
    if not publisher.allowed and publisher_employee_code != asset.owner_employee_id:
        raise KnowledgePermissionError(publisher.reason)
    if asset.status not in {"已批准", "待审核"} and not boss_confirmed:
        raise KnowledgeValidationError("知识发布前必须完成批准")
    if asset.status == "已发布":
        raise KnowledgeConflictError("知识已经发布，不能重复发布")
    asset.status = "已发布"
    asset.published_at = datetime.now(timezone.utc)
    asset.approved_by = normalize_employee_code(publisher_employee_code) or publisher_employee_code
    asset.approved_at = asset.approved_at or asset.published_at
    version = db.get(KnowledgeVersion, asset.current_version_id) if asset.current_version_id else None
    if version:
        version.approved_by = normalize_employee_code(publisher_employee_code) or publisher_employee_code
        version.approved_at = asset.published_at
        db.flush()
        db.query(KnowledgeChunk).filter(KnowledgeChunk.version_id == version.version_id).delete()
        _index_chunks(db, asset.knowledge_id, version.version_id, version.content)
    review = KnowledgeReview(
        review_id=str(uuid4()),
        knowledge_id=asset.knowledge_id,
        version_id=asset.current_version_id,
        review_stage="发布",
        review_status="已发布",
        reviewer_employee_code=normalize_employee_code(publisher_employee_code) or publisher_employee_code,
        reviewer_name=employee_name(publisher_employee_code) or publisher_employee_code,
        review_comment=review_comment or "已发布",
        risk_level=asset.risk_level,
        source_check_result=json.dumps({"source_count": asset.source_count, "primary_source_count": asset.primary_source_count, "cross_validated": asset.cross_validated}, ensure_ascii=False),
        sensitive_check_result=json.dumps({"passed": sensitive_check_passed}, ensure_ascii=False),
        prompt_injection_detected=False,
        boss_confirmed=boss_confirmed,
    )
    db.add(review)
    db.commit()
    db.refresh(asset)
    return {"knowledge": _asset_to_dict(asset, db), "review": _review_to_dict(review)}


def archive_asset(
    db: Session,
    asset: KnowledgeAsset,
    *,
    archiver_employee_code: str,
    review_comment: str | None = None,
) -> dict[str, object]:
    archiver = can_archive_employee(archiver_employee_code)
    if not archiver.allowed and archiver_employee_code != asset.owner_employee_id:
        raise KnowledgePermissionError(archiver.reason)
    asset.status = "已归档"
    asset.archived_at = datetime.now(timezone.utc)
    review = KnowledgeReview(
        review_id=str(uuid4()),
        knowledge_id=asset.knowledge_id,
        version_id=asset.current_version_id,
        review_stage="归档",
        review_status="已归档",
        reviewer_employee_code=normalize_employee_code(archiver_employee_code) or archiver_employee_code,
        reviewer_name=employee_name(archiver_employee_code) or archiver_employee_code,
        review_comment=review_comment or "已归档",
        risk_level=asset.risk_level,
        source_check_result="{}",
        sensitive_check_result="{}",
        prompt_injection_detected=False,
        boss_confirmed=False,
    )
    db.add(review)
    db.commit()
    db.refresh(asset)
    return {"knowledge": _asset_to_dict(asset, db), "review": _review_to_dict(review)}


def record_citation(
    db: Session,
    *,
    knowledge_id: str,
    version_id: str | None,
    chunk_id: str | None,
    task_id: int | None,
    execution_id: str | None,
    employee_id: str | None,
    usage_type: str,
    query_text: str | None,
    citation_summary: str | None,
) -> KnowledgeCitation:
    payload = citation_payload(
        knowledge_id=knowledge_id,
        version_id=version_id or "",
        chunk_id=chunk_id,
        task_id=task_id,
        execution_id=execution_id,
        employee_id=employee_id,
        usage_type=usage_type,
        query_text=query_text,
        citation_summary=citation_summary,
    )
    row = KnowledgeCitation(**payload)
    db.add(row)
    db.flush()
    return row


def _create_version(
    knowledge_id: str,
    *,
    title: str,
    summary: str | None,
    content: str,
    content_format: str,
    change_summary: str,
    change_reason: str,
    source_type: str,
    source_execution_id: str | None,
    source_report_id: str | None,
    created_by: str | None,
) -> dict[str, object]:
    return {
        "version_id": str(uuid4()),
        "knowledge_id": knowledge_id,
        "version_number": "1",
        "title": title,
        "summary": summary,
        "content": content,
        "content_format": content_format,
        "change_summary": change_summary,
        "change_reason": change_reason,
        "source_type": source_type,
        "source_execution_id": source_execution_id,
        "source_report_id": source_report_id,
        "content_hash": stable_text_hash(content),
        "created_by": created_by,
        "reviewed_by": None,
        "approved_by": None,
        "created_at": datetime.now(timezone.utc),
        "approved_at": None,
    }


def create_new_version(
    db: Session,
    asset: KnowledgeAsset,
    *,
    title: str | None = None,
    summary: str | None = None,
    content: str,
    change_summary: str,
    change_reason: str,
    source_type: str,
    source_execution_id: str | None,
    source_report_id: str | None,
    created_by: str | None,
    reviewed_by: str | None = None,
    approved_by: str | None = None,
) -> KnowledgeVersion:
    versions = db.query(KnowledgeVersion).filter(KnowledgeVersion.knowledge_id == asset.knowledge_id).all()
    version_payload = _create_version(
        asset.knowledge_id,
        title=title or asset.title,
        summary=summary or asset.summary,
        content=redact_sensitive_text(strip_html_like_noise(content)),
        content_format="markdown",
        change_summary=change_summary,
        change_reason=change_reason,
        source_type=source_type,
        source_execution_id=source_execution_id,
        source_report_id=source_report_id,
        created_by=created_by,
    )
    version_payload["version_number"] = next_version_number(v.version_number for v in versions)
    version_payload["reviewed_by"] = reviewed_by
    version_payload["approved_by"] = approved_by
    version_payload["approved_at"] = datetime.now(timezone.utc) if approved_by else None
    row = _persist_version(db, version_payload)
    asset.current_version_id = row.version_id
    asset.title = version_payload["title"]  # type: ignore[assignment]
    asset.summary = version_payload["summary"]  # type: ignore[assignment]
    asset.updated_at = datetime.now(timezone.utc)
    db.flush()
    _index_chunks(db, asset.knowledge_id, row.version_id, row.content)
    return row


def create_version_snapshot(
    db: Session,
    asset: KnowledgeAsset,
    *,
    created_by: str,
    change_summary: str,
    change_reason: str,
) -> KnowledgeVersion:
    current = db.get(KnowledgeVersion, asset.current_version_id) if asset.current_version_id else None
    if not current:
        raise KnowledgeNotFoundError("当前版本不存在")
    return create_new_version(
        db,
        asset,
        title=current.title,
        summary=current.summary,
        content=current.content,
        change_summary=change_summary,
        change_reason=change_reason,
        source_type=current.source_type or "manual",
        source_execution_id=current.source_execution_id,
        source_report_id=current.source_report_id,
        created_by=created_by,
        reviewed_by=current.reviewed_by,
        approved_by=current.approved_by,
    )


def restore_version(
    db: Session,
    asset: KnowledgeAsset,
    version: KnowledgeVersion,
    *,
    created_by: str,
    change_summary: str,
    change_reason: str,
) -> KnowledgeVersion:
    restored = create_new_version(
        db,
        asset,
        title=version.title,
        summary=version.summary,
        content=version.content,
        change_summary=change_summary,
        change_reason=change_reason,
        source_type=version.source_type or "manual",
        source_execution_id=version.source_execution_id,
        source_report_id=version.source_report_id,
        created_by=created_by,
        reviewed_by=version.reviewed_by,
        approved_by=version.approved_by,
    )
    return restored


def _persist_version(db: Session, payload: dict[str, object]) -> KnowledgeVersion:
    row = KnowledgeVersion(**payload)
    db.add(row)
    db.flush()
    return row


def _persist_tags(db: Session, knowledge_id: str, version_id: str | None, tags: list[str]) -> None:
    normalized = []
    for idx, tag_name in enumerate(dict.fromkeys([t.strip() for t in tags if t and t.strip()]), start=1):
        tag_code = "".join(ch if ch.isalnum() else "_" for ch in tag_name).strip("_").lower() or f"tag_{idx}"
        tag = db.query(KnowledgeTag).filter(KnowledgeTag.tag_name == tag_name).one_or_none()
        if not tag:
            tag = KnowledgeTag(tag_id=str(uuid4()), tag_code=tag_code, tag_name=tag_name, tag_group="分类", enabled=True)
            db.add(tag)
            db.flush()
        normalized.append(tag)
    for tag in normalized:
        db.add(
            KnowledgeTagRelation(
                relation_id=str(uuid4()),
                knowledge_id=knowledge_id,
                version_id=version_id,
                tag_id=tag.tag_id,
            )
        )
    db.flush()


def _persist_sources(
    db: Session,
    knowledge_id: str,
    version_id: str,
    execution: ResearchExecution,
    sources: list[ResearchSource],
    evidence: list[ResearchEvidence],
) -> None:
    for row in sources:
        db.add(
            KnowledgeSourceLink(
                link_id=str(uuid4()),
                knowledge_id=knowledge_id,
                version_id=version_id,
                source_kind="Research Source",
                source_ref_id=row.source_id,
                source_title=row.title,
                source_url=row.source_url,
                source_hash=row.content_hash,
                source_confidence_level=row.confidence_level,
                source_confidence_score=row.confidence_score,
                source_is_primary=row.is_primary,
                source_checked=True,
                evidence_id=None,
                note=row.summary or row.content_excerpt or "",
            )
        )
    db.add(
        KnowledgeSourceLink(
            link_id=str(uuid4()),
            knowledge_id=knowledge_id,
            version_id=version_id,
            source_kind="Research Report",
            source_ref_id=execution.execution_id,
            source_title=execution.report_title,
            source_url="",
            source_hash=execution.report_hash,
            source_confidence_level="高",
            source_confidence_score=90,
            source_is_primary=True,
            source_checked=True,
            evidence_id=None,
            note=execution.report_content or "",
        )
    )
    db.add(
        KnowledgeSourceLink(
            link_id=str(uuid4()),
            knowledge_id=knowledge_id,
            version_id=version_id,
            source_kind="Research Execution",
            source_ref_id=execution.execution_id,
            source_title=execution.research_topic,
            source_url="",
            source_hash=execution.report_hash,
            source_confidence_level="高",
            source_confidence_score=90,
            source_is_primary=True,
            source_checked=True,
            evidence_id=None,
            note=execution.research_goal,
        )
    )
    for item in evidence:
        db.add(
            KnowledgeSourceLink(
                link_id=str(uuid4()),
                knowledge_id=knowledge_id,
                version_id=version_id,
                source_kind="Research Evidence",
                source_ref_id=item.evidence_id,
                source_title=item.page_title,
                source_url=item.raw_url,
                source_hash=item.evidence_content_hash,
                source_confidence_level=item.confidence_level,
                source_confidence_score=80,
                source_is_primary=False,
                source_checked=True,
                evidence_id=item.evidence_id,
                note=item.citation_summary or "",
            )
        )
    db.flush()


def _persist_reviews(
    db: Session,
    knowledge_id: str,
    version_id: str,
    *,
    submitter_employee_code: str,
    prompt_injection_detected: bool,
    risk_level: str,
    source_count: int,
    conflict_count: int,
) -> None:
    db.add(
        KnowledgeReview(
            review_id=str(uuid4()),
            knowledge_id=knowledge_id,
            version_id=version_id,
            review_stage="来源校验",
            review_status="审核中",
            reviewer_employee_code=submitter_employee_code,
            reviewer_name=employee_name(submitter_employee_code) or submitter_employee_code,
            review_comment="知识候选已创建，等待天藏审核。",
            risk_level=risk_level,
            source_check_result=json.dumps({"source_count": source_count, "conflict_count": conflict_count}, ensure_ascii=False),
            sensitive_check_result=json.dumps({"passed": not prompt_injection_detected}, ensure_ascii=False),
            prompt_injection_detected=prompt_injection_detected,
            boss_confirmed=False,
        )
    )
    db.flush()


def _index_chunks(db: Session, knowledge_id: str, version_id: str, content: str) -> None:
    for chunk in chunk_text(content):
        db.add(
            KnowledgeChunk(
                chunk_id=f"chunk-{version_id}-{chunk['chunk_index']}",
                knowledge_id=knowledge_id,
                version_id=version_id,
                chunk_index=int(chunk["chunk_index"]),
                heading=str(chunk["heading"]),
                content=str(chunk["content"]),
                token_estimate=int(chunk["token_estimate"]),
                content_hash=str(chunk["content_hash"]),
                metadata_json=json.dumps(chunk["metadata"], ensure_ascii=False),
            )
        )
    db.flush()


def _asset_to_dict(asset: KnowledgeAsset, db: Session | None = None) -> dict[str, object]:
    version = db.get(KnowledgeVersion, asset.current_version_id) if db and asset.current_version_id else None
    tags = []
    reviews = []
    links = []
    citations = []
    if db:
        tags = [
            relation.tag.tag_name
            for relation in db.query(KnowledgeTagRelation).filter(KnowledgeTagRelation.knowledge_id == asset.knowledge_id).all()
            if relation.tag and relation.tag.enabled
        ]
        reviews = db.query(KnowledgeReview).filter(KnowledgeReview.knowledge_id == asset.knowledge_id).order_by(KnowledgeReview.created_at.asc()).all()
        links = db.query(KnowledgeSourceLink).filter(KnowledgeSourceLink.knowledge_id == asset.knowledge_id).order_by(KnowledgeSourceLink.created_at.asc()).all()
        citations = db.query(KnowledgeCitation).filter(KnowledgeCitation.knowledge_id == asset.knowledge_id).order_by(KnowledgeCitation.created_at.asc()).all()
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
        "tags": tags,
        "review_count": len(reviews),
        "source_links_count": len(links),
        "citation_count": len(citations),
        "current_version": _version_to_dict(version, db) if version else None,
        "reviews": [_review_to_dict(row) for row in reviews],
        "sources": [_source_link_to_dict(row) for row in links],
        "citations": [_citation_to_dict(row) for row in citations],
    }


def _version_to_dict(version: KnowledgeVersion | None, db: Session | None = None) -> dict[str, object] | None:
    if not version:
        return None
    chunks = []
    if db:
        chunks = [_chunk_to_dict(row) for row in db.query(KnowledgeChunk).filter(KnowledgeChunk.version_id == version.version_id).order_by(KnowledgeChunk.chunk_index.asc()).all()]
    return {
        "version_id": version.version_id,
        "knowledge_id": version.knowledge_id,
        "version_number": version.version_number,
        "title": version.title,
        "summary": version.summary or "",
        "content": version.content,
        "content_format": version.content_format,
        "change_summary": version.change_summary or "",
        "change_reason": version.change_reason or "",
        "source_type": version.source_type or "",
        "source_execution_id": version.source_execution_id or "",
        "source_report_id": version.source_report_id or "",
        "content_hash": version.content_hash,
        "created_by": version.created_by or "",
        "reviewed_by": version.reviewed_by or "",
        "approved_by": version.approved_by or "",
        "approved_at": version.approved_at.isoformat() if version.approved_at else None,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "updated_at": version.updated_at.isoformat() if version.updated_at else None,
        "chunks": chunks,
    }


def _review_to_dict(review: KnowledgeReview) -> dict[str, object]:
    return {
        "review_id": review.review_id,
        "knowledge_id": review.knowledge_id,
        "version_id": review.version_id,
        "review_stage": review.review_stage,
        "review_status": review.review_status,
        "reviewer_employee_code": review.reviewer_employee_code or "",
        "reviewer_name": review.reviewer_name or "",
        "review_comment": review.review_comment or "",
        "risk_level": review.risk_level or "",
        "source_check_result": _safe_json(review.source_check_result),
        "sensitive_check_result": _safe_json(review.sensitive_check_result),
        "prompt_injection_detected": review.prompt_injection_detected,
        "boss_confirmed": review.boss_confirmed,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


def _source_link_to_dict(link: KnowledgeSourceLink) -> dict[str, object]:
    return {
        "link_id": link.link_id,
        "knowledge_id": link.knowledge_id,
        "version_id": link.version_id,
        "source_kind": link.source_kind,
        "source_ref_id": link.source_ref_id or "",
        "source_title": link.source_title or "",
        "source_url": redact_url(link.source_url),
        "source_hash": link.source_hash or "",
        "source_confidence_level": link.source_confidence_level or "",
        "source_confidence_score": link.source_confidence_score,
        "source_is_primary": link.source_is_primary,
        "source_checked": link.source_checked,
        "evidence_id": link.evidence_id or "",
        "note": link.note or "",
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }


def _chunk_to_dict(chunk: KnowledgeChunk) -> dict[str, object]:
    return {
        "chunk_id": chunk.chunk_id,
        "knowledge_id": chunk.knowledge_id,
        "version_id": chunk.version_id,
        "chunk_index": chunk.chunk_index,
        "heading": chunk.heading or "",
        "content": chunk.content,
        "token_estimate": chunk.token_estimate,
        "content_hash": chunk.content_hash,
        "metadata": _safe_json(chunk.metadata_json),
        "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
    }


def _citation_to_dict(citation: KnowledgeCitation) -> dict[str, object]:
    return {
        "citation_id": citation.citation_id,
        "knowledge_id": citation.knowledge_id,
        "version_id": citation.version_id,
        "chunk_id": citation.chunk_id,
        "task_id": citation.task_id,
        "execution_id": citation.execution_id or "",
        "employee_id": citation.employee_id or "",
        "usage_type": citation.usage_type,
        "query_text_hash": citation.query_text_hash,
        "citation_summary": citation.citation_summary or "",
        "created_at": citation.created_at.isoformat() if citation.created_at else None,
    }


def _safe_json(value: str | None):
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {"raw": value}


def get_asset_or_404(db: Session, knowledge_id: str) -> KnowledgeAsset:
    asset = db.get(KnowledgeAsset, knowledge_id)
    if not asset:
        raise KnowledgeNotFoundError("知识资产不存在")
    return asset


def detect_duplicate(db: Session, *, title: str, summary: str | None, content: str, source_report_id: str | None) -> dict[str, object]:
    content_hash = stable_text_hash(content)
    rows = db.query(KnowledgeVersion).all()
    exact = [row for row in rows if row.content_hash == content_hash or row.source_report_id == source_report_id]
    if exact:
        return {"duplicate": True, "severity": "exact", "knowledge_id": exact[0].knowledge_id, "version_id": exact[0].version_id}
    title_tokens = set(normalize_text(title).lower().split())
    summary_tokens = set(normalize_text(summary).lower().split())
    for row in rows:
        row_tokens = set(normalize_text(row.title).lower().split()) | set(normalize_text(row.summary).lower().split())
        overlap = len(title_tokens & row_tokens) + len(summary_tokens & row_tokens)
        if overlap >= 3:
            return {"duplicate": True, "severity": "similar", "knowledge_id": row.knowledge_id, "version_id": row.version_id}
    return {"duplicate": False, "severity": "none"}
