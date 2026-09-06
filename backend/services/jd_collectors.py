from datetime import date, datetime, timezone
import json
import os
import hmac
import re
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import JdAccount, JdAd, JdDailyMetric, JdOrder, JdProduct, Store


class JdCollectorError(RuntimeError):
    pass


DATASET_MODELS = {"metrics": JdDailyMetric, "orders": JdOrder, "products": JdProduct, "ads": JdAd}
DATASET_FIELDS = {
    "metrics": "gmv profit_amount visitors_count paid_orders_count ad_spend roi refunds_count after_sales_count favorites_count cart_add_count conversion_rate today_sales visitors orders refunds after_sales",
    "orders": "order_no order_date paid_amount profit_amount order_status",
    "products": "sku_id stat_date product_name category_name stock_quantity sales_amount sales_quantity visitors_count conversion_rate",
    "ads": "campaign_id campaign_name ad_spend clicks impressions roi cpa deal_amount",
}
METRIC_ALIASES = {"today_sales": "gmv", "visitors": "visitors_count", "orders": "paid_orders_count",
                  "refunds": "refunds_count", "after_sales": "after_sales_count"}
BUSINESS_KEYS = {"orders": "order_no", "products": "sku_id", "ads": "campaign_id"}


def validate_dataset(dataset: str, captured):
    """Validate the complete capture before any persistence or coercion."""
    if dataset not in DATASET_FIELDS:
        raise JdCollectorError("未知采集数据集")
    rows = [captured] if dataset == "metrics" else captured
    if not isinstance(rows, list):
        raise JdCollectorError("云端采集响应校验失败")
    for row in rows:
        if not isinstance(row, dict) or not row or set(row) - set(DATASET_FIELDS[dataset].split()):
            raise JdCollectorError("采集字段无效")
        business_key = BUSINESS_KEYS.get(dataset)
        if business_key and (not isinstance(row.get(business_key), str) or not row[business_key].strip()):
            raise JdCollectorError(f"采集缺少 {business_key}")
        for name, value in row.items():
            field = METRIC_ALIASES.get(name, name) if dataset == "metrics" else name
            if name != field and field in row:
                raise JdCollectorError("采集字段重复")
            column = DATASET_MODELS[dataset].__table__.columns[field]
            kind = column.type.python_type
            if kind is str:
                valid = isinstance(value, str) and len(value) <= column.type.length and not any(ord(c) < 32 for c in value)
                if field == business_key:
                    valid = valid and value == value.strip()
            elif kind is date:
                try:
                    valid = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
                except ValueError:
                    valid = False
            else:
                valid = type(value) in (int, float, str, Decimal)
                valid = valid and bool(re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", str(value)))
                try:
                    numeric = Decimal(str(value)) if valid else Decimal("NaN")
                    valid = numeric.is_finite()
                    if valid and kind is int:
                        valid = numeric == numeric.to_integral_value() and 0 <= numeric <= 2147483647
                    elif valid:
                        scale = column.type.scale
                        valid = abs(numeric) < Decimal(10) ** (column.type.precision - scale) and numeric == numeric.quantize(Decimal(10) ** -scale)
                except InvalidOperation:
                    valid = False
            if not valid:
                raise JdCollectorError(f"采集字段类型无效: {name}")
    return captured


class JdSmartCollector:
    """京东商智采集适配器。

    生产环境应在这里接入京东商智授权后的接口或浏览器自动化采集器。
    当前实现使用 account.access_token / refresh_token 作为真实接入前置条件；
    没有授权时不会伪造数据。
    """

    def _capture(self, account: JdAccount, dataset: str, store: Store):
        endpoint = os.getenv(
            "JD_BROWSER_CAPTURE_BASE_URL",
            "http://jd-browser-runtime:8787/internal/jd-browser",
        ).rstrip("/")
        token = os.getenv("JD_BROWSER_CAPTURE_TOKEN", "")
        if len(token.encode()) < 32:
            raise JdCollectorError("云端浏览器内部认证未配置")
        if not endpoint:
            raise JdCollectorError("云端浏览器运行时未配置")
        namespace = os.getenv("JD_SESSION_NAMESPACE", "").strip()
        if not namespace:
            raise JdCollectorError("会话命名空间未配置")
        payload = {"scope": {"namespace": namespace, "tenant_id": str(store.tenant_id), "company_id": str(store.company_id), "store_id": str(store.id), "platform": "jd"}, "dataset": dataset}
        try:
            with urlopen(Request(endpoint + "/capture", data=json.dumps(payload).encode(), headers={"content-type": "application/json", "x-internal-token": token}), timeout=45) as response:
                result = json.loads(response.read(1_000_000))
        except Exception as exc:
            raise JdCollectorError("云端浏览器采集失败") from exc
        if not isinstance(result, dict) or set(result) != {"status", "data"} or result.get("status") != "OK":
            raise JdCollectorError("需要人工处理登录或风控")
        data = result["data"]
        if (not isinstance(data, dict) or set(data) != {"source", "captured_at", "store_id", dataset}
                or str(data.get("store_id")) != str(store.id) or data.get("source") != "jd_cloud_playwright"):
            raise JdCollectorError("云端采集响应校验失败")
        try:
            if datetime.fromisoformat(data["captured_at"].replace("Z", "+00:00")).tzinfo is None:
                raise ValueError("missing timezone")
        except (TypeError, ValueError, AttributeError):
            raise JdCollectorError("云端采集响应校验失败") from None
        captured = data.get(dataset)
        if (dataset == "metrics" and not isinstance(captured, dict)) or (
            dataset != "metrics"
            and (not isinstance(captured, list) or any(not isinstance(row, dict) for row in captured))
        ):
            raise JdCollectorError("云端采集响应校验失败")
        return validate_dataset(dataset, captured)

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


def sync_jd_smart(db: Session, store_id: int, metric_date: date | None = None, completion_log=None, before_commit=None):
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
    if completion_log is not None:
        completion_log.status = "success"
        completion_log.message = str(result)
        completion_log.finished_at = datetime.now(timezone.utc)
    if before_commit is not None:
        before_commit()
    db.commit()
    return {"saved": 1}


def sync_jzt(db: Session, store_id: int, stat_date: date | None = None):
    account = (
        db.query(JdAccount)
        .filter(JdAccount.store_id == store_id, JdAccount.account_type == "jzt", JdAccount.active.is_(True))
        .one_or_none()
    )
    if not account:
        raise JdCollectorError("店铺未配置京准通账号")
    rows = validate_dataset("ads", JztCollector().fetch_ads_today(account))
    saved = set()
    with db.begin_nested():
        for row in rows:
            save_ad(db, store_id, account.id, stat_date or date.today(), row)
            saved.add(row["campaign_id"])
    account.last_sync_at = datetime.now(timezone.utc)
    account.login_status = "ok"
    account.cookie_status = "ok"
    db.commit()
    return {"saved": len(saved)}


def sync_jd_orders(db: Session, store_id: int, order_date: date | None = None):
    account = get_smart_account(db, store_id)
    rows = validate_dataset("orders", JdSmartCollector().fetch_orders_today(account))
    saved = set()
    with db.begin_nested():
        for row in rows:
            save_order(db, store_id, {**row, "order_date": row.get("order_date") or (order_date or date.today()).isoformat()})
            saved.add(row["order_no"])
    account.last_sync_at = datetime.now(timezone.utc)
    db.commit()
    return {"saved": len(saved)}


def sync_jd_products(db: Session, store_id: int, stat_date: date | None = None):
    account = get_smart_account(db, store_id)
    rows = validate_dataset("products", JdSmartCollector().fetch_products_today(account))
    saved = set()
    with db.begin_nested():
        for row in rows:
            save_product(db, store_id, {**row, "stat_date": row.get("stat_date") or (stat_date or date.today()).isoformat()})
            saved.add((row.get("stat_date") or (stat_date or date.today()).isoformat(), row["sku_id"]))
    account.last_sync_at = datetime.now(timezone.utc)
    db.commit()
    return {"saved": len(saved)}


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
    validate_dataset("metrics", payload)
    metric = JdDailyMetric(store_id=store_id, metric_date=metric_date)
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
    values = {column.name: getattr(metric, column.name) for column in JdDailyMetric.__table__.columns
              if column.name not in {"id", "created_at", "updated_at"}}
    _upsert_business_row(db, JdDailyMetric, ("store_id", "metric_date"), values)
    return db.query(JdDailyMetric).filter_by(store_id=store_id, metric_date=metric_date).populate_existing().one()


def save_order(db: Session, store_id: int, row: dict):
    validate_dataset("orders", [row])
    order_no = str(row.get("order_no", "")).strip()
    if not order_no:
        raise JdCollectorError("订单缺少 order_no")
    values = {
        "store_id": store_id, "order_no": order_no,
        "order_date": parse_date(row.get("order_date")) or date.today(),
        "paid_amount": number(row.get("paid_amount")), "profit_amount": number(row.get("profit_amount")),
        "order_status": row.get("order_status"), "buyer_pin": None, "raw_payload": None,
        "synced_at": datetime.now(timezone.utc),
    }
    _upsert_business_row(db, JdOrder, ("order_no",), values)
    return db.query(JdOrder).filter_by(store_id=store_id, order_no=order_no).populate_existing().one()


def save_product(db: Session, store_id: int, row: dict):
    validate_dataset("products", [row])
    raw_sku_id = row.get("sku_id")
    sku_id = str(raw_sku_id).strip() if raw_sku_id is not None else ""
    if not sku_id:
        raise JdCollectorError("商品缺少 sku_id")
    stat_date = parse_date(row.get("stat_date")) or date.today()
    values = {
        "store_id": store_id,
        "stat_date": stat_date,
        "sku_id": sku_id,
        "product_name": row.get("product_name", ""),
        "category_name": row.get("category_name"),
        "stock_quantity": int(number(row.get("stock_quantity"))),
        "sales_amount": number(row.get("sales_amount")),
        "sales_quantity": int(number(row.get("sales_quantity"))),
        "visitors_count": int(number(row.get("visitors_count"))),
        "conversion_rate": number(row.get("conversion_rate")),
        "raw_payload": None,
        "synced_at": datetime.now(timezone.utc),
    }
    _upsert_business_row(db, JdProduct, ("store_id", "stat_date", "sku_id"), values)
    return db.query(JdProduct).filter(
        JdProduct.store_id == store_id,
        JdProduct.stat_date == stat_date,
        JdProduct.sku_id == sku_id,
    ).populate_existing().one()


def save_ad(db: Session, store_id: int, account_id: int | None, stat_date: date, row: dict):
    validate_dataset("ads", [row])
    raw_campaign_id = row.get("campaign_id")
    campaign_id = str(raw_campaign_id).strip() if raw_campaign_id is not None else ""
    if not campaign_id:
        raise JdCollectorError("广告缺少 campaign_id")
    values = {
        "store_id": store_id,
        "stat_date": stat_date,
        "campaign_id": campaign_id,
        "account_id": account_id,
        "campaign_name": row.get("campaign_name", ""),
        "ad_spend": number(row.get("ad_spend")),
        "clicks": int(number(row.get("clicks"))),
        "impressions": int(number(row.get("impressions"))),
        "roi": number(row.get("roi")),
        "cpa": number(row.get("cpa")),
        "deal_amount": number(row.get("deal_amount")),
        "raw_payload": None,
        "synced_at": datetime.now(timezone.utc),
    }
    _upsert_business_row(db, JdAd, ("store_id", "stat_date", "campaign_id"), values)
    return db.query(JdAd).filter(
        JdAd.store_id == store_id,
        JdAd.stat_date == stat_date,
        JdAd.campaign_id == campaign_id,
    ).populate_existing().one()


def _upsert_business_row(db: Session, model, key_columns: tuple[str, ...], values: dict) -> None:
    if db.get_bind().dialect.name == "postgresql":
        statement = pg_insert(model).values(**values)
        result = db.execute(statement.on_conflict_do_update(
            index_elements=list(key_columns),
            set_={key: statement.excluded[key] for key in values if key not in key_columns},
            where=model.store_id == values["store_id"],
        ))
        if result.rowcount != 1:
            raise JdCollectorError("采集业务主键与店铺不匹配")
        return

    row = db.query(model).filter_by(**{key: values[key] for key in key_columns}).one_or_none()
    if row is not None and row.store_id != values["store_id"]:
        raise JdCollectorError("采集业务主键与店铺不匹配")
    if row is None:
        row = model(**{key: values[key] for key in key_columns})
        db.add(row)
    for key, value in values.items():
        if key not in key_columns:
            setattr(row, key, value)
    db.flush()


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
