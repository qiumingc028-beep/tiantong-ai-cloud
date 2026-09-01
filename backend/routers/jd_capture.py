from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from ..auth import require_permission_user
from ..database import get_db
from ..models import JdDailyMetric, Store

router = APIRouter(prefix="/api/jd/capture")

class Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paid_amount: float = 0
    paid_order_count: int = 0
    sold_quantity: int = 0
    refund_count: int = 0
    refund_amount: float = 0
    ad_spend: float = 0

class CapturePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_id: int
    store_name: str = Field(min_length=1, max_length=200)
    subject_id_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_status: str = Field(pattern=r"^(online|expired|captcha|stopped)$")
    captured_at: datetime
    metrics: Metrics

@router.post("")
def receive_capture(payload: CapturePayload, request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "data.metrics.write")
    store = db.get(Store, payload.store_id)
    if not store or store.store_name != payload.store_name:
        raise HTTPException(status_code=422, detail="店铺归属校验失败")
    metric = db.query(JdDailyMetric).filter(JdDailyMetric.store_id == payload.store_id, JdDailyMetric.metric_date == payload.captured_at.date()).one_or_none()
    if not metric:
        metric = JdDailyMetric(store_id=payload.store_id, metric_date=payload.captured_at.date())
        db.add(metric)
    metric.gmv = payload.metrics.paid_amount
    metric.paid_orders_count = payload.metrics.paid_order_count
    metric.refunds_count = payload.metrics.refund_count
    metric.ad_spend = payload.metrics.ad_spend
    metric.roi = payload.metrics.paid_amount / payload.metrics.ad_spend if payload.metrics.ad_spend else 0
    metric.source = "jd_openclaw_readonly"
    metric.synced_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "store_id": payload.store_id, "business_write_count": 0, "readonly_verified": True}

@router.get("/policy")
def capture_policy(request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "data.metrics.read")
    return {"readonly": True, "business_write_count": 0, "allowed_page_prefixes": ["/shop/home", "/shop/order", "/shop/afterSale", "/shop/inventory", "/jzt/"], "blocked_write_semantics": ["order", "inventory", "price", "after_sales", "promotion"]}
