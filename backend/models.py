from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    permissions: Mapped[list["Permission"]] = relationship(secondary=role_permissions, back_populates="roles")


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    roles: Mapped[list[Role]] = relationship(secondary=role_permissions, back_populates="permissions")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), default="jd", nullable=False)
    store_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    store_name: Mapped[str] = mapped_column(String(200), nullable=False)
    manager_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    manager: Mapped[User | None] = relationship()


class AccountTemplate(Base):
    __tablename__ = "account_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    fields_json: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_code: Mapped[str | None] = mapped_column(String(100), unique=True)
    brand_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    owner_name: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StoreGroup(Base):
    __tablename__ = "store_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_code: Mapped[str | None] = mapped_column(String(100), unique=True)
    group_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StoreAccountNote(Base):
    __tablename__ = "store_account_notes"
    __table_args__ = (UniqueConstraint("store_id", name="uq_store_account_notes_store"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id", ondelete="SET NULL"))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("store_groups.id", ondelete="SET NULL"))
    login_account: Mapped[str | None] = mapped_column(String(200))
    encrypted_password: Mapped[str | None] = mapped_column(Text)
    cookie_status: Mapped[str] = mapped_column(String(50), default="待登录")
    login_status: Mapped[str] = mapped_column(String(50), default="待登录")
    account_status: Mapped[str] = mapped_column(String(50), default="待登录")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    store: Mapped[Store] = relationship()
    brand: Mapped[Brand | None] = relationship()
    group: Mapped[StoreGroup | None] = relationship()


class EmployeeStoreAssignment(Base):
    __tablename__ = "employee_store_assignments"
    __table_args__ = (UniqueConstraint("store_id", name="uq_employee_store_assignments_store"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    role_name: Mapped[str] = mapped_column(String(50), default="负责人")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    store: Mapped[Store] = relationship()


class MetricDaily(Base):
    __tablename__ = "metrics_daily"
    __table_args__ = (UniqueConstraint("store_id", "metric_date", name="uq_metrics_daily_store_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    metric_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    sales_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    profit_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    ad_spend: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    roi: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    visitors_count: Mapped[int] = mapped_column(Integer, default=0)
    refunds_count: Mapped[int] = mapped_column(Integer, default=0)
    after_sales_count: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(50), default="manual")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    store: Mapped[Store] = relationship()


class EmployeeLog(Base):
    __tablename__ = "employee_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AiTask(Base):
    __tablename__ = "ai_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ai_employee_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    ai_employee_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="idle")
    today_task: Mapped[str | None] = mapped_column(Text)
    execution_log: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    owner: Mapped[User | None] = relationship()


class AiEmployee(Base):
    __tablename__ = "ai_employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    employee_name: Mapped[str] = mapped_column(String(100), nullable=False)
    legion: Mapped[str | None] = mapped_column(String(100))
    duty: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False, index=True)
    task_types: Mapped[str | None] = mapped_column(Text)
    default_permissions: Mapped[str | None] = mapped_column(Text)
    is_legacy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TaskCenterTask(Base):
    __tablename__ = "task_center_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="created", nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(50), default="normal", nullable=False)
    source: Mapped[str] = mapped_column(String(50), default="boss", nullable=False)
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"))
    assigned_ai_employee_code: Mapped[str | None] = mapped_column(String(50), index=True)
    assigned_ai_employee_name: Mapped[str | None] = mapped_column(String(100))
    split_plan: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_id])
    parent_task: Mapped["TaskCenterTask | None"] = relationship(remote_side=[id])


class TaskCenterResult(Base):
    __tablename__ = "task_center_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    ai_employee_code: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_employee_name: Mapped[str | None] = mapped_column(String(100))
    result_content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments_json: Mapped[str | None] = mapped_column(Text)
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    task: Mapped[TaskCenterTask] = relationship()
    submitted_by: Mapped[User | None] = relationship()


class TaskCenterReview(Base):
    __tablename__ = "task_center_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    review_type: Mapped[str] = mapped_column(String(50), nullable=False)
    review_status: Mapped[str] = mapped_column(String(50), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    reviewer_role: Mapped[str | None] = mapped_column(String(50))
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    task: Mapped[TaskCenterTask] = relationship()
    reviewer: Mapped[User | None] = relationship()


class TaskCenterAuditLog(Base):
    __tablename__ = "task_center_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(50))
    to_status: Mapped[str | None] = mapped_column(String(50))
    detail: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_role: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    task: Mapped[TaskCenterTask] = relationship()
    actor: Mapped[User | None] = relationship()


class JdIntegration(Base):
    __tablename__ = "jd_integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    connection_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    merchant_id: Mapped[str | None] = mapped_column(String(100))
    app_key: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    store: Mapped[Store] = relationship()


class JdAccount(Base):
    __tablename__ = "jd_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), default="jd", nullable=False)
    account_type: Mapped[str] = mapped_column(String(50), nullable=False)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False)
    login_username: Mapped[str | None] = mapped_column(String(200))
    login_status: Mapped[str] = mapped_column(String(50), default="unknown")
    cookie_status: Mapped[str] = mapped_column(String(50), default="unknown")
    auth_status: Mapped[str] = mapped_column(String(50), default="pending")
    access_token: Mapped[str | None] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remark: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    store: Mapped[Store] = relationship()


class JdSyncLog(Base):
    __tablename__ = "jd_sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("jd_accounts.id", ondelete="SET NULL"))
    task_id: Mapped[str | None] = mapped_column(String(100), index=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    store: Mapped[Store | None] = relationship()
    account: Mapped[JdAccount | None] = relationship()


class JdDailyMetric(Base):
    __tablename__ = "jd_daily_metrics"
    __table_args__ = (UniqueConstraint("store_id", "metric_date", name="uq_jd_daily_metrics_store_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    metric_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    gmv: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    profit_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    visitors_count: Mapped[int] = mapped_column(Integer, default=0)
    paid_orders_count: Mapped[int] = mapped_column(Integer, default=0)
    ad_spend: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    roi: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    refunds_count: Mapped[int] = mapped_column(Integer, default=0)
    after_sales_count: Mapped[int] = mapped_column(Integer, default=0)
    favorites_count: Mapped[int] = mapped_column(Integer, default=0)
    cart_add_count: Mapped[int] = mapped_column(Integer, default=0)
    conversion_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    source: Mapped[str] = mapped_column(String(50), default="jd")
    raw_payload: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    store: Mapped[Store] = relationship()


class JdAd(Base):
    __tablename__ = "jd_ads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("jd_accounts.id", ondelete="SET NULL"))
    stat_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    campaign_id: Mapped[str | None] = mapped_column(String(100))
    campaign_name: Mapped[str | None] = mapped_column(String(200))
    ad_spend: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    roi: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    cpa: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    deal_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    raw_payload: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    store: Mapped[Store] = relationship()
    account: Mapped[JdAccount | None] = relationship()


class JdOrder(Base):
    __tablename__ = "jd_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    order_no: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    order_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    paid_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    profit_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    order_status: Mapped[str | None] = mapped_column(String(50))
    buyer_pin: Mapped[str | None] = mapped_column(String(100))
    raw_payload: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    store: Mapped[Store] = relationship()


class JdProduct(Base):
    __tablename__ = "jd_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    sku_id: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name: Mapped[str] = mapped_column(String(300), nullable=False)
    category_name: Mapped[str | None] = mapped_column(String(200))
    stock_quantity: Mapped[int] = mapped_column(Integer, default=0)
    sales_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    sales_quantity: Mapped[int] = mapped_column(Integer, default=0)
    visitors_count: Mapped[int] = mapped_column(Integer, default=0)
    conversion_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    stat_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    raw_payload: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    store: Mapped[Store] = relationship()


class KnowledgeFile(Base):
    __tablename__ = "knowledge_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(255))
    file_path: Mapped[str | None] = mapped_column(Text)
    file_type: Mapped[str | None] = mapped_column(String(100))
    content_type: Mapped[str | None] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    content_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    ai_tags: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    uploader: Mapped[User | None] = relationship()


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_files.id", ondelete="SET NULL"))
    source_file_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_files.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    tags: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    file: Mapped[KnowledgeFile | None] = relationship(foreign_keys=[file_id])
    source_file: Mapped[KnowledgeFile | None] = relationship(foreign_keys=[source_file_id])
    creator: Mapped[User | None] = relationship()


class SopLibrary(Base):
    __tablename__ = "sop_library"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_articles.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100))
    content: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    steps: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    article: Mapped[KnowledgeArticle | None] = relationship()
