from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..auth import (
    ROLE_LABELS,
    create_session,
    delete_session,
    hash_password,
    normalize_role,
    require_admin_user,
    require_user,
    serialize_user,
    verify_password,
)
from ..database import get_db
from ..models import EmployeeLog, User


router = APIRouter()


@router.post("/api/login")
async def login(request: Request, response: Response, db: Session = Depends(get_db)):
    data = await request.json()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    user = db.query(User).filter(User.username == username).one_or_none()

    if not user or not user.active or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")

    session_token, jwt_token = create_session(user.id)
    db.add(EmployeeLog(user_id=user.id, action="login", detail="员工登录", ip_address=request.client.host if request.client else None))
    db.commit()

    response.set_cookie("tiantong_session", session_token, httponly=True, samesite="lax", max_age=7 * 24 * 3600)
    response.set_cookie("tiantong_jwt", jwt_token, httponly=True, samesite="lax", max_age=7 * 24 * 3600)
    return {"ok": True, "token": jwt_token, "user": serialize_user(db, user)}


@router.post("/api/logout")
def logout(request: Request, response: Response):
    delete_session(request.cookies.get("tiantong_session"))
    response.delete_cookie("tiantong_session")
    response.delete_cookie("tiantong_jwt")
    return {"ok": True}


@router.get("/api/me")
def me(request: Request, db: Session = Depends(get_db)):
    return require_user(request, db)


@router.get("/api/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    return {"title": "老板驾驶舱", "user": user, "message": "系统已连接 PostgreSQL、Redis、JWT 和 SQLAlchemy ORM。"}


@router.get("/api/users")
def list_users(request: Request, db: Session = Depends(get_db)):
    require_admin_user(request, db)
    users = db.query(User).order_by(User.id.asc()).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "role_code": normalize_role(u.role),
            "role_label": ROLE_LABELS.get(normalize_role(u.role), u.role),
            "display_name": u.display_name,
            "active": u.active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.get("/api/menus")
def menus(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    return {"role": user["role"], "role_code": user["role_code"], "menus": user["menus"]}


@router.get("/api/roles")
def roles(request: Request, db: Session = Depends(get_db)):
    require_admin_user(request, db)
    return [{"code": code, "name": label} for code, label in ROLE_LABELS.items()]


@router.post("/api/users")
async def create_user(request: Request, db: Session = Depends(get_db)):
    require_admin_user(request, db)
    data = await request.json()
    username = data.get("username", "").strip()
    display_name = data.get("display_name", "").strip()
    role = data.get("role", "").strip()
    allowed_roles = {"owner", "boss", "admin", "operator", "service", "customer_service", "designer", "editor", "finance", "ads"}

    if role not in allowed_roles:
        raise HTTPException(status_code=400, detail="角色不正确")
    if not username or not display_name:
        raise HTTPException(status_code=400, detail="用户名和姓名不能为空")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")

    import secrets
    password = secrets.token_urlsafe(10)
    db.add(User(username=username, password_hash=hash_password(password), role=role, display_name=display_name, active=True))
    db.commit()
    return {"ok": True, "username": username, "display_name": display_name, "role": role, "password": password}


@router.post("/api/users/{user_id}/reset-password")
def reset_user_password(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin_user(request, db)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    import secrets
    password = secrets.token_urlsafe(10)
    user.password_hash = hash_password(password)
    db.commit()
    return {"ok": True, "username": user.username, "password": password}


@router.post("/api/users/{user_id}/toggle")
def toggle_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin_user(request, db)
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="不能停用自己")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.active = not user.active
    db.commit()
    return {"ok": True, "username": user.username, "active": user.active}
