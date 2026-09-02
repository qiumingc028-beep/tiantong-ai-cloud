from datetime import date, datetime, timezone
import json
import os
import hmac
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from ..models import JdAccount, JdAd, JdDailyMetric, JdOrder, JdProduct, Store


class JdCollectorError(RuntimeError):
    pass


class JdSmartCollector:
    """京东商智采集适配器。

    生产环境应在这里接入京东商智授权后的接口或浏览器自动化采集器。
    当前实现使用 account.access_token / refresh_token 作为真实接入前置条件；
    没有授权时不会伪造数据。
    """

    def _capture(self, account: JdAccount, dataset: str, store: Store):
        endpoint = "http://jd-browser-runtime:8787/internal/jd-browser"
        token = os.getenv("JD_BROWSER_CAPTURE_TOKEN", "")
        if len(token.encode()) < 32:
            raise JdCollectorError("云端浏览器内部认证未配置")
        if not endpoint:
            raise JdCollectorError("云端浏览器运行时未配置")
        payload = {"tenant_id": store.tenant_id, "company_id": store.company_id, "store_id": store.id, "platform": store.platform, "dataset": dataset}
        try:
            with urlopen(Request(endpoint + "/capture", data=json.dumps(payload).encode(), headers={"content-type": "application/json", "x-internal-token": token}), timeout=45) as response:
                result = json.loads(response.read(1_000_000))
        except Exception as exc:
            raise JdCollectorError("云端浏览器采集失败") from exc
        if not isinstance(result, dict) or set(result) != {"status", "data"} or result.get("status") in {"LOGIN_REQUIRED", "CAPTCHA", "RISK_CONTROL"}:
            raise JdCollectorError("需要人工处理登录或风控")
        data = result["data"]
        if not isinstance(data, dict) or data.get("store_id") != store.id or data.get("source") != "jd_cloud_playwright":
            raise JdCollectorError("云端采集响应校验失败")
        return data

    def fetch_today(self, account: JdAccount) -> dict:
        return self._capture(account, "metrics", account.store)

    def fetch_orders_today(self, account: JdAccount) -> list[dict]:
        return self._capture(account, "orders", account.store)

    def fetch_products_today(self, account: JdAccount) -> list[dict]:
        return self._capture(account, "products", account.store)


class JztCollector:
    """京准通采集适配器。"""

    def fetch_ads_today(self, account: JdAccount) -> list[dict]:
        return JdSmartCollector()._capture(account, "ads", account.store)


def sync_jd_smart(db: Session, store_id: int, metric_date: date | None = None):
    store = db.get(Store, store_id)
    if not store:
        raise JdCollectorError("店铺不存在")
    account = (
        db.query(JdAccount)
        .filter(JdAccount.store_id == store_id, JdAccount.account_type == "jd_smart", JdAccount.active.is_(True))
        .one_or_none()
    )
    if not account:
        raise JdCollectorError("店铺未配置京东商智账号")
    payload = JdSmartCollector().fetch_today(account)
    result = save_jd_daily_metric(db, store_id, metric_date or date.today(), payload, "jd_smart")
    account.last_sync_at = datetime.now(timezone.utc)
    account.login_status = "ok"
    account.cookie_status = "ok"
    db.commit()
    return result


def sync_jzt(db: Session, store_id: int, stat_date: date | None = None):
    account = (
        db.query(JdAccount)
        .filter(JdAccount.store_id == store_id, JdAccount.account_type == "jzt", JdAccount.active.is_(True))
        .one_or_none()
    )
    if not account:
        raise JdCollectorError("店铺未配置京准通账号")
    rows = JztCollector().fetch_ads_today(account)
    saved = 0
    for row in rows:
        db.add(
            JdAd(
                store_id=store_id,
                account_id=account.id,
                stat_date=stat_date or date.today(),
                campaign_id=str(row.get("campaign_id", "")),
                campaign_name=row.get("campaign_name", ""),
                ad_spend=number(row.get("ad_spend")),
                clicks=int(number(row.get("clicks"))),
                impressions=int(number(row.get("impressions"))),
                roi=number(row.get("roi")),
                cpa=number(row.get("cpa")),
                deal_amount=number(row.get("deal_amount")),
                raw_payload=None,
            )
        )
        saved += 1
    account.last_sync_at = datetime.now(timezone.utc)
    account.login_status = "ok"
    account.cookie_status = "ok"
    db.commit()
    return {"saved": saved}


def sync_jd_orders(db: Session, store_id: int, order_date: date | None = None):
    account = get_smart_account(db, store_id)
    rows = JdSmartCollector().fetch_orders_today(account)
    saved = 0
    for row in rows:
        save_order(db, store_id, {**row, "order_date": row.get("order_date") or (order_date or date.today()).isoformat()})
        saved += 1
    account.last_sync_at = datetime.now(timezone.utc)
    db.commit()
    return {"saved": saved}


def sync_jd_products(db: Session, store_id: int, stat_date: date | None = None):
    account = get_smart_account(db, store_id)
    rows = JdSmartCollector().fetch_products_today(account)
    saved = 0
    for row in rows:
        save_product(db, store_id, {**row, "stat_date": row.get("stat_date") or (stat_date or date.today()).isoformat()})
        saved += 1
    account.last_sync_at = datetime.now(timezone.utc)
    db.commit()
    return {"saved": saved}


def get_smart_account(db: Session, store_id: int):
    account = (
        db.query(JdAccount)
        .filter(JdAccount.store_id == store_id, JdAccount.account_type == "jd_smart", JdAccount.active.is_(True))
        .one_or_none()
    )
    if not account:
        raise JdCollectorError("店铺未配置京东商智账号")
    return account


def save_jd_daily_metric(db: Session, store_id: int, metric_date: date, payload: dict, source: str):
    metric = (
        db.query(JdDailyMetric)
        .filter(JdDailyMetric.store_id == store_id, JdDailyMetric.metric_date == metric_date)
        .one_or_none()
    )
    if not metric:
        metric = JdDailyMetric(store_id=store_id, metric_date=metric_date)
        db.add(metric)
    metric.gmv = number(payload.get("gmv") or payload.get("today_sales"))
    metric.profit_amount = number(payload.get("profit_amount"))
    metric.visitors_count = int(number(payload.get("visitors_count") or payload.get("visitors")))
    metric.paid_orders_count = int(number(payload.get("paid_orders_count") or payload.get("orders")))
    metric.ad_spend = number(payload.get("ad_spend"))
    metric.roi = number(payload.get("roi"))
    metric.refunds_count = int(number(payload.get("refunds_count") or payload.get("refunds")))
    metric.after_sales_count = int(number(payload.get("after_sales_count") or payload.get("after_sales")))
    metric.favorites_count = int(number(payload.get("favorites_count")))
    metric.cart_add_count = int(number(payload.get("cart_add_count")))
    metric.conversion_rate = number(payload.get("conversion_rate"))
    metric.source = source
    metric.raw_payload = None
    metric.synced_at = datetime.now(timezone.utc)
    db.commit()
    return metric


def save_order(db: Session, store_id: int, row: dict):
    order_no = str(row.get("order_no", "")).strip()
    if not order_no:
        raise JdCollectorError("订单缺少 order_no")
    order = db.query(JdOrder).filter(JdOrder.order_no == order_no).one_or_none()
    if not order:
        order = JdOrder(store_id=store_id, order_no=order_no, order_date=parse_date(row.get("order_date")) or date.today())
        db.add(order)
    order.paid_amount = number(row.get("paid_amount"))
    order.profit_amount = number(row.get("profit_amount"))
    order.order_status = row.get("order_status")
    order.buyer_pin = None
    order.raw_payload = None
    return order


def save_product(db: Session, store_id: int, row: dict):
    product = JdProduct(
        store_id=store_id,
        sku_id=str(row.get("sku_id", "")).strip(),
        product_name=row.get("product_name", ""),
        category_name=row.get("category_name"),
        stock_quantity=int(number(row.get("stock_quantity"))),
        sales_amount=number(row.get("sales_amount")),
        sales_quantity=int(number(row.get("sales_quantity"))),
        visitors_count=int(number(row.get("visitors_count"))),
        conversion_rate=number(row.get("conversion_rate")),
        stat_date=parse_date(row.get("stat_date")) or date.today(),
        raw_payload=None,
    )
    db.add(product)
    return product


def number(value):
    try:
        return float(value or 0)
    except Exception:
        return 0


def parse_date(value):
    if not value:
        return None
    if hasattr(value, "date"):
        return value.date()
    try:
        return datetime.fromisoformat(str(value)).date()
    except Exception:
        return None
