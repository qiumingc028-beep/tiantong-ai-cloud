from __future__ import annotations

import hashlib
import os
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import String, cast
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import get_settings
from ..database import get_db
from ..models import AiProductAsset, AiProductDraft, Store, User
from ..store_authorization import authorized_stores, require_authorized_store


router = APIRouter(prefix="/api/ai-products", tags=["ai-products"])
MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_FILES = 9
ALLOWED_TYPES = {
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".webp": ("image/webp", (b"RIFF",)),
}
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,254}$")


def _validated_filename(filename: str | None) -> tuple[str, str, tuple[bytes, ...]]:
    if not filename or not SAFE_FILENAME.fullmatch(filename):
        raise HTTPException(status_code=400, detail="文件名不安全")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="文件名不安全")
    suffixes = Path(filename).suffixes
    if len(suffixes) != 1:
        raise HTTPException(status_code=400, detail="不允许双扩展名")
    extension = suffixes[0].lower()
    if extension not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 JPEG、PNG 和 WEBP")
    mime_type, signatures = ALLOWED_TYPES[extension]
    return extension, mime_type, signatures


async def _validate_upload(upload: UploadFile) -> tuple[str, bytes, str]:
    _, expected_mime, signatures = _validated_filename(upload.filename)
    if upload.content_type != expected_mime:
        raise HTTPException(status_code=400, detail="文件扩展名与 MIME 类型不一致")
    content = await upload.read(MAX_FILE_SIZE + 1)
    if not content:
        raise HTTPException(status_code=400, detail="文件不能为空")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="单个文件不能超过 10 MiB")
    valid_magic = any(content.startswith(signature) for signature in signatures)
    if expected_mime == "image/webp":
        valid_magic = len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    if not valid_magic:
        raise HTTPException(status_code=400, detail="文件真实格式与声明不一致")
    return upload.filename, content, expected_mime


def _asset_dict(asset: AiProductAsset) -> dict:
    return {
        "id": asset.id,
        "draft_id": asset.draft_id,
        "shop_id": asset.shop_id,
        "original_filename": asset.original_filename,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "sha256": asset.sha256,
        "status": asset.status,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


def _storage_directory(tenant_key: str, shop_id: int) -> Path:
    root = get_settings().ASSET_STORAGE_ROOT
    if not root.is_absolute() or root.is_symlink():
        raise HTTPException(status_code=500, detail="素材存储配置不安全")
    root.mkdir(parents=True, exist_ok=True)
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="素材存储不可用") from exc
    if resolved_root != root:
        raise HTTPException(status_code=500, detail="素材存储配置不安全")

    directory = root / tenant_key / str(shop_id)
    current = root
    for component in (tenant_key, str(shop_id)):
        current = current / component
        if current.is_symlink():
            raise HTTPException(status_code=500, detail="素材存储配置不安全")
        current.mkdir(mode=0o750, exist_ok=True)
        if current.is_symlink() or resolved_root not in current.resolve(strict=True).parents:
            raise HTTPException(status_code=500, detail="素材存储配置不安全")
    return directory


@router.get("/shops")
def list_available_shops(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    return {
        "shops": [
            {"id": shop.id, "store_code": shop.store_code, "store_name": shop.store_name}
            for shop in authorized_stores(db, user).order_by(Store.id.asc()).all()
        ]
    }


@router.post("/assets", status_code=status.HTTP_201_CREATED)
async def upload_assets(
    request: Request,
    shop_id: int = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    user = current_user(request, db)
    shop = require_authorized_store(db, user, store_id=shop_id, write=True)
    tenant_key = str(shop.tenant_id)
    if not files or len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail="每次必须上传 1 到 9 个文件")

    validated = []
    try:
        for upload in files:
            validated.append(await _validate_upload(upload))
    finally:
        for upload in files:
            await upload.close()

    written: list[Path] = []
    temporary: list[Path] = []
    assets: list[AiProductAsset] = []
    try:
        draft = AiProductDraft(
            tenant_id=tenant_key,
            shop_id=shop.id,
            created_by=user.id,
            status="draft",
        )
        db.add(draft)
        db.flush()
        storage_directory = _storage_directory(tenant_key, shop.id)
        for original_filename, content, mime_type in validated:
            storage_key = secrets.token_hex(32)
            path = storage_directory / storage_key
            temp_path = storage_directory / f".{storage_key}.{secrets.token_hex(16)}.tmp"
            written.append(path)
            temporary.append(temp_path)
            with temp_path.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            temporary.remove(temp_path)
            asset = AiProductAsset(
                draft_id=draft.id,
                tenant_id=tenant_key,
                shop_id=shop.id,
                created_by=user.id,
                original_filename=original_filename,
                storage_key=storage_key,
                mime_type=mime_type,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                status="ready",
            )
            db.add(asset)
            assets.append(asset)
        db.commit()
    except Exception:
        db.rollback()
        for path in temporary + written:
            path.unlink(missing_ok=True)
        raise
    return {"draft_id": draft.id, "assets": [_asset_dict(asset) for asset in assets]}


@router.get("/assets")
def list_assets(request: Request, shop_id: int | None = None, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if shop_id is not None:
        shop = require_authorized_store(db, user, store_id=shop_id)
        query = db.query(AiProductAsset).filter(
            AiProductAsset.shop_id == shop.id,
            AiProductAsset.tenant_id == str(shop.tenant_id),
        )
    else:
        allowed_shop_ids = authorized_stores(db, user).with_entities(Store.id)
        query = db.query(AiProductAsset).join(Store, Store.id == AiProductAsset.shop_id).filter(
            Store.id.in_(allowed_shop_ids),
            AiProductAsset.tenant_id == cast(Store.tenant_id, String),
        )
    assets = query.order_by(AiProductAsset.id.asc()).all()
    return {"assets": [_asset_dict(asset) for asset in assets]}


@router.get("/assets/{asset_id}")
def read_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    allowed_shop_ids = authorized_stores(db, user).with_entities(Store.id)
    asset = db.query(AiProductAsset).join(Store, Store.id == AiProductAsset.shop_id).filter(
        AiProductAsset.id == asset_id,
        Store.id.in_(allowed_shop_ids),
        AiProductAsset.tenant_id == cast(Store.tenant_id, String),
    ).one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    return _asset_dict(asset)
