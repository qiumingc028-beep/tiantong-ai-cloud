from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from ..auth import get_role_permissions, normalize_role, require_permission_user, current_user
from ..database import get_db, get_redis
from ..models import AiTask, EmployeeLog


router = APIRouter()


@router.get("/api/ai/tasks")
def list_ai_tasks(request: Request, db: Session = Depends(get_db)):
    require_ai_task_read(request, db)
    tasks = db.query(AiTask).options(joinedload(AiTask.owner)).order_by(AiTask.id.asc()).all()
    return [task_to_dict(t) for t in tasks]


@router.post("/api/ai/tasks/{task_id}")
async def update_ai_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "ai.tasks.manage")
    data = await request.json()
    task = db.get(AiTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="AI员工任务不存在")
    task.status = data.get("status", "").strip() or "idle"
    task.today_task = data.get("today_task", "").strip()
    task.execution_log = data.get("execution_log", "").strip()
    task.owner_user_id = data.get("owner_user_id") or None
    db.add(EmployeeLog(user_id=user.id, action="ai_task_update", detail=f"更新AI任务 {task_id}", ip_address=request.client.host if request.client else None))
    db.commit()
    return {"ok": True}


@router.post("/api/ai/tasks/{task_id}/run")
def run_ai_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "ai.tasks.manage")
    task = db.get(AiTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="AI员工任务不存在")
    now = datetime.now(timezone.utc)
    task.status = "running"
    task.last_run_at = now
    line = f"{now.strftime('%Y-%m-%d %H:%M:%S')} 手动触发执行"
    task.execution_log = ((task.execution_log or "") + "\n" + line).strip()
    db.add(EmployeeLog(user_id=user.id, action="ai_task_run", detail=f"触发{task.ai_employee_name}执行", ip_address=request.client.host if request.client else None))
    db.commit()
    push_ai_queue(task)
    return {"ok": True, "message": f"{task.ai_employee_name} 已进入执行状态"}


def task_to_dict(task: AiTask):
    return {
        "id": task.id,
        "ai_employee_code": task.ai_employee_code,
        "ai_employee_name": task.ai_employee_name,
        "status": task.status,
        "today_task": task.today_task or "",
        "execution_log": task.execution_log or "",
        "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "owner": {"id": task.owner.id, "display_name": task.owner.display_name} if task.owner else None,
    }


def push_ai_queue(task: AiTask):
    get_redis().rpush(
        "ai:task_queue",
        json.dumps(
            {
                "task_id": task.id,
                "ai_employee_code": task.ai_employee_code,
                "ai_employee_name": task.ai_employee_name,
                "today_task": task.today_task,
                "queued_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        ),
    )


def require_ai_task_read(request: Request, db: Session):
    user = current_user(request, db)
    permissions = get_role_permissions(db, normalize_role(user.role))
    if not permissions.intersection({"ai.tasks.read", "ai.tasks.manage", "menu.ai_employees", "menu.workflows"}):
        raise HTTPException(status_code=403, detail="没有AI员工任务访问权限")
    return user
