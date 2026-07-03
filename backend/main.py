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
app.include_router(account_center.router)
app.include_router(jd_integrations.router)
app.include_router(jd_collection.router)
app.include_router(metrics.router)
app.include_router(ai_employees.router)
app.include_router(tiancang.router)
app.include_router(knowledge_center.router)
app.include_router(task_center.router)
app.include_router(deploy_center.router)
app.include_router(ceo_dashboard.router)
app.include_router(orchestrator.router)


@app.get("/api/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        db_ok = str(e)

    try:
        redis_ok = get_redis().ping()
    except Exception as e:
        redis_ok = str(e)

    return {
        "system": "天统AI云中台",
        "status": "running",
        "database": db_ok,
        "redis": redis_ok,
        "time": datetime.now().isoformat(),
    }


@app.get("/api/ready")
def ready():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    get_redis().ping()
    return {
        "system": "天统AI云中台",
        "status": "ready",
        "time": datetime.now().isoformat(),
    }


def frontend_file(filename: str):
    path = FRONTEND_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="页面不存在")
    return FileResponse(path)


@app.get("/", include_in_schema=False)
def index_page():
    return frontend_file("index.html")


@app.get("/{page_name}.html", include_in_schema=False)
def html_page(page_name: str):
    filename = f"{page_name}.html"
    if filename not in HTML_PAGES:
        raise HTTPException(status_code=404, detail="页面不存在")
    return frontend_file(filename)
