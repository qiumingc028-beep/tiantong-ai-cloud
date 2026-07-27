from __future__ import annotations

import hashlib
import os
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..models import AiProductAsset, AiProductDraft, Store, User


router = APIRouter(prefix="/api/ai-products", tags=["ai-products"])
CANONICAL_TENANT_ID = "tiantong"
STORAGE_ROOT = Path("artifacts/product-assets")
MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_FILES = 9
ALLOWED_TYPES = {
    ".jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    ".png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
    ".webp": ("image/webp", (b"RIFF",)),
}
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,254}$")


def _available_shops(db: Session, user: User):
    query = db.query(Store).filter(Store.active.is_(True))
    if normalize_role(user.role) not in {"owner", "admin"}:
        query = query.filter(Store.manager_user_id == user.id)
    return query.order_by(Store.id.asc())


def _require_shop(db: Session, user: User, shop_id: int) -> Store:
    shop = _available_shops(db, user).filter(Store.id == shop_id).one_or_none()
    if shop is None:
        raise HTTPException(status_code=404, detail="店铺不存在或不可访问")
    return shop


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


@router.get("/shops")
def list_available_shops(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    return {
        "shops": [
            {"id": shop.id, "store_code": shop.store_code, "store_name": shop.store_name}
            for shop in _available_shops(db, user).all()
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
    _require_shop(db, user, shop_id)
    if not files or len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail="每次必须上传 1 到 9 个文件")

    validated = []
    try:
        for upload in files:
            validated.append(await _validate_upload(upload))
    finally:
        for upload in files:
            await upload.close()

    draft = AiProductDraft(
        tenant_id=CANONICAL_TENANT_ID,
        shop_id=shop_id,
        created_by=user.id,
        status="draft",
    )
    db.add(draft)
    db.flush()
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    assets: list[AiProductAsset] = []
    try:
        for original_filename, content, mime_type in validated:
            storage_key = secrets.token_hex(32)
            path = STORAGE_ROOT / storage_key
            written.append(path)
            with path.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            asset = AiProductAsset(
                draft_id=draft.id,
                tenant_id=CANONICAL_TENANT_ID,
                shop_id=shop_id,
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
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return {"draft_id": draft.id, "assets": [_asset_dict(asset) for asset in assets]}


@router.get("/assets")
def list_assets(request: Request, shop_id: int | None = None, db: Session = Depends(get_db)):
    user = current_user(request, db)
    allowed_shop_ids = _available_shops(db, user).with_entities(Store.id)
    query = db.query(AiProductAsset).filter(
        AiProductAsset.tenant_id == CANONICAL_TENANT_ID,
        AiProductAsset.shop_id.in_(allowed_shop_ids),
    )
    if shop_id is not None:
        _require_shop(db, user, shop_id)
        query = query.filter(AiProductAsset.shop_id == shop_id)
    assets = query.order_by(AiProductAsset.id.asc()).all()
    return {"assets": [_asset_dict(asset) for asset in assets]}


@router.get("/assets/{asset_id}")
def read_asset(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    allowed_shop_ids = _available_shops(db, user).with_entities(Store.id)
    asset = db.query(AiProductAsset).filter(
        AiProductAsset.id == asset_id,
        AiProductAsset.tenant_id == CANONICAL_TENANT_ID,
        AiProductAsset.shop_id.in_(allowed_shop_ids),
    ).one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="素材不存在")
    return _asset_dict(asset)
