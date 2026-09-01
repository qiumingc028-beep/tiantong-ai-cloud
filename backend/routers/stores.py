from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from ..auth import get_role_permissions, normalize_role, require_permission_user, current_user
from ..database import get_db
from ..models import (
    Company, JdDailyMetric, JdWorkbenchDevice, JdWorkbenchStoreStatus,
    MetricDaily, Store, User, UserStoreMembership,
)
from ..store_authorization import authorized_stores, require_authorized_store


router = APIRouter()


@router.get("/api/store-users")
def store_users(request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "stores.manage")
    users = db.query(User).filter(
        User.tenant_id == user.tenant_id,
        User.company_id == user.company_id,
        User.active.is_(True),
    ).order_by(User.id.asc()).all()
    return [{"id": u.id, "username": u.username, "role": u.role, "display_name": u.display_name, "active": u.active} for u in users]


@router.get("/api/stores")
def list_stores(request: Request, db: Session = Depends(get_db)):
    user = require_store_read(request, db)
    stores = authorized_stores(db, user, active_only=False).options(joinedload(Store.manager)).order_by(Store.id.asc()).all()
    companies = {
        company.id: company
        for company in db.query(Company).filter(
            Company.tenant_id == user.tenant_id,
            Company.id.in_([store.company_id for store in stores]),
        ).all()
    }
    latest_statuses = {}
    for store in stores:
        latest_statuses[store.id] = (
            db.query(JdWorkbenchStoreStatus)
            .join(JdWorkbenchDevice, JdWorkbenchDevice.device_id == JdWorkbenchStoreStatus.device_id)
            .filter(
                JdWorkbenchStoreStatus.store_id == store.id,
                JdWorkbenchDevice.tenant_id == user.tenant_id,
                JdWorkbenchDevice.revoked_at.is_(None),
            )
            .order_by(JdWorkbenchStoreStatus.updated_at.desc())
            .first()
        )
    return [store_to_dict(s, companies.get(s.company_id), latest_statuses.get(s.id)) for s in stores]


@router.get("/api/jd/dashboard")
def jd_dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "menu.jd_data")
    stores = (
        authorized_stores(db, user)
        .options(joinedload(Store.manager))
        .filter(Store.platform == "jd")
        .order_by(Store.id.asc())
        .all()
    )
    store_ids = [store.id for store in stores]
    jd_metrics = {
        m.store_id: m
        for m in db.query(JdDailyMetric).filter(
            JdDailyMetric.metric_date == date.today(),
            JdDailyMetric.store_id.in_(store_ids),
        ).all()
    }
    legacy_metrics = {
        m.store_id: m
        for m in db.query(MetricDaily).filter(
            MetricDaily.metric_date == date.today(),
            MetricDaily.store_id.in_(store_ids),
        ).all()
    }
    rows = []
    for store in stores:
        item = store_metric_to_dict(store, jd_metrics.get(store.id), legacy_metrics.get(store.id))
        item["health_score"], item["health_status"], item["alerts"] = assess_store_health(item)
        rows.append(item)
    return {"stores": rows, "total": len(rows), "alerts": sum(len(s["alerts"]) for s in rows), "healthy": sum(1 for s in rows if s["health_score"] >= 80)}


@router.post("/api/stores")
async def create_store(request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "stores.manage")
    data = await request.json()
    store_code = data.get("store_code", "").strip()
    store_name = data.get("store_name", "").strip()
    if not store_code or not store_name:
        raise HTTPException(status_code=400, detail="店铺编号和店铺名称不能为空")
    if db.query(Store).filter(Store.tenant_id == user.tenant_id, Store.store_code == store_code).first():
        raise HTTPException(status_code=400, detail="店铺编号已存在")
    store = Store(
        platform=data.get("platform", "jd").strip(),
        store_code=store_code,
        store_name=store_name,
        tenant_id=user.tenant_id,
        company_id=user.company_id,
        notes=data.get("notes", "").strip(),
        active=True,
    )
    db.add(store)
    db.flush()
    db.add(UserStoreMembership(user_id=user.id, store_id=store.id, can_read=True, can_write=True, active=True))
    db.commit()
    db.refresh(store)
    return {"ok": True, "id": store.id}


@router.post("/api/stores/{store_id}/assign")
async def assign_store(store_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "stores.manage")
    data = await request.json()
    store = require_authorized_store(db, user, store_id=store_id, write=True)
    manager_user_id = data.get("manager_user_id")
    manager = None
    if manager_user_id:
        manager = db.query(User).filter(
            User.id == manager_user_id,
            User.tenant_id == user.tenant_id,
            User.company_id == user.company_id,
            User.active.is_(True),
        ).one_or_none()
    if manager_user_id and not manager:
        raise HTTPException(status_code=400, detail="负责人不存在或已停用")
    previous_manager_id = store.manager_user_id
    store.manager_user_id = manager_user_id or None
    if previous_manager_id and previous_manager_id != manager_user_id:
        previous_membership = db.query(UserStoreMembership).filter(
            UserStoreMembership.user_id == previous_manager_id,
            UserStoreMembership.store_id == store.id,
            UserStoreMembership.assignment_managed.is_(True),
        ).one_or_none()
        if previous_membership:
            previous_membership.active = bool(previous_membership.assignment_previous_active)
            previous_membership.can_read = bool(previous_membership.assignment_previous_can_read)
            previous_membership.can_write = bool(previous_membership.assignment_previous_can_write)
            previous_membership.assignment_managed = False
            previous_membership.assignment_previous_active = None
            previous_membership.assignment_previous_can_read = None
            previous_membership.assignment_previous_can_write = None
    if manager:
        membership = db.query(UserStoreMembership).filter(
            UserStoreMembership.user_id == manager.id,
            UserStoreMembership.store_id == store.id,
        ).one_or_none()
        if not membership:
            membership = UserStoreMembership(
                user_id=manager.id,
                store_id=store.id,
                assignment_managed=True,
                assignment_previous_active=False,
                assignment_previous_can_read=False,
                assignment_previous_can_write=False,
            )
            db.add(membership)
        elif not membership.assignment_managed:
            membership.assignment_managed = True
            membership.assignment_previous_active = membership.active
            membership.assignment_previous_can_read = membership.can_read
            membership.assignment_previous_can_write = membership.can_write
        membership.can_read = True
        membership.can_write = True
        membership.active = True
    db.commit()
    return {"ok": True}


@router.post("/api/stores/{store_id}/toggle")
def toggle_store(store_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "stores.manage")
    store = require_authorized_store(db, user, store_id=store_id, write=True, active_only=False)
    store.active = not store.active
    db.commit()
    return {"ok": True, "store_name": store.store_name, "active": store.active}


def store_to_dict(store: Store, company: Company | None = None, sync_status: JdWorkbenchStoreStatus | None = None):
    return {
        "id": store.id,
        "platform": store.platform,
        "store_code": store.store_code,
        "store_name": store.store_name,
        "subject_id": store.company_id,
        "subject_code": company.company_code if company else None,
        "subject_name": company.company_name if company else None,
        "active": store.active,
        "notes": store.notes,
        "created_at": store.created_at.isoformat() if store.created_at else None,
        "manager": {"id": store.manager.id, "username": store.manager.username, "display_name": store.manager.display_name} if store.manager else None,
        "login_status": sync_status.status if sync_status else "OFFLINE",
        "login_reason": sync_status.reason_code if sync_status else None,
        "last_sync_at": sync_status.last_sync_at.isoformat() if sync_status and sync_status.last_sync_at else None,
    }


def store_metric_to_dict(store: Store, jd_metric: JdDailyMetric | None, legacy_metric: MetricDaily | None):
    return {
        "store_id": store.id,
        "store_code": store.store_code,
        "store_name": store.store_name,
        "manager": {"id": store.manager.id, "display_name": store.manager.display_name} if store.manager else None,
        "sales_amount": float(jd_metric.gmv if jd_metric else (legacy_metric.sales_amount if legacy_metric else 0)),
        "profit_amount": float(jd_metric.profit_amount if jd_metric else (legacy_metric.profit_amount if legacy_metric else 0)),
        "ad_spend": float(jd_metric.ad_spend if jd_metric else (legacy_metric.ad_spend if legacy_metric else 0)),
        "roi": float(jd_metric.roi if jd_metric else (legacy_metric.roi if legacy_metric else 0)),
        "orders_count": int(jd_metric.paid_orders_count if jd_metric else (legacy_metric.orders_count if legacy_metric else 0)),
        "visitors_count": int(jd_metric.visitors_count if jd_metric else (legacy_metric.visitors_count if legacy_metric else 0)),
        "refunds_count": int(jd_metric.refunds_count if jd_metric else (legacy_metric.refunds_count if legacy_metric else 0)),
        "after_sales_count": int(jd_metric.after_sales_count if jd_metric else (legacy_metric.after_sales_count if legacy_metric else 0)),
        "favorites_count": int(jd_metric.favorites_count if jd_metric else 0),
        "cart_add_count": int(jd_metric.cart_add_count if jd_metric else 0),
        "conversion_rate": float(jd_metric.conversion_rate if jd_metric else 0),
        "active": bool(store.active),
    }


def assess_store_health(store):
    score = 100
    alerts = []
    if not store["active"]:
        score -= 40
        alerts.append("店铺已停用")
    if not store["manager"]:
        score -= 15
        alerts.append("未分配负责人")
    if store["sales_amount"] <= 0:
        score -= 25
        alerts.append("今日暂无成交")
    if store["ad_spend"] > 0 and store["roi"] < 1:
        score -= 20
        alerts.append("广告ROI低于1")
    if store["refunds_count"] >= 5:
        score -= 10
        alerts.append("退款数偏高")
    if store["after_sales_count"] >= 5:
        score -= 10
        alerts.append("售后数偏高")
    if store["visitors_count"] <= 0:
        score -= 10
        alerts.append("访客数据缺失")
    score = max(0, min(100, score))
    return score, "健康" if score >= 85 else ("关注" if score >= 60 else "异常"), alerts


def require_store_read(request: Request, db: Session):
    user = current_user(request, db)
    permissions = get_role_permissions(db, normalize_role(user.role))
    if not permissions.intersection({"menu.stores", "menu.jd_data", "data.metrics.read", "data.metrics.write"}):
        raise HTTPException(status_code=403, detail="没有店铺数据访问权限")
    return user
