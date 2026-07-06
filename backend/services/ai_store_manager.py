from __future__ import annotations

from typing import Optional
from datetime import date

from sqlalchemy.orm import Session

from ..models import JdAd, JdDailyMetric, JdProduct, Store


def analyze_store_health(db: Session, metric_date: Optional[date] = None):
    metric_date = metric_date or date.today()
    metrics = {m.store_id: m for m in db.query(JdDailyMetric).filter(JdDailyMetric.metric_date == metric_date).all()}
    stores = db.query(Store).filter(Store.platform == "jd", Store.active.is_(True)).all()
    suggestions = []
    for store in stores:
        metric = metrics.get(store.id)
        if not metric:
            suggestions.append({"store_id": store.id, "store_name": store.store_name, "level": "warning", "message": "今日暂无商智数据，需检查采集任务或账号授权。"})
            continue
        if float(metric.gmv or 0) <= 0:
            suggestions.append({"store_id": store.id, "store_name": store.store_name, "level": "critical", "message": "今日GMV为0，需优先排查流量、商品和支付链路。"})
        if float(metric.ad_spend or 0) > 0 and float(metric.roi or 0) < 1:
            suggestions.append({"store_id": store.id, "store_name": store.store_name, "level": "warning", "message": "广告ROI低于1，建议暂停低效计划并复盘关键词。"})
        if int(metric.refunds_count or 0) >= 5 or int(metric.after_sales_count or 0) >= 5:
            suggestions.append({"store_id": store.id, "store_name": store.store_name, "level": "warning", "message": "退款或售后偏高，建议客服跟进商品评价和售后原因。"})

    low_products = (
        db.query(JdProduct)
        .filter(JdProduct.stat_date == metric_date, JdProduct.stock_quantity <= 5)
        .limit(20)
        .all()
    )
    for product in low_products:
        suggestions.append({"store_id": product.store_id, "store_name": product.store.store_name if product.store else "", "level": "warning", "message": f"商品 {product.product_name} 库存偏低，当前库存 {product.stock_quantity}。"})

    bad_ads = db.query(JdAd).filter(JdAd.stat_date == metric_date, JdAd.ad_spend > 0, JdAd.roi < 1).limit(20).all()
    for ad in bad_ads:
        suggestions.append({"store_id": ad.store_id, "store_name": ad.store.store_name if ad.store else "", "level": "warning", "message": f"广告计划 {ad.campaign_name or ad.campaign_id} ROI低于1，建议降预算或暂停。"})

    return suggestions
