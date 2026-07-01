from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import get_settings
from ..database import get_db
from ..models import BugCase, CourseLesson, KnowledgeArticle, KnowledgeFile, PromptLibrary, SopLibrary
from ..services.knowledge_ai import call_ai


router = APIRouter(prefix="/api/tiancang")
BASE_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = BASE_DIR / "uploads" / "tiancang"

MOCK_SUMMARY = "这是系统自动生成的资料摘要，主要内容包括：知识资产、SOP、Prompt、Bug案例、课程沉淀等。"
MOCK_CLASSIFICATION = {"category": "AI知识库", "tags": ["天藏", "知识资产", "SOP", "Prompt"]}
MOCK_ARTICLE = {
    "title": "天藏知识资产中心建设方案",
    "content": "根据上传资料自动生成一篇结构化知识文章。",
}


@router.post("/files/upload")
async def upload_file(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    current_user(request, db)
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择要上传的文件")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    original_name = Path(file.filename).name
    suffix = Path(original_name).suffix
    saved_name = f"{uuid.uuid4().hex}{suffix}"
    saved_path = UPLOAD_DIR / saved_name

    with saved_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    record = KnowledgeFile(
        filename=saved_name,
        original_name=original_name,
        file_path=str(saved_path),
        file_type=file.content_type or suffix.removeprefix("."),
        file_size=saved_path.stat().st_size,
        status="draft",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"ok": True, "file": knowledge_file_to_dict(record)}


@router.get("/files")
def list_files(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    current_user(request, db)
    query = db.query(KnowledgeFile)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(KnowledgeFile.original_name.ilike(like), KnowledgeFile.summary.ilike(like)))
    if category:
        query = query.filter(KnowledgeFile.category == category)
    if status:
        query = query.filter(KnowledgeFile.status == status)
    rows = query.order_by(KnowledgeFile.id.desc()).all()
    return [knowledge_file_to_dict(row) for row in rows]


@router.post("/files/{file_id}/summarize")
def summarize_file(file_id: int, request: Request, db: Session = Depends(get_db)):
    current_user(request, db)
    record = get_file_or_404(db, file_id)
    result = ai_summarize(record)
    record.summary = result["summary"]
    db.commit()
    db.refresh(record)
    return {"ok": True, "summary": record.summary, "provider": result["provider"], "file": knowledge_file_to_dict(record)}


@router.post("/files/{file_id}/classify")
def classify_file(file_id: int, request: Request, db: Session = Depends(get_db)):
    current_user(request, db)
    record = get_file_or_404(db, file_id)
    result = ai_classify(record)
    record.category = result["category"]
    record.ai_tags = json.dumps(result["tags"], ensure_ascii=False)
    db.commit()
    db.refresh(record)
    return {"ok": True, "category": record.category, "tags": result["tags"], "provider": result["provider"], "file": knowledge_file_to_dict(record)}


@router.post("/files/{file_id}/generate-article")
def generate_article(file_id: int, request: Request, db: Session = Depends(get_db)):
    current_user(request, db)
    record = get_file_or_404(db, file_id)
    result = ai_generate_article(record)
    article = KnowledgeArticle(
        title=result["title"],
        content=result["content"],
        summary=record.summary or MOCK_SUMMARY,
        category=record.category or MOCK_CLASSIFICATION["category"],
        source_file_id=record.id,
        tags=record.ai_tags or json.dumps(MOCK_CLASSIFICATION["tags"], ensure_ascii=False),
        status="draft",
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    return {"ok": True, "article": article_to_dict(article), "provider": result["provider"]}


@router.post("/articles/{article_id}/publish")
def publish_article(article_id: int, request: Request, db: Session = Depends(get_db)):
    current_user(request, db)
    article = db.get(KnowledgeArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="知识文章不存在")
    article.status = "published"
    article.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(article)
    return {"ok": True, "article": article_to_dict(article)}


@router.get("/articles/search")
def search_articles(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    current_user(request, db)
    query = db.query(KnowledgeArticle)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(KnowledgeArticle.title.ilike(like), KnowledgeArticle.content.ilike(like), KnowledgeArticle.summary.ilike(like)))
    if category:
        query = query.filter(KnowledgeArticle.category == category)
    if status:
        query = query.filter(KnowledgeArticle.status == status)
    rows = query.order_by(KnowledgeArticle.id.desc()).all()
    return [article_to_dict(row) for row in rows]


@router.get("/sops")
def list_sops(request: Request, q: str | None = None, status: str | None = None, db: Session = Depends(get_db)):
    current_user(request, db)
    query = db.query(SopLibrary)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(SopLibrary.title.ilike(like), SopLibrary.content.ilike(like), SopLibrary.department.ilike(like)))
    if status:
        query = query.filter(SopLibrary.status == status)
    return [sop_to_dict(row) for row in query.order_by(SopLibrary.id.desc()).all()]


@router.get("/prompts")
def list_prompts(request: Request, q: str | None = None, prompt_type: str | None = None, db: Session = Depends(get_db)):
    current_user(request, db)
    query = db.query(PromptLibrary)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(PromptLibrary.title.ilike(like), PromptLibrary.content.ilike(like)))
    if prompt_type:
        query = query.filter(PromptLibrary.prompt_type == prompt_type)
    return [prompt_to_dict(row) for row in query.order_by(PromptLibrary.id.desc()).all()]


@router.get("/bugs")
def list_bugs(request: Request, q: str | None = None, status: str | None = None, db: Session = Depends(get_db)):
    current_user(request, db)
    query = db.query(BugCase)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(BugCase.title.ilike(like), BugCase.description.ilike(like), BugCase.solution.ilike(like)))
    if status:
        query = query.filter(BugCase.status == status)
    return [bug_to_dict(row) for row in query.order_by(BugCase.id.desc()).all()]


@router.get("/courses")
def list_courses(request: Request, q: str | None = None, status: str | None = None, db: Session = Depends(get_db)):
    current_user(request, db)
    query = db.query(CourseLesson)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(CourseLesson.title.ilike(like), CourseLesson.course_name.ilike(like), CourseLesson.content.ilike(like)))
    if status:
        query = query.filter(CourseLesson.status == status)
    return [course_to_dict(row) for row in query.order_by(CourseLesson.lesson_order.asc(), CourseLesson.id.desc()).all()]


def get_file_or_404(db: Session, file_id: int):
    record = db.get(KnowledgeFile, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="资料不存在")
    return record


def configured_provider():
    settings = get_settings()
    provider = (settings.AI_PROVIDER or "mock").lower()
    if provider == "openai" and settings.OPENAI_API_KEY:
        return "openai"
    if provider == "deepseek" and settings.DEEPSEEK_API_KEY:
        return "deepseek"
    return "mock"


def ai_summarize(record: KnowledgeFile):
    provider = configured_provider()
    if provider != "mock":
        result = safe_call_ai(f"请总结资料《{record.original_name or record.filename}》，输出适合知识库沉淀的摘要。")
        if result:
            return {"provider": provider, "summary": result}
    return {"provider": provider, "summary": MOCK_SUMMARY}


def ai_classify(record: KnowledgeFile):
    provider = configured_provider()
    if provider != "mock":
        result = safe_call_ai(f"请将资料《{record.original_name or record.filename}》分类，并给出标签。")
        if result:
            return {"provider": provider, "category": MOCK_CLASSIFICATION["category"], "tags": [*MOCK_CLASSIFICATION["tags"], "AI生成"]}
    return {"provider": provider, **MOCK_CLASSIFICATION}


def ai_generate_article(record: KnowledgeFile):
    provider = configured_provider()
    if provider != "mock":
        result = safe_call_ai(f"请基于资料《{record.original_name or record.filename}》生成一篇结构化知识文章。摘要：{record.summary or ''}")
        if result:
            return {"provider": provider, "title": MOCK_ARTICLE["title"], "content": result}
    return {"provider": provider, **MOCK_ARTICLE}


def safe_call_ai(prompt: str):
    try:
        return call_ai(prompt)
    except Exception:
        return None


def parse_json_list(value: str | None):
    if not value:
        return []
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def iso(value):
    return value.isoformat() if value else None


def knowledge_file_to_dict(row: KnowledgeFile):
    return {
        "id": row.id,
        "filename": row.filename,
        "original_name": row.original_name,
        "file_path": row.file_path,
        "file_type": row.file_type,
        "file_size": row.file_size,
        "category": row.category,
        "summary": row.summary,
        "ai_tags": parse_json_list(row.ai_tags),
        "status": row.status,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def article_to_dict(row: KnowledgeArticle):
    return {
        "id": row.id,
        "title": row.title,
        "content": row.content,
        "summary": row.summary,
        "category": row.category,
        "source_file_id": row.source_file_id,
        "tags": parse_json_list(row.tags),
        "status": row.status,
        "published_at": iso(row.published_at),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def sop_to_dict(row: SopLibrary):
    return {"id": row.id, "title": row.title, "department": row.department, "content": row.content, "category": row.category, "status": row.status, "created_at": iso(row.created_at), "updated_at": iso(row.updated_at)}


def prompt_to_dict(row: PromptLibrary):
    return {"id": row.id, "title": row.title, "prompt_type": row.prompt_type, "content": row.content, "model": row.model, "version": row.version, "status": row.status, "created_at": iso(row.created_at), "updated_at": iso(row.updated_at)}


def bug_to_dict(row: BugCase):
    return {"id": row.id, "title": row.title, "description": row.description, "reason": row.reason, "solution": row.solution, "impact_scope": row.impact_scope, "status": row.status, "created_at": iso(row.created_at), "updated_at": iso(row.updated_at)}


def course_to_dict(row: CourseLesson):
    return {"id": row.id, "title": row.title, "course_name": row.course_name, "outline": row.outline, "content": row.content, "lesson_order": row.lesson_order, "status": row.status, "created_at": iso(row.created_at), "updated_at": iso(row.updated_at)}
