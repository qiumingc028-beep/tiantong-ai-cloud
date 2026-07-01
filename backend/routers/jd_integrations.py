from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from ..auth import require_permission_user
from ..database import get_db
from ..models import JdIntegration, Store


router = APIRouter()


@router.get("/api/jd/integrations")
def list_jd_integrations(request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "menu.jd_data")
    rows = db.query(JdIntegration).options(joinedload(JdIntegration.store)).order_by(JdIntegration.id.asc()).all()
    return [integration_to_dict(i) for i in rows]


@router.post("/api/jd/integrations")
async def create_jd_integration(request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "menu.jd_data")
    data = await request.json()
    store_id = data.get("store_id")
    source_type = data.get("source_type", "").strip()
    connection_mode = data.get("connection_mode", "").strip()
    if not store_id or not source_type or not connection_mode:
        raise HTTPException(status_code=400, detail="店铺、数据来源、接入方式不能为空")
    if not db.get(Store, store_id):
        raise HTTPException(status_code=404, detail="店铺不存在")
    if source_type not in ["jd_sz", "jd_jzt", "jd_open", "manual_import", "browser_auto"]:
        raise HTTPException(status_code=400, detail="数据来源不正确")
    if connection_mode not in ["official_api", "browser_auto", "excel_import", "pending"]:
        raise HTTPException(status_code=400, detail="接入方式不正确")

    integration = JdIntegration(
        store_id=store_id,
        source_type=source_type,
        connection_mode=connection_mode,
        merchant_id=data.get("merchant_id", "").strip(),
        app_key=data.get("app_key", "").strip(),
        notes=data.get("notes", "").strip(),
        status="pending",
        active=True,
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return {"ok": True, "id": integration.id}


@router.post("/api/jd/integrations/{integration_id}/status")
async def update_jd_integration_status(integration_id: int, request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "menu.jd_data")
    data = await request.json()
    status = data.get("status", "").strip()
    if status not in ["pending", "authorized", "error", "disabled"]:
        raise HTTPException(status_code=400, detail="状态不正确")
    integration = db.get(JdIntegration, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="接入记录不存在")
    integration.status = status
    db.commit()
    return {"ok": True}


@router.post("/api/jd/integrations/{integration_id}/toggle")
def toggle_jd_integration(integration_id: int, request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "menu.jd_data")
    integration = db.get(JdIntegration, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="接入记录不存在")
    integration.active = not integration.active
    db.commit()
    return {"ok": True, "active": integration.active}


def integration_to_dict(i: JdIntegration):
    return {
        "id": i.id,
        "store_id": i.store_id,
        "store_code": i.store.store_code if i.store else None,
        "store_name": i.store.store_name if i.store else None,
        "source_type": i.source_type,
        "connection_mode": i.connection_mode,
        "merchant_id": i.merchant_id,
        "app_key": i.app_key,
        "status": i.status,
        "notes": i.notes,
        "active": i.active,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "updated_at": i.updated_at.isoformat() if i.updated_at else None,
    }
