from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import database
from ..auth import get_role_permissions, normalize_role, require_permission_user
from ..config import get_settings
from ..database import get_db
from ..models import (
    JdWorkbenchDevice,
    JdWorkbenchPairingCode,
    JdWorkbenchRecord,
    JdWorkbenchStoreStatus,
    JdWorkbenchSyncBatch,
    JdWorkbenchSyncPolicy,
    EmployeeLog,
    Company,
    Store,
    User,
)
from ..store_authorization import authorized_stores, require_authorized_store


router = APIRouter(prefix="/api/jd-workbench", tags=["jd-workbench"])

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 500
DEFAULT_SYNC_INTERVAL_SECONDS = 300
ALLOWED_SYNC_INTERVAL_SECONDS = frozenset({300, 900, 1800, 3600})
MAX_SYNC_RETRIES = 5
PAIRING_TTL = timedelta(minutes=10)
DEVICE_TTL = timedelta(days=30)
HEX_KEY_RE = re.compile(r"^[0-9a-f]{64}$")
IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")
CLIENT_VERSION_RE = re.compile(r"^[A-Za-z0-9.+_-]{1,64}$")
SOURCE_PERIOD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:/\d{4}-\d{2}-\d{2})?$")
NONCE_RE = re.compile(r"^[0-9a-f]{32}$")
INGEST_PERMISSION = "jd_workbench.ingest"
SIGNATURE_WINDOW_SECONDS = 60
SIGNATURE_NONCE_TTL_SECONDS = 300
RSA_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")

DATASET_FIELDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "sales_daily": (
        frozenset({"source_record_key", "sales_amount", "orders_count"}),
        frozenset(),
    ),
    "orders": (
        frozenset({"source_record_key", "order_count", "paid_amount"}),
        frozenset(),
    ),
    "refunds": (
        frozenset({"source_record_key", "refund_order_count", "refund_amount"}),
        frozenset(),
    ),
    "products": (
        frozenset({"source_record_key", "sku_key", "product_name"}),
        frozenset({"category_name"}),
    ),
    "inventory": (
        frozenset({"source_record_key", "sku_key", "stock_quantity"}),
        frozenset({"low_stock"}),
    ),
    "promotion_costs": (
        frozenset({"source_record_key", "channel", "ad_spend"}),
        frozenset({"attributed_sales", "roi", "promotion_rate"}),
    ),
    "operating_metrics": (
        frozenset({"source_record_key"}),
        frozenset(
            {
                "sales_amount",
                "sales_orders",
                "sales_customers",
                "conversion_rate",
                "product_units",
                "visitors",
                "page_views",
                "month_sales",
                "year_sales",
                "ad_spend",
                "ad_impressions",
                "ad_clicks",
                "ad_ctr",
                "ad_cpm",
                "ad_cpc",
                "pending_shipments",
                "pending_refunds",
                "inventory_risk",
                "abnormal_orders",
            }
        ),
    ),
    "fulfillment_orders": (
        frozenset({"source_record_key", "order_state", "product_name", "quantity", "paid_amount", "ordered_at"}),
        frozenset({"promised_ship_at"}),
    ),
    "aftersale_orders": (
        frozenset({"source_record_key", "aftersale_state", "product_name", "quantity", "refund_amount", "requested_at"}),
        frozenset({"reason_category"}),
    ),
    "abnormal_orders": (
        frozenset({"source_record_key", "abnormal_state", "product_name", "quantity", "detected_at"}),
        frozenset({"reason_category"}),
    ),
}
MONEY_FIELDS = frozenset(
    {
        "sales_amount", "paid_amount", "refund_amount", "ad_spend", "attributed_sales",
        "month_sales", "year_sales", "ad_cpm", "ad_cpc",
    }
)
RATIO_FIELDS = frozenset({"roi", "promotion_rate", "conversion_rate", "ad_ctr"})
INTEGER_FIELDS = frozenset(
    {
        "orders_count", "order_count", "refund_order_count", "stock_quantity",
        "sales_orders", "sales_customers", "product_units", "visitors", "page_views",
        "ad_impressions", "ad_clicks", "pending_shipments", "pending_refunds", "inventory_risk",
        "abnormal_orders", "quantity",
    }
)
TEXT_LIMITS = {
    "product_name": 200, "category_name": 120, "order_state": 64,
    "aftersale_state": 64, "abnormal_state": 64, "reason_category": 120,
}
DATETIME_FIELDS = frozenset({"ordered_at", "promised_ship_at", "requested_at", "detected_at"})
PROMOTION_CHANNELS = frozenset({"jd_kuaiche", "haitou", "jingtiaoke", "jingzhuntong", "other"})
DEVICE_STATUSES = frozenset({"ONLINE", "IDLE", "SYNCING", "PAUSED", "OFFLINE", "ERROR", "HUMAN_ACTION_REQUIRED"})
CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
DashboardPeriod = Literal["latest", "today", "yesterday", "7d"]
OPERATING_MONEY_SUM_FIELDS = ("sales_amount", "ad_spend")
OPERATING_INTEGER_SUM_FIELDS = (
    "sales_orders",
    "sales_customers",
    "product_units",
    "visitors",
    "page_views",
    "ad_impressions",
    "ad_clicks",
)
OPERATING_LATEST_MONEY_FIELDS = ("month_sales", "year_sales")
OPERATING_LATEST_INTEGER_FIELDS = ("pending_shipments", "pending_refunds", "inventory_risk", "abnormal_orders")
OPERATING_DERIVED_FIELDS = ("conversion_rate", "ad_ctr", "ad_cpm", "ad_cpc")
HUMAN_REASON_CODES = frozenset(
    {
        "CAPTCHA_REQUIRED",
        "SMS_REQUIRED",
        "QR_REQUIRED",
        "RISK_CONTROL",
        "LOGIN_EXPIRED",
        "UNKNOWN_DOMAIN",
        "AUTHORIZATION_REVOKED",
        "STORE_IDENTITY_MISMATCH",
    }
)
SYNC_ERROR_CODES = frozenset(
    {
        "CLOUD_CONNECTION_FAILED", "COLLECTOR_PAGE_LOAD_FAILED", "COLLECTOR_SCHEMA_MISMATCH",
        "COLLECTOR_EMPTY", "SYNC_UPLOAD_REJECTED", "LOGIN_EXPIRED", "RISK_CONTROL",
        "CAPTCHA_REQUIRED",
    }
)
SYNC_TOP_LEVEL = frozenset(
    {
        "store_id",
        "subject_id",
        "dataset_type",
        "source_period",
        "collected_at",
        "idempotency_key",
        "client_version",
        "records",
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _generic_bad_request() -> HTTPException:
    return HTTPException(status_code=400, detail="请求字段不符合R297只读自动同步合同")


@router.post("/internal/browser-session-authorize", status_code=204)
async def authorize_browser_session(request: Request, db: Session = Depends(get_db)):
    """Fail-closed capability check used only by the isolated browser runtime."""
    expected = get_settings().JD_BROWSER_CONTROL_TOKEN
    supplied = request.headers.get("x-internal-token", "")
    if len(expected) < 32 or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="浏览器控制凭据无效")
    body = await _json_body(request)
    required = {"tenant_id", "company_id", "store_id", "platform"}
    if set(body) != required:
        raise _generic_bad_request()
    try:
        tenant_id, company_id, store_id = (int(body[name]) for name in ("tenant_id", "company_id", "store_id"))
    except (TypeError, ValueError) as exc:
        raise _generic_bad_request() from exc
    found = db.query(Store.id).filter(
        Store.id == store_id,
        Store.tenant_id == tenant_id,
        Store.company_id == company_id,
        Store.platform == str(body["platform"]),
        Store.active.is_(True),
    ).one_or_none()
    if not found:
        raise HTTPException(status_code=404, detail="店铺会话作用域不存在")


def _require_owner_store(store_id: int, request: Request, db: Session) -> tuple[User, Store]:
    user = require_permission_user(request, db, "stores.manage")
    if normalize_role(user.role) not in {"owner", "老板"}:
        raise HTTPException(status_code=403, detail="仅Owner可管理云端登录会话")
    store = require_authorized_store(db, user, store_id=store_id, write=True)
    if not store.active or store.tenant_id != user.tenant_id or store.company_id != user.company_id:
        raise HTTPException(status_code=403, detail="店铺作用域不匹配")
    return user, store


RUNTIME_BASE = "http://jd-browser-runtime:8787/internal/jd-browser"


def _runtime_session_id(store: Store) -> str:
    return f"{store.tenant_id}:{store.company_id}:{store.id}:{store.platform}"


def _runtime_call(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    token = get_settings().JD_BROWSER_CONTROL_TOKEN
    if not isinstance(token, str) or len(token.encode("utf-8")) < 32:
        raise HTTPException(status_code=503, detail="云端登录运行时控制凭据未配置")
    body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{RUNTIME_BASE}{path}",
        data=body,
        headers={"content-type": "application/json", "x-internal-token": token},
        method=method,
    )
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read(512 * 1024)
        result = json.loads(raw)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        raise HTTPException(status_code=503, detail="云端登录运行时不可用") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="云端登录运行时响应无效")
    return result


def _audit_owner_action(db: Session, user: User, store: Store, action: str) -> None:
    db.add(EmployeeLog(user_id=user.id, store_id=store.id, action=action, detail="owner_login_session"))
    db.commit()


@router.post("/stores/{store_id}/login-session")
async def create_owner_login_session(store_id: int, request: Request, db: Session = Depends(get_db)):
    user, store = _require_owner_store(store_id, request, db)
    body = await _json_body(request)
    if body:
        raise _generic_bad_request()
    sid = _runtime_session_id(store)
    result = _runtime_call("POST", "/sessions", {"tenant_id": str(store.tenant_id), "company_id": str(store.company_id), "store_id": str(store.id), "platform": str(store.platform)})
    if result.get("session_id") != sid or not isinstance(result.get("expires_in"), int):
        raise HTTPException(status_code=503, detail="云端登录运行时响应无效")
    _audit_owner_action(db, user, store, "owner_login_session_create")
    return {"session_id": sid, "store_id": store.id, "status": "LOGIN_REQUIRED", "expires_in": result["expires_in"]}


@router.get("/stores/{store_id}/login-session")
async def owner_login_session_status(store_id: int, request: Request, db: Session = Depends(get_db)):
    user, store = _require_owner_store(store_id, request, db)
    sid = _runtime_session_id(store)
    result = _runtime_call("GET", f"/sessions/{sid}")
    status = result.get("status")
    if not isinstance(status, str):
        raise HTTPException(status_code=503, detail="云端登录运行时响应无效")
    _audit_owner_action(db, user, store, "owner_login_session_status")
    return {"store_id": store.id, "status": status}


@router.delete("/stores/{store_id}/login-session")
async def delete_owner_login_session(store_id: int, request: Request, db: Session = Depends(get_db)):
    user, store = _require_owner_store(store_id, request, db)
    sid = _runtime_session_id(store)
    result = _runtime_call("DELETE", f"/sessions/{sid}")
    if result.get("ok") is not True:
        raise HTTPException(status_code=503, detail="云端登录会话销毁失败")
    _audit_owner_action(db, user, store, "owner_login_session_revoke")
    return {"ok": True, "store_id": store.id, "status": "REVOKED"}


@router.post("/stores/{store_id}/login-ticket")
async def owner_login_ticket(store_id: int, request: Request, db: Session = Depends(get_db)):
    user, store = _require_owner_store(store_id, request, db)
    body = await _json_body(request)
    if body:
        raise _generic_bad_request()
    sid = _runtime_session_id(store)
    result = _runtime_call("POST", "/tickets", {"session_id": sid})
    if not isinstance(result.get("ticket"), str) or not isinstance(result.get("expires_in"), int):
        raise HTTPException(status_code=503, detail="云端登录运行时响应无效")
    _audit_owner_action(db, user, store, "owner_login_ticket")
    return {"ticket": result["ticket"], "expires_in": result["expires_in"]}


async def _json_body(request: Request) -> dict[str, Any]:
    length = request.headers.get("content-length", "")
    if length:
        try:
            if int(length) > MAX_JSON_BYTES:
                raise HTTPException(status_code=413, detail="请求体过大")
        except ValueError as exc:
            raise _generic_bad_request() from exc
    try:
        data = await request.json()
    except Exception as exc:
        raise _generic_bad_request() from exc
    if not isinstance(data, dict):
        raise _generic_bad_request()
    return data


def _exact_keys(data: dict[str, Any], required: frozenset[str], optional: frozenset[str] = frozenset()) -> None:
    if set(data) != required | (set(data) & optional):
        raise _generic_bad_request()
    if not required.issubset(data):
        raise _generic_bad_request()


def _pairing_hash(code: str) -> str:
    return hmac.new(
        get_settings().JWT_SECRET.encode("utf-8"),
        f"r291-pairing\0{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _store_uuid(store: Store) -> str:
    digest = hmac.new(
        get_settings().JWT_SECRET.encode("utf-8"),
        f"r291-store\0{store.tenant_id}\0{store.company_id}\0{store.id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return str(uuid.UUID(hex=digest[:32], version=5))


def _decode_base64url(value: Any, *, maximum: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise _generic_bad_request()
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise _generic_bad_request() from exc


def _parse_public_key(raw: Any) -> tuple[str, int]:
    if not isinstance(raw, dict) or set(raw) != {"kty", "n", "e"} or raw.get("kty") != "RSA":
        raise _generic_bad_request()
    modulus_bytes = _decode_base64url(raw.get("n"), maximum=400)
    exponent_bytes = _decode_base64url(raw.get("e"), maximum=8)
    modulus = int.from_bytes(modulus_bytes, "big")
    exponent = int.from_bytes(exponent_bytes, "big")
    if modulus.bit_length() != 2048 or modulus % 2 != 1 or exponent != 65537:
        raise _generic_bad_request()
    return format(modulus, "0512x"), exponent


def _verify_rsa_signature(device: JdWorkbenchDevice, canonical: bytes, signature: bytes) -> bool:
    modulus = int(device.public_key_n, 16)
    size = (modulus.bit_length() + 7) // 8
    if size != 256 or len(signature) != size:
        return False
    encoded_int = pow(int.from_bytes(signature, "big"), device.public_key_e, modulus)
    encoded = encoded_int.to_bytes(size, "big")
    digest_info = RSA_SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(canonical).digest()
    padding_length = size - len(digest_info) - 3
    if padding_length < 8:
        return False
    expected = b"\x00\x01" + b"\xff" * padding_length + b"\x00" + digest_info
    return hmac.compare_digest(encoded, expected)


async def _device_context(request: Request, db: Session) -> tuple[JdWorkbenchDevice, User]:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Device "):
        raise HTTPException(status_code=401, detail="设备认证失败")
    token = authorization.removeprefix("Device ").strip()
    if not (40 <= len(token) <= 256):
        raise HTTPException(status_code=401, detail="设备认证失败")
    device = db.query(JdWorkbenchDevice).filter(JdWorkbenchDevice.token_hash == _token_hash(token)).one_or_none()
    now = _now()
    if (
        not device
        or device.revoked_at is not None
        or _aware(device.expires_at) <= now
        or device.status == "REVOKED"
    ):
        raise HTTPException(status_code=401, detail="设备认证失败")
    user = db.get(User, device.user_id)
    if (
        not user
        or not user.active
        or user.tenant_id != device.tenant_id
        or user.company_id != device.company_id
        or INGEST_PERMISSION not in get_role_permissions(db, normalize_role(user.role))
    ):
        raise HTTPException(status_code=401, detail="设备认证失败")

    timestamp_raw = request.headers.get("X-R291-Timestamp", "")
    nonce = request.headers.get("X-R291-Nonce", "")
    signature_raw = request.headers.get("X-R291-Signature", "")
    if not (10 <= len(timestamp_raw) <= 11) or not timestamp_raw.isdigit() or not NONCE_RE.fullmatch(nonce):
        raise HTTPException(status_code=401, detail="设备认证失败")
    timestamp = int(timestamp_raw)
    if abs(int(_now().timestamp()) - timestamp) > SIGNATURE_WINDOW_SECONDS:
        raise HTTPException(status_code=401, detail="设备认证失败")
    try:
        signature = _decode_base64url(signature_raw, maximum=400)
    except HTTPException as exc:
        raise HTTPException(status_code=401, detail="设备认证失败") from exc
    body = await request.body()
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    canonical = "\n".join(
        (
            "R291",
            timestamp_raw,
            nonce,
            request.method.upper(),
            path,
            hashlib.sha256(body).hexdigest(),
        )
    ).encode("utf-8")
    if not _verify_rsa_signature(device, canonical, signature):
        raise HTTPException(status_code=401, detail="设备认证失败")
    nonce_key = f"r291:device-nonce:{device.device_id}:{hashlib.sha256(nonce.encode()).hexdigest()}"
    if not database.get_redis().set(nonce_key, "1", nx=True, ex=SIGNATURE_NONCE_TTL_SECONDS):
        raise HTTPException(status_code=401, detail="设备认证失败")
    return device, user


def _parse_aware_datetime(raw: Any) -> datetime:
    if not isinstance(raw, str) or len(raw) > 40:
        raise _generic_bad_request()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _generic_bad_request() from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _generic_bad_request()
    return parsed.astimezone(timezone.utc)


def _decimal(raw: Any, *, places: int, maximum: Decimal) -> str:
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise _generic_bad_request()
    if isinstance(raw, float) and not math.isfinite(raw):
        raise _generic_bad_request()
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise _generic_bad_request() from exc
    if not value.is_finite() or value < 0 or value > maximum:
        raise _generic_bad_request()
    quantum = Decimal(1).scaleb(-places)
    return format(value.quantize(quantum), f".{places}f")


def _integer(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0 or raw > 1_000_000_000:
        raise _generic_bad_request()
    return raw


def _short_text(raw: Any, limit: int) -> str:
    if not isinstance(raw, str):
        raise _generic_bad_request()
    value = unicodedata.normalize("NFKC", raw).strip()
    if not value or len(value) > limit or any(ord(char) < 32 for char in value):
        raise _generic_bad_request()
    return value


def _normalize_record(dataset_type: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _generic_bad_request()
    required, optional = DATASET_FIELDS[dataset_type]
    _exact_keys(raw, required, optional)
    if dataset_type == "operating_metrics" and not (set(raw) - {"source_record_key"}):
        raise _generic_bad_request()
    source_record_key = raw.get("source_record_key")
    if not isinstance(source_record_key, str) or not HEX_KEY_RE.fullmatch(source_record_key):
        raise _generic_bad_request()

    normalized: dict[str, Any] = {"source_record_key": source_record_key}
    for key in sorted(set(raw) - {"source_record_key"}):
        value = raw[key]
        if key in MONEY_FIELDS:
            normalized[key] = _decimal(value, places=2, maximum=Decimal("999999999999999.99"))
        elif key in RATIO_FIELDS:
            normalized[key] = _decimal(value, places=4, maximum=Decimal("999999.9999"))
        elif key in INTEGER_FIELDS:
            normalized[key] = _integer(value)
        elif key == "sku_key":
            if not isinstance(value, str) or not HEX_KEY_RE.fullmatch(value):
                raise _generic_bad_request()
            normalized[key] = value
        elif key == "channel":
            if value not in PROMOTION_CHANNELS:
                raise _generic_bad_request()
            normalized[key] = value
        elif key == "low_stock":
            if not isinstance(value, bool):
                raise _generic_bad_request()
            normalized[key] = value
        elif key in TEXT_LIMITS:
            normalized[key] = _short_text(value, TEXT_LIMITS[key])
        elif key in DATETIME_FIELDS:
            normalized[key] = _parse_aware_datetime(value).isoformat()
        else:
            raise _generic_bad_request()
    return normalized


def _normalize_sync(data: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(data, SYNC_TOP_LEVEL)
    dataset_type = data.get("dataset_type")
    if dataset_type not in DATASET_FIELDS:
        raise _generic_bad_request()
    if not isinstance(data.get("store_id"), int) or isinstance(data.get("store_id"), bool):
        raise _generic_bad_request()
    if not isinstance(data.get("subject_id"), int) or isinstance(data.get("subject_id"), bool):
        raise _generic_bad_request()
    source_period = data.get("source_period")
    if not isinstance(source_period, str) or not SOURCE_PERIOD_RE.fullmatch(source_period):
        raise _generic_bad_request()
    idempotency_key = data.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not IDEMPOTENCY_RE.fullmatch(idempotency_key):
        raise _generic_bad_request()
    client_version = data.get("client_version")
    if not isinstance(client_version, str) or not CLIENT_VERSION_RE.fullmatch(client_version):
        raise _generic_bad_request()
    records = data.get("records")
    minimum_records = 0 if dataset_type in {"fulfillment_orders", "aftersale_orders", "abnormal_orders"} else 1
    if not isinstance(records, list) or not (minimum_records <= len(records) <= MAX_RECORDS):
        raise _generic_bad_request()
    normalized_records = [_normalize_record(dataset_type, record) for record in records]
    keys = [record["source_record_key"] for record in normalized_records]
    if len(keys) != len(set(keys)):
        raise _generic_bad_request()
    return {
        "store_id": data["store_id"],
        "subject_id": data["subject_id"],
        "dataset_type": dataset_type,
        "source_period": source_period,
        "collected_at": _parse_aware_datetime(data.get("collected_at")),
        "idempotency_key": idempotency_key,
        "client_version": client_version,
        "records": sorted(normalized_records, key=lambda item: item["source_record_key"]),
    }


def _payload_digest(normalized: dict[str, Any]) -> str:
    canonical = {
        **normalized,
        "collected_at": normalized["collected_at"].isoformat(),
    }
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _status_row(db: Session, device_id: str, store_id: int) -> JdWorkbenchStoreStatus:
    row = db.query(JdWorkbenchStoreStatus).filter(
        JdWorkbenchStoreStatus.device_id == device_id,
        JdWorkbenchStoreStatus.store_id == store_id,
    ).one_or_none()
    if row is None:
        row = JdWorkbenchStoreStatus(device_id=device_id, store_id=store_id, status="OFFLINE")
        db.add(row)
    return row


def _sync_policy(db: Session, user: User, store: Store) -> JdWorkbenchSyncPolicy:
    row = db.query(JdWorkbenchSyncPolicy).filter(
        JdWorkbenchSyncPolicy.tenant_id == user.tenant_id,
        JdWorkbenchSyncPolicy.store_id == store.id,
    ).one_or_none()
    if row is None:
        row = JdWorkbenchSyncPolicy(
            tenant_id=user.tenant_id,
            company_id=store.company_id,
            store_id=store.id,
            enabled=True,
            interval_seconds=DEFAULT_SYNC_INTERVAL_SECONDS,
            updated_by_user_id=user.id,
        )
        db.add(row)
    return row


def _runtime_payload(status: JdWorkbenchStoreStatus | None) -> dict[str, Any]:
    return {
        "status": status.status if status else "OFFLINE",
        "reason_code": status.reason_code if status else None,
        "last_attempt_at": status.last_attempt_at.isoformat() if status and status.last_attempt_at else None,
        "last_sync_at": status.last_sync_at.isoformat() if status and status.last_sync_at else None,
        "next_sync_at": status.next_sync_at.isoformat() if status and status.next_sync_at else None,
        "retry_count": status.retry_count if status else 0,
        "last_error_at": status.last_error_at.isoformat() if status and status.last_error_at else None,
    }


@router.post("/pairing-codes")
def create_pairing_code(request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, INGEST_PERMISSION)
    now = _now()
    for _ in range(10):
        code = f"{secrets.randbelow(100_000_000):08d}"
        row = JdWorkbenchPairingCode(
            pairing_id=str(uuid.uuid4()),
            code_hash=_pairing_hash(code),
            tenant_id=user.tenant_id,
            company_id=user.company_id,
            user_id=user.id,
            expires_at=now + PAIRING_TTL,
        )
        db.add(row)
        try:
            db.commit()
            return {"code": code, "expires_at": row.expires_at.isoformat()}
        except IntegrityError:
            db.rollback()
    raise HTTPException(status_code=503, detail="暂时无法生成配对码")


@router.post("/pair")
async def pair_device(request: Request, db: Session = Depends(get_db)):
    data = await _json_body(request)
    _exact_keys(data, frozenset({"code", "device_name", "client_version", "public_key"}))
    code = data.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"\d{8}", code):
        raise _generic_bad_request()
    device_name = _short_text(data.get("device_name"), 120)
    client_version = data.get("client_version")
    if not isinstance(client_version, str) or not CLIENT_VERSION_RE.fullmatch(client_version):
        raise _generic_bad_request()
    public_key_n, public_key_e = _parse_public_key(data.get("public_key"))
    now = _now()
    pairing = db.query(JdWorkbenchPairingCode).filter(
        JdWorkbenchPairingCode.code_hash == _pairing_hash(code)
    ).one_or_none()
    if not pairing:
        raise HTTPException(status_code=400, detail="配对码无效或已过期")
    consumed = db.query(JdWorkbenchPairingCode).filter(
        JdWorkbenchPairingCode.pairing_id == pairing.pairing_id,
        JdWorkbenchPairingCode.used_at.is_(None),
        JdWorkbenchPairingCode.expires_at > now,
    ).update({JdWorkbenchPairingCode.used_at: now}, synchronize_session=False)
    if consumed != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="配对码无效或已过期")
    user = db.get(User, pairing.user_id)
    if (
        not user
        or not user.active
        or user.tenant_id != pairing.tenant_id
        or user.company_id != pairing.company_id
        or INGEST_PERMISSION not in get_role_permissions(db, normalize_role(user.role))
    ):
        db.rollback()
        raise HTTPException(status_code=400, detail="配对码无效或已过期")
    token = secrets.token_urlsafe(48)
    device = JdWorkbenchDevice(
        device_id=str(uuid.uuid4()),
        token_hash=_token_hash(token),
        public_key_n=public_key_n,
        public_key_e=public_key_e,
        tenant_id=pairing.tenant_id,
        company_id=pairing.company_id,
        user_id=pairing.user_id,
        device_name=device_name,
        client_version=client_version,
        status="PAIRED",
        last_seen_at=now,
        expires_at=now + DEVICE_TTL,
    )
    db.add(device)
    db.commit()
    return {
        "device_id": device.device_id,
        "device_token": token,
        "expires_at": device.expires_at.isoformat(),
    }


@router.get("/stores")
async def list_device_stores(request: Request, db: Session = Depends(get_db)):
    device, user = await _device_context(request, db)
    stores = authorized_stores(db, user, write=True).filter(Store.platform == "jd").order_by(Store.id.asc()).all()
    statuses = {
        row.store_id: row
        for row in db.query(JdWorkbenchStoreStatus).filter(
            JdWorkbenchStoreStatus.device_id == device.device_id,
            JdWorkbenchStoreStatus.store_id.in_([store.id for store in stores]),
        ).all()
    }
    policies = {store.id: _sync_policy(db, user, store) for store in stores}
    db.commit()
    result = []
    for store in stores:
        store_uuid = _store_uuid(store)
        status = statuses.get(store.id)
        policy = policies[store.id]
        result.append(
            {
                "store_id": store.id,
                "subject_id": store.company_id,
                "store_uuid": store_uuid,
                "partition": f"persist:jd-{store_uuid}",
                "store_code": store.store_code,
                "store_name": store.store_name,
                **_runtime_payload(status),
                "sync_policy": {
                    "enabled": policy.enabled,
                    "interval_seconds": policy.interval_seconds,
                    "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
                },
            }
        )
    return result


@router.post("/heartbeat")
async def heartbeat(request: Request, db: Session = Depends(get_db)):
    device, user = await _device_context(request, db)
    data = await _json_body(request)
    _exact_keys(
        data,
        frozenset({"client_version", "status"}),
        frozenset({"store_id", "reason_code", "last_attempt_at", "next_sync_at", "retry_count"}),
    )
    client_version = data.get("client_version")
    status = data.get("status")
    if not isinstance(client_version, str) or not CLIENT_VERSION_RE.fullmatch(client_version):
        raise _generic_bad_request()
    if status not in DEVICE_STATUSES:
        raise _generic_bad_request()
    store_id = data.get("store_id")
    reason_code = data.get("reason_code")
    if status == "HUMAN_ACTION_REQUIRED":
        if not isinstance(store_id, int) or isinstance(store_id, bool) or reason_code not in HUMAN_REASON_CODES:
            raise _generic_bad_request()
    elif status == "ERROR":
        if not isinstance(store_id, int) or isinstance(store_id, bool) or reason_code not in SYNC_ERROR_CODES:
            raise _generic_bad_request()
    elif reason_code is not None:
        raise _generic_bad_request()
    retry_count = data.get("retry_count", 0)
    if isinstance(retry_count, bool) or not isinstance(retry_count, int) or not (0 <= retry_count <= MAX_SYNC_RETRIES):
        raise _generic_bad_request()
    last_attempt_at = _parse_aware_datetime(data["last_attempt_at"]) if "last_attempt_at" in data else None
    next_sync_at = _parse_aware_datetime(data["next_sync_at"]) if "next_sync_at" in data else None
    now = _now()
    if store_id is not None:
        if not isinstance(store_id, int) or isinstance(store_id, bool):
            raise _generic_bad_request()
        store = require_authorized_store(db, user, store_id=store_id, write=True)
        row = _status_row(db, device.device_id, store.id)
        row.status = status
        row.reason_code = reason_code
        if last_attempt_at is not None:
            row.last_attempt_at = last_attempt_at
        row.next_sync_at = next_sync_at
        row.retry_count = retry_count
        if status in {"ERROR", "HUMAN_ACTION_REQUIRED"}:
            row.last_error_at = now
        elif status in {"IDLE", "ONLINE", "SYNCING"}:
            row.last_error_at = None
        row.updated_at = now
    device.client_version = client_version
    device.status = status
    device.last_seen_at = now
    db.commit()
    return {"ok": True, "status": status, "server_time": now.isoformat()}


@router.post("/sync")
async def sync_data(request: Request, db: Session = Depends(get_db)):
    device, user = await _device_context(request, db)
    normalized = _normalize_sync(await _json_body(request))
    store = require_authorized_store(db, user, store_id=normalized["store_id"], write=True)
    if normalized["subject_id"] != store.company_id or store.company_id != device.company_id:
        raise HTTPException(status_code=403, detail="没有店铺访问权限")
    digest = _payload_digest(normalized)
    existing_batch = db.query(JdWorkbenchSyncBatch).filter(
        JdWorkbenchSyncBatch.tenant_id == device.tenant_id,
        JdWorkbenchSyncBatch.store_id == store.id,
        JdWorkbenchSyncBatch.dataset_type == normalized["dataset_type"],
        JdWorkbenchSyncBatch.idempotency_key == normalized["idempotency_key"],
    ).one_or_none()
    if existing_batch:
        if not hmac.compare_digest(existing_batch.payload_digest, digest):
            raise HTTPException(status_code=409, detail="幂等键对应的数据内容不一致")
        return {"ok": True, "duplicate": True, "accepted": 0, "batch_id": existing_batch.batch_id}

    batch = JdWorkbenchSyncBatch(
        batch_id=str(uuid.uuid4()),
        device_id=device.device_id,
        tenant_id=device.tenant_id,
        company_id=device.company_id,
        store_id=store.id,
        subject_id=store.company_id,
        dataset_type=normalized["dataset_type"],
        source_period=normalized["source_period"],
        collected_at=normalized["collected_at"],
        idempotency_key=normalized["idempotency_key"],
        client_version=normalized["client_version"],
        payload_digest=digest,
        record_count=len(normalized["records"]),
        status="ACCEPTED",
    )
    db.add(batch)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raced = db.query(JdWorkbenchSyncBatch).filter(
            JdWorkbenchSyncBatch.tenant_id == device.tenant_id,
            JdWorkbenchSyncBatch.store_id == store.id,
            JdWorkbenchSyncBatch.dataset_type == normalized["dataset_type"],
            JdWorkbenchSyncBatch.idempotency_key == normalized["idempotency_key"],
        ).one_or_none()
        if raced and hmac.compare_digest(raced.payload_digest, digest):
            return {"ok": True, "duplicate": True, "accepted": 0, "batch_id": raced.batch_id}
        raise HTTPException(status_code=409, detail="幂等键对应的数据内容不一致")

    accepted = 0
    for record in normalized["records"]:
        values = {key: value for key, value in record.items() if key != "source_record_key"}
        values_json = json.dumps(values, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        prior = db.query(JdWorkbenchRecord).filter(
            JdWorkbenchRecord.tenant_id == device.tenant_id,
            JdWorkbenchRecord.store_id == store.id,
            JdWorkbenchRecord.dataset_type == normalized["dataset_type"],
            JdWorkbenchRecord.source_period == normalized["source_period"],
            JdWorkbenchRecord.source_record_key == record["source_record_key"],
        ).one_or_none()
        if prior:
            if not hmac.compare_digest(prior.values_json, values_json):
                db.rollback()
                raise HTTPException(status_code=409, detail="来源记录键对应的数据内容不一致")
            continue
        db.add(
            JdWorkbenchRecord(
                batch_id=batch.batch_id,
                tenant_id=device.tenant_id,
                company_id=device.company_id,
                store_id=store.id,
                subject_id=store.company_id,
                dataset_type=normalized["dataset_type"],
                source_period=normalized["source_period"],
                source_record_key=record["source_record_key"],
                values_json=values_json,
            )
        )
        accepted += 1
    now = _now()
    status = _status_row(db, device.device_id, store.id)
    policy = _sync_policy(db, user, store)
    status.status = "IDLE"
    status.reason_code = None
    status.last_attempt_at = normalized["collected_at"]
    status.last_sync_at = now
    status.next_sync_at = now + timedelta(seconds=policy.interval_seconds) if policy.enabled else None
    status.retry_count = 0
    status.last_error_at = None
    status.updated_at = now
    device.client_version = normalized["client_version"]
    device.status = "ONLINE"
    device.last_seen_at = now
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="来源记录已由另一同步任务写入") from exc
    return {"ok": True, "duplicate": False, "accepted": accepted, "batch_id": batch.batch_id}


@router.patch("/sync-policies/{store_id}")
async def update_sync_policy(store_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "stores.manage")
    store = require_authorized_store(db, user, store_id=store_id, write=True)
    data = await _json_body(request)
    _exact_keys(data, frozenset({"enabled"}), frozenset({"interval_seconds"}))
    enabled = data.get("enabled")
    interval_seconds = data.get("interval_seconds", DEFAULT_SYNC_INTERVAL_SECONDS)
    if not isinstance(enabled, bool) or interval_seconds not in ALLOWED_SYNC_INTERVAL_SECONDS:
        raise _generic_bad_request()
    policy = _sync_policy(db, user, store)
    policy.enabled = enabled
    policy.interval_seconds = interval_seconds
    policy.updated_by_user_id = user.id
    now = _now()
    statuses = db.query(JdWorkbenchStoreStatus).join(
        JdWorkbenchDevice, JdWorkbenchDevice.device_id == JdWorkbenchStoreStatus.device_id,
    ).filter(
        JdWorkbenchStoreStatus.store_id == store.id,
        JdWorkbenchDevice.tenant_id == user.tenant_id,
        JdWorkbenchDevice.company_id == user.company_id,
        JdWorkbenchDevice.revoked_at.is_(None),
    ).all()
    for status_row in statuses:
        status_row.status = "IDLE" if enabled else "PAUSED"
        status_row.reason_code = None
        status_row.next_sync_at = now if enabled else None
        status_row.retry_count = 0
        status_row.updated_at = now
    db.commit()
    return {
        "ok": True, "store_id": store.id, "enabled": policy.enabled,
        "interval_seconds": policy.interval_seconds,
        "next_sync_at": now.isoformat() if enabled else None,
    }


def _dashboard_period_bounds(
    period: DashboardPeriod,
    anchor_date: date | None,
) -> tuple[date | None, date | None]:
    if period == "latest":
        return None, None
    anchor = anchor_date or _now().astimezone(CHINA_TIMEZONE).date()
    if period == "today":
        return anchor, anchor
    if period == "yesterday":
        previous = anchor - timedelta(days=1)
        return previous, previous
    return anchor - timedelta(days=6), anchor


def _china_date(value: datetime) -> date:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(CHINA_TIMEZONE).date()


def _mean(values: list[Decimal]) -> Decimal | None:
    return sum(values, Decimal("0")) / len(values) if values else None


def _summarize_operating_records(
    records: list[dict[str, Any]],
) -> dict[str, str | int | None]:
    money_sums = {field: Decimal("0") for field in OPERATING_MONEY_SUM_FIELDS}
    integer_sums = {field: 0 for field in OPERATING_INTEGER_SUM_FIELDS}
    latest_money: dict[str, Decimal] = {}
    latest_integer: dict[str, int] = {}
    raw_rates: dict[str, list[Decimal]] = {field: [] for field in OPERATING_DERIVED_FIELDS}
    present: set[str] = set()

    for record in records:
        for field in OPERATING_MONEY_SUM_FIELDS:
            if field in record:
                money_sums[field] += Decimal(str(record[field]))
                present.add(field)
        for field in OPERATING_INTEGER_SUM_FIELDS:
            if field in record:
                integer_sums[field] += int(record[field])
                present.add(field)
        for field in OPERATING_LATEST_MONEY_FIELDS:
            if field in record:
                latest_money[field] = Decimal(str(record[field]))
                present.add(field)
        for field in OPERATING_LATEST_INTEGER_FIELDS:
            if field in record:
                latest_integer[field] = int(record[field])
                present.add(field)
        for field in OPERATING_DERIVED_FIELDS:
            if field in record:
                raw_rates[field].append(Decimal(str(record[field])))

    result: dict[str, str | int | None] = {}
    for field, value in money_sums.items():
        result[field] = format(value, ".2f") if field in present else None
    for field, value in integer_sums.items():
        result[field] = value if field in present else None
    for field in OPERATING_LATEST_MONEY_FIELDS:
        result[field] = format(latest_money[field], ".2f") if field in latest_money else None
    for field in OPERATING_LATEST_INTEGER_FIELDS:
        result[field] = latest_integer.get(field)

    visitors = integer_sums["visitors"]
    orders = integer_sums["sales_orders"]
    impressions = integer_sums["ad_impressions"]
    clicks = integer_sums["ad_clicks"]
    spend = money_sums["ad_spend"]
    derived: dict[str, Decimal | None] = {
        "conversion_rate": (
            Decimal(orders) * Decimal("100") / Decimal(visitors)
            if "sales_orders" in present and "visitors" in present and visitors > 0
            else _mean(raw_rates["conversion_rate"])
        ),
        "ad_ctr": (
            Decimal(clicks) * Decimal("100") / Decimal(impressions)
            if "ad_clicks" in present and "ad_impressions" in present and impressions > 0
            else _mean(raw_rates["ad_ctr"])
        ),
        "ad_cpm": (
            spend * Decimal("1000") / Decimal(impressions)
            if "ad_spend" in present and "ad_impressions" in present and impressions > 0
            else _mean(raw_rates["ad_cpm"])
        ),
        "ad_cpc": (
            spend / Decimal(clicks)
            if "ad_spend" in present and "ad_clicks" in present and clicks > 0
            else _mean(raw_rates["ad_cpc"])
        ),
    }
    for field, value in derived.items():
        result[field] = (
            format(value, ".2f" if field in {"ad_cpm", "ad_cpc"} else ".4f")
            if value is not None
            else None
        )
    return result


@router.get("/dashboard")
def cloud_dashboard(
    request: Request,
    store_id: int | None = None,
    period: DashboardPeriod = "latest",
    anchor_date: date | None = None,
    db: Session = Depends(get_db),
):
    user = require_permission_user(request, db, "menu.jd_data")
    period_start, period_end = _dashboard_period_bounds(period, anchor_date)
    store_query = authorized_stores(db, user).filter(Store.platform == "jd")
    if store_id is not None:
        store_query = store_query.filter(Store.id == store_id)
    stores = store_query.order_by(Store.id.asc()).all()
    items = []
    for store in stores:
        policy = _sync_policy(db, user, store)
        company = db.get(Company, store.company_id)
        latest_status = (
            db.query(JdWorkbenchStoreStatus)
            .join(JdWorkbenchDevice, JdWorkbenchDevice.device_id == JdWorkbenchStoreStatus.device_id)
            .filter(
                JdWorkbenchStoreStatus.store_id == store.id,
                JdWorkbenchDevice.tenant_id == user.tenant_id,
                JdWorkbenchDevice.company_id == user.company_id,
                JdWorkbenchDevice.revoked_at.is_(None),
            )
            .order_by(JdWorkbenchStoreStatus.updated_at.desc())
            .first()
        )
        batch_query = db.query(JdWorkbenchSyncBatch).filter(
            JdWorkbenchSyncBatch.tenant_id == user.tenant_id,
            JdWorkbenchSyncBatch.company_id == user.company_id,
            JdWorkbenchSyncBatch.store_id == store.id,
        )
        if period_start is not None and period_end is not None:
            start_at = datetime.combine(
                period_start, datetime.min.time(), tzinfo=CHINA_TIMEZONE
            ).astimezone(timezone.utc)
            end_at = datetime.combine(
                period_end + timedelta(days=1), datetime.min.time(), tzinfo=CHINA_TIMEZONE
            ).astimezone(timezone.utc)
            batch_query = batch_query.filter(
                JdWorkbenchSyncBatch.collected_at >= start_at,
                JdWorkbenchSyncBatch.collected_at < end_at,
            )
        batches = batch_query.order_by(
            JdWorkbenchSyncBatch.source_period.desc(),
            JdWorkbenchSyncBatch.collected_at.desc(),
            JdWorkbenchSyncBatch.created_at.desc(),
        ).all()
        latest_batches: dict[str | tuple[str, str], JdWorkbenchSyncBatch] = {}
        for batch in batches:
            key: str | tuple[str, str] = (
                batch.dataset_type
                if period == "latest"
                else (batch.dataset_type, _china_date(batch.collected_at).isoformat())
            )
            latest_batches.setdefault(key, batch)
        selected_batches = sorted(
            latest_batches.values(),
            key=lambda batch: (batch.dataset_type, batch.source_period, batch.collected_at),
        )
        datasets: dict[str, dict[str, Any]] = {}
        for batch in selected_batches:
            display_period = _china_date(batch.collected_at).isoformat()
            records = db.query(JdWorkbenchRecord).filter(
                JdWorkbenchRecord.tenant_id == user.tenant_id,
                JdWorkbenchRecord.company_id == user.company_id,
                JdWorkbenchRecord.store_id == store.id,
                JdWorkbenchRecord.dataset_type == batch.dataset_type,
                JdWorkbenchRecord.batch_id == batch.batch_id,
            ).order_by(JdWorkbenchRecord.id.asc()).limit(100).all()
            dataset = datasets.setdefault(
                batch.dataset_type,
                {
                    "source": "jd_workbench_readonly",
                    "source_period": display_period,
                    "source_periods": [],
                    "collected_at": batch.collected_at.isoformat(),
                    "client_version": batch.client_version,
                    "record_count": 0,
                    "records": [],
                },
            )
            dataset["source_periods"].append(display_period)
            dataset["source_period"] = (
                display_period
                if len(dataset["source_periods"]) == 1
                else f"{dataset['source_periods'][0]}/{dataset['source_periods'][-1]}"
            )
            dataset["collected_at"] = batch.collected_at.isoformat()
            dataset["client_version"] = batch.client_version
            normalized_records = [json.loads(record.values_json) for record in records]
            dataset["records"].extend(normalized_records)
            dataset["record_count"] += len(normalized_records)
        operating_records = datasets.get("operating_metrics", {}).get("records", [])
        items.append(
            {
                "store_id": store.id,
                "subject_id": store.company_id,
                "subject_name": company.company_name if company else None,
                "store_code": store.store_code,
                "store_name": store.store_name,
                "sync_status": latest_status.status if latest_status else ("IDLE" if policy.enabled else "PAUSED"),
                **{key: value for key, value in _runtime_payload(latest_status).items() if key != "status"},
                "sync_enabled": policy.enabled,
                "sync_interval_seconds": policy.interval_seconds,
                "data_state": "READY" if datasets else "NO_DATA",
                "empty_message": None if datasets else "暂无数据",
                "datasets": datasets,
                "summary": _summarize_operating_records(operating_records),
            }
        )
    summary_values: dict[str, Decimal | int] = {
        "sales_amount": Decimal("0"),
        "orders_count": 0,
        "refund_amount": Decimal("0"),
        "refund_order_count": 0,
        "ad_spend": Decimal("0"),
        "inventory_sku_count": 0,
        "low_stock_count": 0,
        "pending_shipment_count": 0,
        "aftersale_count": 0,
        "abnormal_order_count": 0,
    }
    present = {key: False for key in summary_values}
    attributed_sales = Decimal("0")
    attributed_present = False
    for item in items:
        datasets = item["datasets"]
        operating_records = datasets.get("operating_metrics", {}).get("records", [])
        sales_records = datasets.get("sales_daily", {}).get("records", [])
        for record in sales_records:
            summary_values["sales_amount"] += Decimal(record["sales_amount"])
            present["sales_amount"] = True
        if not sales_records:
            for record in operating_records:
                if "sales_amount" in record:
                    summary_values["sales_amount"] += Decimal(record["sales_amount"])
                    present["sales_amount"] = True
        order_records = datasets.get("orders", {}).get("records")
        if order_records is None:
            order_records = sales_records
            order_field = "orders_count"
        else:
            order_field = "order_count"
        for record in order_records:
            summary_values["orders_count"] += int(record[order_field])
            present["orders_count"] = True
        if not order_records:
            for record in operating_records:
                if "sales_orders" in record:
                    summary_values["orders_count"] += int(record["sales_orders"])
                    present["orders_count"] = True
        for record in datasets.get("refunds", {}).get("records", []):
            summary_values["refund_amount"] += Decimal(record["refund_amount"])
            summary_values["refund_order_count"] += int(record["refund_order_count"])
            present["refund_amount"] = True
            present["refund_order_count"] = True
        for record in datasets.get("inventory", {}).get("records", []):
            summary_values["inventory_sku_count"] += 1
            summary_values["low_stock_count"] += int(bool(record.get("low_stock")))
            present["inventory_sku_count"] = True
            present["low_stock_count"] = True
        promotion_records = datasets.get("promotion_costs", {}).get("records", [])
        for record in promotion_records:
            summary_values["ad_spend"] += Decimal(record["ad_spend"])
            present["ad_spend"] = True
            if "attributed_sales" in record:
                attributed_sales += Decimal(record["attributed_sales"])
                attributed_present = True
        if not promotion_records:
            for record in operating_records:
                if "ad_spend" in record:
                    summary_values["ad_spend"] += Decimal(record["ad_spend"])
                    present["ad_spend"] = True
        detail_counts = {
            "fulfillment_orders": "pending_shipment_count",
            "aftersale_orders": "aftersale_count",
            "abnormal_orders": "abnormal_order_count",
        }
        for dataset_type, summary_key in detail_counts.items():
            if dataset_type in datasets:
                summary_values[summary_key] += len(datasets[dataset_type].get("records", []))
                present[summary_key] = True
    ad_spend = summary_values["ad_spend"]
    summary = {
        key: (
            format(value, ".2f") if isinstance(value, Decimal) else value
        ) if present[key] else None
        for key, value in summary_values.items()
    }
    summary["roi"] = (
        format(attributed_sales / ad_spend, ".4f")
        if attributed_present and present["ad_spend"] and ad_spend > 0
        else None
    )
    combined_operating_records = [
        record
        for item in items
        for record in item["datasets"].get("operating_metrics", {}).get("records", [])
    ]
    operating_summary = _summarize_operating_records(combined_operating_records)
    for key, value in operating_summary.items():
        if key not in {"sales_amount", "sales_orders", "ad_spend"}:
            summary[key] = value
    summary["sales_orders"] = summary["orders_count"]
    db.commit()
    failure_items = [
        item for item in items
        if item["sync_status"] in {"ERROR", "HUMAN_ACTION_REQUIRED"}
    ]
    return {
        "stores": items,
        "total": len(items),
        "source": "jd_workbench_readonly",
        "summary": summary,
        "period": period,
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
        "ready_stores": sum(item["data_state"] == "READY" for item in items),
        "human_action_required": sum(item["sync_status"] == "HUMAN_ACTION_REQUIRED" for item in items),
        "running_stores": sum(item["sync_enabled"] and item["sync_status"] not in {"ERROR", "HUMAN_ACTION_REQUIRED"} for item in items),
        "paused_stores": sum(not item["sync_enabled"] or item["sync_status"] == "PAUSED" for item in items),
        "successful_stores": sum(item["last_sync_at"] is not None and item["sync_status"] not in {"ERROR", "HUMAN_ACTION_REQUIRED"} for item in items),
        "failed_stores": len(failure_items),
        "failure_reasons": [
            {"store_id": item["store_id"], "store_name": item["store_name"], "reason_code": item["reason_code"]}
            for item in failure_items
        ],
    }


@router.get("/dashboard/details/{detail_type}")
def cloud_order_details(
    detail_type: str,
    request: Request,
    store_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    status: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    user = require_permission_user(request, db, "menu.jd_data")
    dataset_type = {
        "fulfillment": "fulfillment_orders",
        "aftersales": "aftersale_orders",
        "abnormal": "abnormal_orders",
    }.get(detail_type)
    if dataset_type is None or not (1 <= limit <= 500) or (start_date and end_date and start_date > end_date):
        raise HTTPException(status_code=400, detail="明细查询参数不正确")
    store_query = authorized_stores(db, user).filter(Store.platform == "jd")
    if store_id is not None:
        store_query = store_query.filter(Store.id == store_id)
    stores = store_query.order_by(Store.id.asc()).all()
    store_map = {store.id: store for store in stores}
    if store_id is not None and store_id not in store_map:
        raise HTTPException(status_code=404, detail="店铺不存在或无权访问")
    if not store_map:
        return {"detail_type": detail_type, "records": [], "total": 0}
    batches_query = db.query(JdWorkbenchSyncBatch).filter(
        JdWorkbenchSyncBatch.tenant_id == user.tenant_id,
        JdWorkbenchSyncBatch.company_id == user.company_id,
        JdWorkbenchSyncBatch.store_id.in_(store_map),
        JdWorkbenchSyncBatch.dataset_type == dataset_type,
    )
    if start_date:
        batches_query = batches_query.filter(JdWorkbenchSyncBatch.source_period >= start_date.isoformat())
    if end_date:
        batches_query = batches_query.filter(JdWorkbenchSyncBatch.source_period <= end_date.isoformat())
    batches = batches_query.order_by(
        JdWorkbenchSyncBatch.collected_at.desc(), JdWorkbenchSyncBatch.created_at.desc()
    ).all()
    latest_batches: dict[tuple[int, str], JdWorkbenchSyncBatch] = {}
    for batch in batches:
        latest_batches.setdefault((batch.store_id, batch.source_period), batch)
    batch_ids = [batch.batch_id for batch in latest_batches.values()]
    if not batch_ids:
        return {"detail_type": detail_type, "records": [], "total": 0}
    state_field = {
        "fulfillment": "order_state",
        "aftersales": "aftersale_state",
        "abnormal": "abnormal_state",
    }[detail_type]
    result = []
    rows = db.query(JdWorkbenchRecord).filter(
        JdWorkbenchRecord.tenant_id == user.tenant_id,
        JdWorkbenchRecord.company_id == user.company_id,
        JdWorkbenchRecord.batch_id.in_(batch_ids),
    ).order_by(JdWorkbenchRecord.created_at.desc(), JdWorkbenchRecord.id.desc()).limit(limit * 3).all()
    for row in rows:
        values = json.loads(row.values_json)
        if status and values.get(state_field) != status:
            continue
        store = store_map[row.store_id]
        result.append(
            {
                "store_id": store.id,
                "store_code": store.store_code,
                "store_name": store.store_name,
                "order_reference": f"JD-{row.source_record_key[:12].upper()}",
                "source_period": row.source_period,
                "current_status": values.get(state_field),
                **values,
            }
        )
        if len(result) >= limit:
            break
    return {"detail_type": detail_type, "records": result, "total": len(result)}


@router.get("/dashboard/stores/{store_id}/{detail_type}")
def cloud_store_order_details(
    store_id: int,
    detail_type: str,
    request: Request,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Backward-compatible per-store route used by the R297 desktop and existing links."""
    return cloud_order_details(
        detail_type=detail_type,
        request=request,
        store_id=store_id,
        limit=limit,
        db=db,
    )


@router.get("/devices")
def list_devices(request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, INGEST_PERMISSION)
    devices = db.query(JdWorkbenchDevice).filter(
        JdWorkbenchDevice.tenant_id == user.tenant_id,
        JdWorkbenchDevice.company_id == user.company_id,
        JdWorkbenchDevice.user_id == user.id,
    ).order_by(JdWorkbenchDevice.created_at.desc()).all()
    return [
        {
            "device_id": device.device_id,
            "device_name": device.device_name,
            "client_version": device.client_version,
            "status": device.status,
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
            "expires_at": device.expires_at.isoformat(),
            "revoked_at": device.revoked_at.isoformat() if device.revoked_at else None,
        }
        for device in devices
    ]


@router.post("/devices/{device_id}/revoke")
def revoke_device(device_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, INGEST_PERMISSION)
    device = db.query(JdWorkbenchDevice).filter(
        JdWorkbenchDevice.device_id == device_id,
        JdWorkbenchDevice.tenant_id == user.tenant_id,
        JdWorkbenchDevice.company_id == user.company_id,
        JdWorkbenchDevice.user_id == user.id,
    ).one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    device.revoked_at = _now()
    device.status = "REVOKED"
    db.commit()
    return {"ok": True, "device_id": device.device_id, "status": "REVOKED"}
