from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..employee_execution.models import EmployeeExecutionContract
from ..workers.tian_shang_worker import contract_to_dict, create_tian_shang_task, latest_tian_shang_status, process_next_tian_shang_execution


router = APIRouter(prefix="/api/employee-execution")
PRIVILEGED_ROLES = {"owner", "admin"}


class TianShangTaskCreate(BaseModel):
    goal: str


@router.post("/tian-shang/tasks")
def create_tian_shang_execution_task(payload: TianShangTaskCreate, request: Request, db: Session = Depends(get_db)):
    user = require_privileged_user(request, db)
    return create_tian_shang_task(db, payload.goal, created_by_id=user.id, enqueue=True)


@router.post("/tian-shang/process-next")
def process_next_tian_shang_task(request: Request, db: Session = Depends(get_db)):
    require_privileged_user(request, db)
    processed = process_next_tian_shang_execution(db, timeout=1)
    return {"processed": processed, "status": latest_tian_shang_status(db)}


@router.get("/tian-shang/status")
def get_tian_shang_status(request: Request, db: Session = Depends(get_db)):
    require_execution_view_user(request, db)
    return latest_tian_shang_status(db)


@router.get("/contracts/{contract_id}")
def get_execution_contract(contract_id: int, request: Request, db: Session = Depends(get_db)):
    require_execution_view_user(request, db)
    row = db.get(EmployeeExecutionContract, contract_id)
    if not row:
        raise HTTPException(status_code=404, detail="执行合同不存在")
    return contract_to_dict(row)


def require_execution_view_user(request: Request, db: Session):
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role in PRIVILEGED_ROLES:
        return user
    if user.username == "tianshang":
        return user
    raise HTTPException(status_code=403, detail="无 AI员工执行查看权限")


def require_privileged_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in PRIVILEGED_ROLES:
        raise HTTPException(status_code=403, detail="需要 Owner/Admin 权限")
    return user
