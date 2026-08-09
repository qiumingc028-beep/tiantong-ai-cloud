from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.auth import hash_password
from backend.database import SessionLocal
from backend.models import Company, Store, Tenant, User, UserStoreMembership


PRIVILEGED_ROLES = {"owner", "boss", "admin"}
PASSWORD_ENV = "ADMIN_RESET_PASSWORD"
CORE_ADMIN_ACCOUNTS = {
    "owner": {"role": "owner", "display_name": "Owner"},
    "boss": {"role": "boss", "display_name": "老板"},
    "admin": {"role": "admin", "display_name": "Admin"},
}


@dataclass(frozen=True)
class AdminAccountSummary:
    username: str
    role: str
    display_name: str
    active: bool
    password_hash_algorithm: str


def list_admin_accounts(db: Session) -> list[AdminAccountSummary]:
    rows = (
        db.query(User)
        .filter(User.role.in_(PRIVILEGED_ROLES))
        .order_by(User.role.asc(), User.username.asc())
        .all()
    )
    return [
        AdminAccountSummary(
            username=row.username,
            role=row.role,
            display_name=row.display_name,
            active=bool(row.active),
            password_hash_algorithm=password_hash_algorithm(row.password_hash),
        )
        for row in rows
    ]


def reset_admin_password(
    db: Session,
    username: str,
    new_password: str,
    *,
    role: str | None = None,
    create_missing: bool = False,
    display_name: str | None = None,
) -> AdminAccountSummary:
    clean_username = username.strip()
    if not clean_username:
        raise ValueError("username is required")
    if role and role not in PRIVILEGED_ROLES:
        raise ValueError("role must be one of: admin, boss, owner")
    if len(new_password) < 12:
        raise ValueError("new password must be at least 12 characters")

    user = db.query(User).filter(User.username == clean_username).one_or_none()
    if not user:
        if not create_missing:
            raise ValueError("admin account does not exist; use --create-missing after confirming the environment")
        tenant_id, company_id = unique_active_scope(db)
        user = User(
            username=clean_username,
            password_hash=hash_password(new_password),
            role=role or "boss",
            display_name=display_name or clean_username,
            tenant_id=tenant_id,
            company_id=company_id,
            active=True,
        )
        db.add(user)
        db.flush()
        for store in db.query(Store).filter(
            Store.tenant_id == tenant_id,
            Store.company_id == company_id,
        ):
            db.add(
                UserStoreMembership(
                    user_id=user.id,
                    store_id=store.id,
                    can_read=True,
                    can_write=True,
                    active=True,
                )
            )
    else:
        if user.role not in PRIVILEGED_ROLES and not role:
            raise ValueError("refusing to reset a non-admin account without an explicit privileged --role")
        user.password_hash = hash_password(new_password)
        user.role = role or user.role
        user.display_name = display_name or user.display_name
        user.active = True

    db.commit()
    db.refresh(user)
    return AdminAccountSummary(
        username=user.username,
        role=user.role,
        display_name=user.display_name,
        active=bool(user.active),
        password_hash_algorithm=password_hash_algorithm(user.password_hash),
    )


def unique_active_scope(db: Session) -> tuple[int, int]:
    scopes = (
        db.query(Tenant.id, Company.id)
        .join(Company, Company.tenant_id == Tenant.id)
        .filter(Tenant.active.is_(True), Company.active.is_(True))
        .all()
    )
    if len(scopes) != 1:
        raise ValueError("admin account creation requires exactly one active tenant/company scope")
    return scopes[0]


def ensure_core_admin_accounts(db: Session, new_password: str) -> list[AdminAccountSummary]:
    if len(new_password) < 12:
        raise ValueError("new password must be at least 12 characters")
    summaries = []
    for username, account in CORE_ADMIN_ACCOUNTS.items():
        summaries.append(
            reset_admin_password(
                db,
                username,
                new_password,
                role=account["role"],
                create_missing=True,
                display_name=account["display_name"],
            )
        )
    return summaries


def password_hash_algorithm(password_hash: str | None) -> str:
    if not password_hash:
        return "missing"
    return password_hash.split("$", 1)[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List or reset privileged login accounts without printing secrets.")
    parser.add_argument("--list", action="store_true", help="List owner/boss/admin accounts without password hashes.")
    parser.add_argument("--reset", action="store_true", help=f"Reset a privileged account password from ${PASSWORD_ENV}.")
    parser.add_argument(
        "--ensure-core-admins",
        action="store_true",
        help=f"Create or repair owner/boss/admin accounts with password from ${PASSWORD_ENV}.",
    )
    parser.add_argument("--username", default="boss", help="Account username to reset. Defaults to boss.")
    parser.add_argument("--role", choices=sorted(PRIVILEGED_ROLES), help="Set or enforce a privileged role during reset.")
    parser.add_argument("--display-name", help="Display name to set when creating or repairing the account.")
    parser.add_argument("--create-missing", action="store_true", help="Create the account if missing.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.list and not args.reset and not args.ensure_core_admins:
        raise SystemExit("choose --list, --reset, or --ensure-core-admins")

    db = SessionLocal()
    try:
        if args.list:
            for row in list_admin_accounts(db):
                print(
                    f"username={row.username} role={row.role} active={row.active} "
                    f"hash_algorithm={row.password_hash_algorithm} display_name={row.display_name}"
                )
        if args.reset:
            new_password = os.getenv(PASSWORD_ENV, "")
            summary = reset_admin_password(
                db,
                args.username,
                new_password,
                role=args.role,
                create_missing=args.create_missing,
                display_name=args.display_name,
            )
            print(
                f"reset_ok username={summary.username} role={summary.role} active={summary.active} "
                f"hash_algorithm={summary.password_hash_algorithm}"
            )
        if args.ensure_core_admins:
            new_password = os.getenv(PASSWORD_ENV, "")
            for summary in ensure_core_admin_accounts(db, new_password):
                print(
                    f"ensure_ok username={summary.username} role={summary.role} active={summary.active} "
                    f"hash_algorithm={summary.password_hash_algorithm}"
                )
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
