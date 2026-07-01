from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import require_permission_user
from ..database import get_db
from ..models import JdAccount, JdSyncLog, Store
from ..queue import enqueue_task, get_queue_status
from ..services.ai_store_manager import analyze_store_health


router = APIRouter()

SYNC_TASK_TYPES = ["sync_jd_smart", "sync_jzt", "sync_jd_orders", "sync_jd_products"]


@router.get("/api/jd/accounts")
def list_jd_accounts(request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "menu.jd_data")
    rows = db.query(JdAccount).order_by(JdAccount.id.asc()).all()
    return [account_to_dict(row) for row in rows]


@router.post("/api/jd/accounts")
async def create_jd_account(request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "menu.jd_data")
    data = await request.json()
    store_id = data.get("store_id")
    account_name = data.get("account_name", "").strip()
    account_type = data.get("account_type", "").strip() or data.get("platform", "").strip()
    if account_type not in {"jd_smart", "jzt"}:
        raise HTTPException(status_code=400, detail="account_type 只能是 jd_smart 或 jzt")
    if not store_id or not db.get(Store, store_id):
        raise HTTPException(status_code=404, detail="店铺不存在")
    if not account_name:
        raise HTTPException(status_code=400, detail="账号名称不能为空")
    account = JdAccount(
        store_id=store_id,
        platform=data.get("platform", "jd").strip() or "jd",
        account_type=account_type,
        account_name=account_name,
        login_username=data.get("login_username", "").strip(),
        login_status=data.get("login_status", "unknown").strip(),
        cookie_status=data.get("cookie_status", "unknown").strip(),
        auth_status=data.get("auth_status", "pending").strip(),
        access_token=data.get("access_token"),
        refresh_token=data.get("refresh_token"),
        remark=data.get("remark"),
        active=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return {"ok": True, "id": account.id}


@router.post("/api/jd/sync/store/{store_id}")
def enqueue_store_sync(store_id: int, request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "menu.jd_data")
    if not db.get(Store, store_id):
        raise HTTPException(status_code=404, detail="店铺不存在")
    queued = enqueue_store_tasks(store_id)
    return {"ok": True, "store_id": store_id, "queued": queued}


@router.post("/api/jd/sync/all")
def enqueue_all_store_sync(request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "menu.jd_data")
    stores = db.query(Store).filter(Store.platform == "jd", Store.active.is_(True)).all()
    queued = []
    for store in stores:
        queued.extend(enqueue_store_tasks(store.id))
    return {"ok": True, "stores": len(stores), "tasks": len(queued), "queued": queued}


@router.get("/api/jd/sync/status")
def jd_sync_status(request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "menu.jd_data")
    logs = db.query(JdSyncLog).order_by(JdSyncLog.id.desc()).limit(50).all()
    return {
        "queue": get_queue_status(50),
        "logs": [sync_log_to_dict(log) for log in logs],
    }


@router.post("/api/ai/store-manager/analyze")
def ai_store_manager_analyze(request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "ai.tasks.read")
    return {"ok": True, "date": date.today().isoformat(), "suggestions": analyze_store_health(db)}


@router.post("/api/ai/store-manager/enqueue")
def enqueue_ai_store_manager(request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "ai.tasks.read")
    task = enqueue_task("ai_store_manager_daily", {"date": date.today().isoformat()})
    return {"ok": True, "queued": task}


def enqueue_store_tasks(store_id: int):
    return [enqueue_task(task_type, {"store_id": store_id}) for task_type in SYNC_TASK_TYPES]


def account_to_dict(account: JdAccount):
    return {
        "id": account.id,
        "store_id": account.store_id,
        "store_code": account.store.store_code if account.store else None,
        "store_name": account.store.store_name if account.store else None,
        "platform": account.platform,
        "account_type": account.account_type,
        "account_name": account.account_name,
        "login_username": account.login_username,
        "login_status": account.login_status,
        "cookie_status": account.cookie_status,
        "auth_status": account.auth_status,
        "last_login_at": account.last_login_at.isoformat() if account.last_login_at else None,
        "last_sync_at": account.last_sync_at.isoformat() if account.last_sync_at else None,
        "remark": account.remark,
        "active": account.active,
    }


def sync_log_to_dict(log: JdSyncLog):
    return {
        "id": log.id,
        "store_id": log.store_id,
        "store_name": log.store.store_name if log.store else None,
        "task_id": log.task_id,
        "task_type": log.task_type,
        "status": log.status,
        "message": log.message,
        "attempt": log.attempt,
        "retry_count": log.attempt,
        "failure_reason": log.message if log.status == "failed" else None,
        "last_executed_at": (log.finished_at or log.started_at or log.created_at).isoformat() if (log.finished_at or log.started_at or log.created_at) else None,
        "started_at": log.started_at.isoformat() if log.started_at else None,
        "finished_at": log.finished_at.isoformat() if log.finished_at else None,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
