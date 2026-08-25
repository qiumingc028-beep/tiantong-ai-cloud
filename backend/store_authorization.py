from fastapi import HTTPException
from sqlalchemy import and_, exists
from sqlalchemy.orm import Session

from .models import Company, Store, Tenant, User, UserStoreMembership


STORE_ACCESS_DENIED = "没有店铺访问权限"


def authorized_store_condition(user: User, *, write: bool = False, active_only: bool = True):
    permission = UserStoreMembership.can_write if write else UserStoreMembership.can_read
    return and_(
        Store.active.is_(True) if active_only else True,
        Store.tenant_id == user.tenant_id,
        Store.company_id == user.company_id,
        exists().where(Tenant.id == user.tenant_id, Tenant.active.is_(True)),
        exists().where(
            Company.id == user.company_id,
            Company.tenant_id == user.tenant_id,
            Company.active.is_(True),
        ),
        exists().where(
            UserStoreMembership.user_id == user.id,
            UserStoreMembership.store_id == Store.id,
            UserStoreMembership.active.is_(True),
            permission.is_(True),
        ),
    )


def authorized_stores(db: Session, user: User, *, write: bool = False, active_only: bool = True):
    return db.query(Store).filter(
        authorized_store_condition(user, write=write, active_only=active_only)
    )


def require_authorized_store(
    db: Session,
    user: User,
    *,
    store_id: int | None = None,
    store_code: str | None = None,
    write: bool = False,
    for_update: bool = False,
    active_only: bool = True,
) -> Store:
    query = authorized_stores(db, user, write=write, active_only=active_only)
    if store_id is not None:
        query = query.filter(Store.id == store_id)
    elif store_code:
        query = query.filter(Store.store_code == store_code)
    else:
        raise HTTPException(status_code=403, detail=STORE_ACCESS_DENIED)
    if for_update:
        query = query.with_for_update()
    store = query.one_or_none()
    if not store:
        raise HTTPException(status_code=403, detail=STORE_ACCESS_DENIED)
    return store
