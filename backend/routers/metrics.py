from __future__ import annotations

from typing import Optional
import csv
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import current_user, require_permission_user
from ..database import get_db, get_redis
from ..models import AiTask, JdDailyMetric, MetricDaily, Store


router = APIRouter()


@router.get("/api/jd/metrics/summary")
def jd_metrics_summary(request: Request, db: Session = Depends(get_db)):
    current_user(request, db)
    return metrics_summary(db)


@router.get("/api/owner/dashboard")
def owner_dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "menu.dashboard")
    data = metrics_summary(db)
    data["user"] = {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role}
    data["title"] = "老板驾驶舱"
    return data


@router.post("/api/metrics/manual")
async def save_manual_metrics(request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "data.metrics.write")
    data = await request.json()
    store_id = data.get("store_id")
    if not store_id:
        raise HTTPException(status_code=400, detail="请选择店铺")
    if not db.get(Store, store_id):
        raise HTTPException(status_code=404, detail="店铺不存在")
    metric_date = parse_date(data.get("metric_date")) or date.today()
    upsert_metric(db, store_id, metric_date, data, "manual", user.id)
    upsert_jd_daily_from_manual(db, store_id, metric_date, data)
    db.commit()
    return {"ok": True, "message": "数据已保存"}


@router.get("/api/metrics/today")
def metrics_today(request: Request, db: Session = Depends(get_db)):
    current_user(request, db)
    jd_metrics = {m.store_id: m for m in db.query(JdDailyMetric).filter(JdDailyMetric.metric_date == date.today()).all()}
    legacy_metrics = {m.store_id: m for m in db.query(MetricDaily).filter(MetricDaily.metric_date == date.today()).all()}
    stores = db.query(Store).filter(Store.active.is_(True)).order_by(Store.id.asc()).all()
    return [metric_row(store, jd_metrics.get(store.id), legacy_metrics.get(store.id)) for store in stores]


@router.post("/api/metrics/import")
async def import_metrics_file(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "data.metrics.write")
    content = await file.read()
    filename = (file.filename or "").lower()
    if filename.endswith(".xlsx"):
        rows = read_xlsx_rows(content)
    elif filename.endswith(".csv"):
        rows = list(csv.DictReader(StringIO(content.decode("utf-8-sig"))))
    else:
        raise HTTPException(status_code=400, detail="只支持 .xlsx 或 .csv 文件")

    imported = 0
    errors = []
    for index, row in enumerate(rows, start=2):
        store_code = str(get_value(row, "店铺编号", "store_code", "编号") or "").strip()
        if not store_code:
            errors.append(f"第{index}行：缺少店铺编号")
            continue
        store = db.query(Store).filter(Store.store_code == store_code).one_or_none()
        if not store:
            errors.append(f"第{index}行：找不到店铺编号 {store_code}")
            continue
        data = {
            "sales_amount": get_value(row, "今日成交", "成交", "sales_amount"),
            "profit_amount": get_value(row, "今日利润", "利润", "profit_amount"),
            "ad_spend": get_value(row, "广告花费", "广告费", "ad_spend"),
            "roi": get_value(row, "ROI", "roi"),
            "orders_count": get_value(row, "订单数", "订单", "orders_count"),
            "visitors_count": get_value(row, "访客数", "访客", "visitors_count"),
            "refunds_count": get_value(row, "退款数", "退款", "refunds_count"),
            "after_sales_count": get_value(row, "售后数", "售后", "after_sales_count"),
            "favorites_count": get_value(row, "收藏", "favorites_count"),
            "cart_add_count": get_value(row, "加购", "cart_add_count"),
            "conversion_rate": get_value(row, "转化率", "conversion_rate"),
        }
        metric_date = parse_date(get_value(row, "日期", "metric_date", "date")) or date.today()
        upsert_metric(db, store.id, metric_date, data, "excel", user.id)
        upsert_jd_daily_from_manual(db, store.id, metric_date, data)
        imported += 1
    db.commit()
    return {"ok": True, "imported": imported, "errors": errors}


def metrics_summary(db: Session):
    r = (
        db.query(
            func.coalesce(func.sum(JdDailyMetric.gmv), 0),
            func.coalesce(func.sum(JdDailyMetric.profit_amount), 0),
            func.coalesce(func.sum(JdDailyMetric.ad_spend), 0),
            func.coalesce(func.sum(JdDailyMetric.paid_orders_count), 0),
            func.coalesce(func.sum(JdDailyMetric.visitors_count), 0),
            func.coalesce(func.sum(JdDailyMetric.refunds_count), 0),
            func.coalesce(func.sum(JdDailyMetric.after_sales_count), 0),
        )
        .filter(JdDailyMetric.metric_date == date.today())
        .one()
    )
    gmv = float(r[0] or 0)
    ad = float(r[2] or 0)
    ai_tasks = db.query(AiTask).order_by(AiTask.id.asc()).all()
    return {
        "today_sales": gmv,
        "today_gmv": gmv,
        "today_profit": float(r[1] or 0),
        "ad_spend": ad,
        "roi": round(gmv / ad, 2) if ad > 0 else 0,
        "orders": int(r[3] or 0),
        "visitors": int(r[4] or 0),
        "refunds": int(r[5] or 0),
        "after_sales": int(r[6] or 0),
        "stores": db.query(Store).filter(Store.platform == "jd", Store.active.is_(True)).count(),
        "ai_employees_online": count_online_employees(),
        "ai_task_status": [{"name": t.ai_employee_name, "status": t.status} for t in ai_tasks],
    }


def upsert_metric(db: Session, store_id: int, metric_date: date, data: dict, source: str, user_id: int):
    metric = db.query(MetricDaily).filter(MetricDaily.store_id == store_id, MetricDaily.metric_date == metric_date).one_or_none()
    if not metric:
        metric = MetricDaily(store_id=store_id, metric_date=metric_date)
        db.add(metric)
    metric.sales_amount = safe_number(data.get("sales_amount"))
    metric.profit_amount = safe_number(data.get("profit_amount"))
    metric.ad_spend = safe_number(data.get("ad_spend"))
    metric.roi = safe_number(data.get("roi"))
    metric.orders_count = safe_int(data.get("orders_count"))
    metric.visitors_count = safe_int(data.get("visitors_count"))
    metric.refunds_count = safe_int(data.get("refunds_count"))
    metric.after_sales_count = safe_int(data.get("after_sales_count"))
    metric.source = source
    metric.created_by = user_id


def upsert_jd_daily_from_manual(db: Session, store_id: int, metric_date: date, data: dict):
    metric = db.query(JdDailyMetric).filter(JdDailyMetric.store_id == store_id, JdDailyMetric.metric_date == metric_date).one_or_none()
    if not metric:
        metric = JdDailyMetric(store_id=store_id, metric_date=metric_date)
        db.add(metric)
    metric.gmv = safe_number(data.get("sales_amount"))
    metric.profit_amount = safe_number(data.get("profit_amount"))
    metric.ad_spend = safe_number(data.get("ad_spend"))
    metric.roi = safe_number(data.get("roi"))
    metric.paid_orders_count = safe_int(data.get("orders_count"))
    metric.visitors_count = safe_int(data.get("visitors_count"))
    metric.refunds_count = safe_int(data.get("refunds_count"))
    metric.after_sales_count = safe_int(data.get("after_sales_count"))
    metric.favorites_count = safe_int(data.get("favorites_count"))
    metric.cart_add_count = safe_int(data.get("cart_add_count"))
    metric.conversion_rate = safe_number(data.get("conversion_rate"))
    metric.source = "manual"


def metric_row(store: Store, jd_metric: Optional[JdDailyMetric], legacy_metric: Optional[MetricDaily]):
    return {
        "store_id": store.id,
        "store_code": store.store_code,
        "store_name": store.store_name,
        "sales_amount": float(jd_metric.gmv if jd_metric else (legacy_metric.sales_amount if legacy_metric else 0)),
        "profit_amount": float(jd_metric.profit_amount if jd_metric else (legacy_metric.profit_amount if legacy_metric else 0)),
        "ad_spend": float(jd_metric.ad_spend if jd_metric else (legacy_metric.ad_spend if legacy_metric else 0)),
        "roi": float(jd_metric.roi if jd_metric else (legacy_metric.roi if legacy_metric else 0)),
        "orders_count": int(jd_metric.paid_orders_count if jd_metric else (legacy_metric.orders_count if legacy_metric else 0)),
        "visitors_count": int(jd_metric.visitors_count if jd_metric else (legacy_metric.visitors_count if legacy_metric else 0)),
        "refunds_count": int(jd_metric.refunds_count if jd_metric else (legacy_metric.refunds_count if legacy_metric else 0)),
        "after_sales_count": int(jd_metric.after_sales_count if jd_metric else (legacy_metric.after_sales_count if legacy_metric else 0)),
    }


def read_xlsx_rows(content):
    wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
    ws = wb.active
    headers = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    return [{h: values[idx] if idx < len(values) else None for idx, h in enumerate(headers)} for values in ws.iter_rows(min_row=2, values_only=True) if any(values)]


def safe_number(v):
    try:
        return float(v or 0)
    except Exception:
        return 0


def safe_int(v):
    try:
        return int(float(v or 0))
    except Exception:
        return 0


def parse_date(v):
    if not v:
        return None
    if hasattr(v, "date"):
        return v.date()
    text = str(v).strip().replace("/", "-").replace(".", "-")
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date()
        if text.isdigit():
            n = int(float(text))
            if 20000 <= n <= 60000:
                return (datetime(1899, 12, 30) + timedelta(days=n)).date()
        return datetime.fromisoformat(text).date()
    except Exception:
        return None


def get_value(row, *names):
    for name in names:
        if name in row:
            return row.get(name)
    return None


def count_online_employees():
    try:
        return sum(1 for _ in get_redis().scan_iter("session:*"))
    except Exception:
        return 0
