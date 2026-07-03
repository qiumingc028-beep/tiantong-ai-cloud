from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text

from .database import SessionLocal, ensure_tables, engine, get_redis
from .routers import account_center, ai_employees, ceo_dashboard, deploy_center, jd_collection, jd_integrations, knowledge_center, metrics, orchestrator, stores, task_center, tiancang, users
from .seed import seed_defaults


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
HTML_PAGES = {
    "index.html", "login.html", "control.html", "stores.html", "jd-integrations.html",
    "jd-dashboard.html", "metrics.html", "import.html", "ads.html",
    "ai-assets.html", "workflows.html", "ai-employees.html", "settings.html",
    "account-center.html", "template-center.html", "brands.html", "store-groups.html",
    "knowledge-center.html", "tiancang.html", "task-center.html", "orchestrator.html", "deploy-center.html",
}

app = FastAPI(title="天统AI云中台")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    ensure_tables()
    db = SessionLocal()
    try:
        seed_defaults(db)
    finally:
        db.close()


app.include_router(users.router)
app.include_router(stores.router)
app.include_router(metrics.router)
app.include_router(jd_integrations.router)
app.include_router(jd_collection.router)
app.include_router(account_center.router)
app.include_router(knowledge_center.router)
app.include_router(tiancang.router)
app.include_router(task_center.router)
app.include_router(ai_employees.router)
app.include_router(deploy_center.router)
app.include_router(ceo_dashboard.router)
app.include_router(orchestrator.router)


def db_health() -> bool:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        db.close()


def redis_health() -> bool:
    client = get_redis()
    try:
        if client is None:
            return False
        return bool(client.ping())
    except Exception:
        return False


@app.get("/api/health")
def health():
    database_ok = db_health()
    redis_ok = redis_health()
    return {
        "status": "ok" if database_ok else "degraded",
        "database": database_ok,
        "redis": redis_ok,
        "time": datetime.utcnow().isoformat(),
    }


@app.get("/")
def root():
    return frontend_file("index.html")


def frontend_file(filename: str):
    path = FRONTEND_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="页面不存在")
    return FileResponse(path)


@app.get("/{filename}")
def html_page(filename: str):
    if filename not in HTML_PAGES:
        raise HTTPException(status_code=404, detail="页面不存在")
    return frontend_file(filename)
