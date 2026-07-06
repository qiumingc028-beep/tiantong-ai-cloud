from __future__ import annotations

from typing import Optional
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import current_user, get_role_permissions, normalize_role
from ..database import get_db
from ..models import BugCase, CourseLesson, KnowledgeArticle, KnowledgeFile, PromptLibrary, SopLibrary
from ..services.knowledge_ai import classify_material, generate_assets, summarize_material


router = APIRouter()

STATUS_MAP = {
    "draft": "draft",
    "草稿": "draft",
    "published": "published",
    "已发布": "published",
    "review": "review",
    "pending_review": "review",
    "待审核": "review",
}


@router.post("/api/knowledge/files")
async def upload_file(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = require_knowledge_access(request, db, manage=True)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件不能为空")
    text = decode_content(content)
    row = KnowledgeFile(
        filename=file.filename or "未命名资料",
        content_type=file.content_type,
        file_size=len(content),
        content_text=text,
        status="draft",
        uploaded_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return file_to_dict(row)


@router.get("/api/knowledge/files")
def list_files(
    request: Request,
    q: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    require_knowledge_access(request, db)
    query = db.query(KnowledgeFile).order_by(KnowledgeFile.id.desc())
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(KnowledgeFile.filename.ilike(like), KnowledgeFile.summary.ilike(like), KnowledgeFile.content_text.ilike(like)))
    if category:
        query = query.filter(KnowledgeFile.category == category)
    normalized_status = normalize_status(status)
    if normalized_status:
        query = query.filter(KnowledgeFile.status == normalized_status)
    return [file_to_dict(row) for row in query.limit(200).all()]


@router.post("/api/knowledge/files/{file_id}/summarize")
def summarize_file(file_id: int, request: Request, db: Session = Depends(get_db)):
    require_knowledge_access(request, db, manage=True)
    row = get_file(db, file_id)
    result = summarize_material(row.filename, row.content_text or "")
    row.summary = result.get("summary") or json.dumps(result, ensure_ascii=False)
    db.commit()
    db.refresh(row)
    return {"file": file_to_dict(row), "result": result}


@router.post("/api/knowledge/files/{file_id}/classify")
def classify_file(file_id: int, request: Request, db: Session = Depends(get_db)):
    require_knowledge_access(request, db, manage=True)
    row = get_file(db, file_id)
    result = classify_material(row.filename, row.content_text or "")
    row.category = result.get("category") or "知识库"
    db.commit()
    db.refresh(row)
    return {"file": file_to_dict(row), "result": result}


@router.post("/api/knowledge/files/{file_id}/article")
def generate_article(file_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_knowledge_access(request, db, manage=True)
    row = get_file(db, file_id)
    if not row.summary:
        row.summary = summarize_material(row.filename, row.content_text or "").get("summary", "")
    if not row.category:
        row.category = classify_material(row.filename, row.content_text or "").get("category", "知识库")
    assets = generate_assets(row.filename, row.content_text or "", row.summary, row.category)
    article_data = assets["article"]
    article = KnowledgeArticle(
        file_id=row.id,
        title=article_data["title"],
        summary=article_data["summary"],
        content=article_data["content"],
        category=article_data["category"],
        tags=json.dumps(article_data.get("tags", []), ensure_ascii=False),
        status="draft",
        created_by=user.id,
    )
    db.add(article)
    db.flush()
    sop = SopLibrary(article_id=article.id, status="draft", **assets["sop"])
    prompt = PromptLibrary(article_id=article.id, status="draft", **assets["prompt"])
    bug = BugCase(article_id=article.id, status="draft", **assets["bug_case"])
    course = CourseLesson(article_id=article.id, status="draft", **assets["course"])
    db.add_all([sop, prompt, bug, course])
    db.commit()
    db.refresh(article)
    return {
        "article": article_to_dict(article),
        "sop": sop_to_dict(sop),
        "prompt": prompt_to_dict(prompt),
        "bug_case": bug_to_dict(bug),
        "course": course_to_dict(course),
        "mock": assets.get("mock", False),
    }


@router.post("/api/knowledge/articles/{article_id}/publish")
def publish_article(article_id: int, request: Request, db: Session = Depends(get_db)):
    require_knowledge_access(request, db, manage=True)
    article = db.get(KnowledgeArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="知识文章不存在")
    article.status = "published"
    article.published_at = datetime.now(timezone.utc)
    for model in (SopLibrary, PromptLibrary, BugCase, CourseLesson):
        db.query(model).filter(model.article_id == article.id).update({"status": "published"})
    if article.file_id:
        file_row = db.get(KnowledgeFile, article.file_id)
        if file_row:
            file_row.status = "published"
    db.commit()
    db.refresh(article)
    return {"ok": True, "article": article_to_dict(article)}


@router.get("/api/knowledge/articles")
def list_articles(
    request: Request,
    q: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    require_knowledge_access(request, db)
    return query_articles(db, q, category, status)


@router.get("/api/knowledge/search")
def search_knowledge(
    request: Request,
    q: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    require_knowledge_access(request, db)
    articles = query_articles(db, q, category, status)
    files = list_files(request, q=q, category=category, status=status, db=db)
    return {"articles": articles, "files": files}


@router.get("/api/knowledge/sops")
def list_sops(request: Request, category: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    require_knowledge_access(request, db)
    query = filter_category_status(db.query(SopLibrary), SopLibrary, category, status)
    return [sop_to_dict(row) for row in query.order_by(SopLibrary.id.desc()).limit(200).all()]


@router.get("/api/knowledge/prompts")
def list_prompts(request: Request, category: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    require_knowledge_access(request, db)
    query = filter_category_status(db.query(PromptLibrary), PromptLibrary, category, status)
    return [prompt_to_dict(row) for row in query.order_by(PromptLibrary.id.desc()).limit(200).all()]


@router.get("/api/knowledge/bug-cases")
def list_bug_cases(request: Request, category: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    require_knowledge_access(request, db)
    query = filter_category_status(db.query(BugCase), BugCase, category, status)
    return [bug_to_dict(row) for row in query.order_by(BugCase.id.desc()).limit(200).all()]


@router.get("/api/knowledge/courses")
def list_courses(request: Request, category: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    require_knowledge_access(request, db)
    query = filter_category_status(db.query(CourseLesson), CourseLesson, category, status)
    return [course_to_dict(row) for row in query.order_by(CourseLesson.id.desc()).limit(200).all()]


def query_articles(db: Session, q: Optional[str], category: Optional[str], status: Optional[str]):
    query = db.query(KnowledgeArticle).order_by(KnowledgeArticle.id.desc())
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(KnowledgeArticle.title.ilike(like), KnowledgeArticle.summary.ilike(like), KnowledgeArticle.content.ilike(like)))
    if category:
        query = query.filter(KnowledgeArticle.category == category)
    normalized_status = normalize_status(status)
    if normalized_status:
        query = query.filter(KnowledgeArticle.status == normalized_status)
    return [article_to_dict(row) for row in query.limit(200).all()]


def filter_category_status(query, model, category: Optional[str], status: Optional[str]):
    if category:
        query = query.filter(model.category == category)
    normalized_status = normalize_status(status)
    if normalized_status:
        query = query.filter(model.status == normalized_status)
    return query


def get_file(db: Session, file_id: int) -> KnowledgeFile:
    row = db.get(KnowledgeFile, file_id)
    if not row:
        raise HTTPException(status_code=404, detail="资料不存在")
    return row


def require_knowledge_access(request: Request, db: Session, manage: bool = False):
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role in {"owner", "admin"}:
        return user
    permissions = get_role_permissions(db, role)
    required = "knowledge.manage" if manage else "knowledge.read"
    if required not in permissions and "knowledge.manage" not in permissions:
        raise HTTPException(status_code=403, detail="没有天藏知识资产中心访问权限")
    return user


def normalize_status(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return STATUS_MAP.get(value.strip(), value.strip())


def status_label(value: Optional[str]) -> str:
    return {"draft": "草稿", "published": "已发布", "review": "待审核"}.get(value or "", value or "")


def decode_content(content: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            pass
    return ""


def file_to_dict(row: KnowledgeFile):
    return {
        "id": row.id,
        "filename": row.filename,
        "content_type": row.content_type or "",
        "file_size": row.file_size,
        "summary": row.summary or "",
        "category": row.category or "",
        "status": row.status,
        "status_label": status_label(row.status),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def article_to_dict(row: KnowledgeArticle):
    return {
        "id": row.id,
        "file_id": row.file_id,
        "title": row.title,
        "summary": row.summary or "",
        "content": row.content,
        "category": row.category or "",
        "tags": json.loads(row.tags or "[]"),
        "status": row.status,
        "status_label": status_label(row.status),
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def sop_to_dict(row: SopLibrary):
    return {"id": row.id, "article_id": row.article_id, "title": row.title, "category": row.category or "", "steps": row.steps, "status": row.status, "status_label": status_label(row.status)}


def prompt_to_dict(row: PromptLibrary):
    return {"id": row.id, "article_id": row.article_id, "title": row.title, "category": row.category or "", "prompt_text": row.prompt_text, "usage_notes": row.usage_notes or "", "status": row.status, "status_label": status_label(row.status)}


def bug_to_dict(row: BugCase):
    return {"id": row.id, "article_id": row.article_id, "title": row.title, "category": row.category or "", "symptom": row.symptom, "root_cause": row.root_cause or "", "solution": row.solution, "status": row.status, "status_label": status_label(row.status)}


def course_to_dict(row: CourseLesson):
    return {"id": row.id, "article_id": row.article_id, "title": row.title, "category": row.category or "", "outline": row.outline, "target_audience": row.target_audience or "", "status": row.status, "status_label": status_label(row.status)}
