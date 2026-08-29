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
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

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
    Store,
    User,
)
from ..store_authorization import authorized_stores, require_authorized_store


router = APIRouter(prefix="/api/jd-workbench", tags=["jd-workbench"])

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 500
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
}
MONEY_FIELDS = frozenset({"sales_amount", "paid_amount", "refund_amount", "ad_spend", "attributed_sales"})
RATIO_FIELDS = frozenset({"roi", "promotion_rate"})
INTEGER_FIELDS = frozenset({"orders_count", "order_count", "refund_order_count", "stock_quantity"})
TEXT_LIMITS = {"product_name": 200, "category_name": 120}
PROMOTION_CHANNELS = frozenset({"jd_kuaiche", "haitou", "jingtiaoke", "jingzhuntong", "other"})
DEVICE_STATUSES = frozenset({"ONLINE", "IDLE", "SYNCING", "OFFLINE", "ERROR", "HUMAN_ACTION_REQUIRED"})
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
    return HTTPException(status_code=400, detail="请求字段不符合R291只读同步合同")


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
    if not isinstance(records, list) or not (1 <= len(records) <= MAX_RECORDS):
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
    result = []
    for store in stores:
        store_uuid = _store_uuid(store)
        status = statuses.get(store.id)
        result.append(
            {
                "store_id": store.id,
                "subject_id": store.company_id,
                "store_uuid": store_uuid,
                "partition": f"persist:jd-{store_uuid}",
                "store_code": store.store_code,
                "store_name": store.store_name,
                "status": status.status if status else "OFFLINE",
                "reason_code": status.reason_code if status else None,
                "last_sync_at": status.last_sync_at.isoformat() if status and status.last_sync_at else None,
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
        frozenset({"store_id", "reason_code"}),
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
    elif reason_code is not None:
        raise _generic_bad_request()
    now = _now()
    if store_id is not None:
        if not isinstance(store_id, int) or isinstance(store_id, bool):
            raise _generic_bad_request()
        store = require_authorized_store(db, user, store_id=store_id, write=True)
        row = _status_row(db, device.device_id, store.id)
        row.status = status
        row.reason_code = reason_code
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
    status.status = "IDLE"
    status.reason_code = None
    status.last_sync_at = now
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


@router.get("/dashboard")
def cloud_dashboard(
    request: Request,
    store_id: int | None = None,
    db: Session = Depends(get_db),
):
    user = require_permission_user(request, db, "menu.jd_data")
    store_query = authorized_stores(db, user).filter(Store.platform == "jd")
    if store_id is not None:
        store_query = store_query.filter(Store.id == store_id)
    stores = store_query.order_by(Store.id.asc()).all()
    items = []
    for store in stores:
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
        latest_batches: dict[str, JdWorkbenchSyncBatch] = {}
        for batch in db.query(JdWorkbenchSyncBatch).filter(
            JdWorkbenchSyncBatch.tenant_id == user.tenant_id,
            JdWorkbenchSyncBatch.company_id == user.company_id,
            JdWorkbenchSyncBatch.store_id == store.id,
        ).order_by(JdWorkbenchSyncBatch.collected_at.desc(), JdWorkbenchSyncBatch.created_at.desc()).all():
            latest_batches.setdefault(batch.dataset_type, batch)
        datasets = {}
        for dataset_type, batch in latest_batches.items():
            records = db.query(JdWorkbenchRecord).filter(
                JdWorkbenchRecord.tenant_id == user.tenant_id,
                JdWorkbenchRecord.company_id == user.company_id,
                JdWorkbenchRecord.store_id == store.id,
                JdWorkbenchRecord.dataset_type == dataset_type,
                JdWorkbenchRecord.source_period == batch.source_period,
            ).order_by(JdWorkbenchRecord.id.asc()).limit(100).all()
            datasets[dataset_type] = {
                "source": "jd_workbench_readonly",
                "source_period": batch.source_period,
                "collected_at": batch.collected_at.isoformat(),
                "client_version": batch.client_version,
                "record_count": len(records),
                "records": [json.loads(record.values_json) for record in records],
            }
        items.append(
            {
                "store_id": store.id,
                "subject_id": store.company_id,
                "store_name": store.store_name,
                "sync_status": latest_status.status if latest_status else "OFFLINE",
                "reason_code": latest_status.reason_code if latest_status else None,
                "last_sync_at": latest_status.last_sync_at.isoformat() if latest_status and latest_status.last_sync_at else None,
                "data_state": "READY" if datasets else "NO_DATA",
                "empty_message": None if datasets else "暂无数据",
                "datasets": datasets,
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
    }
    present = {key: False for key in summary_values}
    attributed_sales = Decimal("0")
    attributed_present = False
    for item in items:
        datasets = item["datasets"]
        for record in datasets.get("sales_daily", {}).get("records", []):
            summary_values["sales_amount"] += Decimal(record["sales_amount"])
            present["sales_amount"] = True
        order_records = datasets.get("orders", {}).get("records")
        if order_records is None:
            order_records = datasets.get("sales_daily", {}).get("records", [])
            order_field = "orders_count"
        else:
            order_field = "order_count"
        for record in order_records:
            summary_values["orders_count"] += int(record[order_field])
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
        for record in datasets.get("promotion_costs", {}).get("records", []):
            summary_values["ad_spend"] += Decimal(record["ad_spend"])
            present["ad_spend"] = True
            if "attributed_sales" in record:
                attributed_sales += Decimal(record["attributed_sales"])
                attributed_present = True
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
    return {
        "stores": items,
        "total": len(items),
        "source": "jd_workbench_readonly",
        "summary": summary,
        "ready_stores": sum(item["data_state"] == "READY" for item in items),
        "human_action_required": sum(item["sync_status"] == "HUMAN_ACTION_REQUIRED" for item in items),
    }


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
