import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from .core.orchestrator import handle_event as orchestrator_handle_event
from .database import SessionLocal, ensure_tables, engine, get_redis
from .logging_config import configure_json_logging
from .command_center import controller as command_center
from .routers import auto_dispatch
from .routers import account_center, ai_capabilities, ai_employees, ai_execution, business_loop, ceo_dashboard, deploy_center, dual_engine_business, employee_activity_log, employee_activity_trace, employee_capabilities, employee_evolution, employee_workspace, execution_engine, jd_collection, jd_integrations, knowledge_center, metrics, model_routing, orchestrator, orchestrator_hotfix, orchestrator_task_links, release_center, reviews, skill_plugin_center, skill_plugin_research, sop_skill_center, stores, task_center, tiancang, tool_permissions, users
from .seed import seed_defaults


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
WORKER_HEARTBEAT_KEY = "tiantong:worker:heartbeat"
WORKER_HEARTBEAT_MAX_AGE_SECONDS = 60
HTML_PAGES = {
    "index.html", "login.html", "control.html", "stores.html", "jd-integrations.html",
    "jd-dashboard.html", "metrics.html", "import.html", "ads.html",
    "ai-assets.html", "workflows.html", "ai-employees.html", "settings.html",
    "account-center.html", "template-center.html", "brands.html", "store-groups.html",
    "knowledge-center.html", "tiancang.html", "task-center.html", "orchestrator.html", "auto-dispatch-center.html", "deploy-center.html",
    "ai-execution.html", "release-center.html",
}
DASHBOARD_HTML_PAGES = {
    "overview.html",
    "organization.html",
    "employees.html",
    "workflow.html",
}

configure_json_logging()
logger = logging.getLogger("tiantong.backend")
app = FastAPI(title="天统AI云中台")


def handle_event(event: dict) -> dict:
    return orchestrator_handle_event(event)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started_at = time.perf_counter()
    response = await call_next(request)
    logger.info(
        "http_request",
        extra={
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "client_ip": request.client.host if request.client else "",
        },
    )
    return response


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
app.include_router(ai_capabilities.router)
app.include_router(tiancang.router)
app.include_router(knowledge_center.router)
app.include_router(task_center.router)
app.include_router(auto_dispatch.router)
app.include_router(deploy_center.router)
app.include_router(ceo_dashboard.router)
app.include_router(employee_activity_log.router, prefix="/api/employee-activity-log")
app.include_router(employee_activity_trace.router, prefix="/api/employee-activity-trace")
app.include_router(employee_capabilities.router, prefix="/api/employee-capabilities")
app.include_router(employee_evolution.router)
app.include_router(model_routing.router, prefix="/api/model-routing")
app.include_router(tool_permissions.router, prefix="/api/tool-permissions")
app.include_router(sop_skill_center.router, prefix="/api/sop-skill-center")
app.include_router(skill_plugin_center.router, prefix="/api/skill-plugin-center")
app.include_router(skill_plugin_research.router, prefix="/api/skill-plugin-research")
app.include_router(ai_execution.router)
app.include_router(execution_engine.router)
app.include_router(reviews.router)
app.include_router(release_center.router)
app.include_router(business_loop.router)
app.include_router(dual_engine_business.router)
app.include_router(employee_workspace.router)
app.include_router(orchestrator_hotfix.router)
app.include_router(orchestrator_task_links.router)
app.include_router(orchestrator.router)
app.include_router(command_center.router)


def check_database():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "status": "up"}
    except Exception as e:
        return {"ok": False, "status": "down", "error": str(e)}


def check_redis():
    try:
        return {"ok": bool(get_redis().ping()), "status": "up"}
    except Exception as e:
        return {"ok": False, "status": "down", "error": str(e)}


def check_worker():
    try:
        raw = get_redis().get(WORKER_HEARTBEAT_KEY)
    except Exception as e:
        return {"ok": False, "status": "unknown", "error": str(e)}

    if not raw:
        return {"ok": False, "status": "unknown", "last_seen_at": None}

    try:
        last_seen = datetime.fromisoformat(raw)
        age_seconds = max(0, int((datetime.now(timezone.utc) - last_seen).total_seconds()))
    except Exception:
        return {"ok": False, "status": "unknown", "last_seen_at": raw}

    is_fresh = age_seconds <= WORKER_HEARTBEAT_MAX_AGE_SECONDS
    return {
        "ok": is_fresh,
        "status": "up" if is_fresh else "stale",
        "last_seen_at": raw,
        "age_seconds": age_seconds,
    }


def build_health_payload():
    database = check_database()
    redis = check_redis()
    worker = check_worker()
    service_ok = database["ok"] and redis["ok"]

    return {
        "system": "天统AI云中台",
        "status": "running",
        "ok": service_ok,
        "checks": {
            "database": database,
            "redis": redis,
            "worker": worker,
        },
        "database": database["ok"],
        "redis": redis["ok"],
        "worker": worker["ok"],
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/health")
def health():
    return build_health_payload()


@app.get("/health")
def root_health():
    return health()


@app.get("/api/ready")
def ready():
    payload = build_health_payload()
    service_ready = payload["checks"]["database"]["ok"] and payload["checks"]["redis"]["ok"]
    return JSONResponse(status_code=200 if service_ready else 503, content={
        "system": "天统AI云中台",
        "status": "ready" if service_ready else "not_ready",
        "ok": service_ready,
        "checks": payload["checks"],
        "time": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/ready")
def root_ready():
    return ready()


def frontend_file(filename: str):
    path = FRONTEND_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="页面不存在")
    return FileResponse(path)


@app.get("/", include_in_schema=False)
def index_page():
    return frontend_file("index.html")


@app.get("/dashboard/{page_name}.html", include_in_schema=False)
def dashboard_html_page(page_name: str):
    filename = f"{page_name}.html"
    if filename not in DASHBOARD_HTML_PAGES:
        raise HTTPException(status_code=404, detail="页面不存在")
    return frontend_file(f"dashboard/{filename}")


@app.get("/{page_name}.html", include_in_schema=False)
def html_page(page_name: str):
    filename = f"{page_name}.html"
    if filename not in HTML_PAGES:
        raise HTTPException(status_code=404, detail="页面不存在")
    return frontend_file(filename)
