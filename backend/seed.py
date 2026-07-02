from sqlalchemy.orm import Session

from .auth_data import ROLE_LABELS
from .models import AiTask, Permission, Role


PERMISSIONS = [
    ("menu.dashboard", "老板驾驶舱"),
    ("menu.employees", "员工中心"),
    ("menu.stores", "店铺管理"),
    ("menu.jd_data", "京东数据中心"),
    ("menu.ads", "广告中心"),
    ("menu.metrics", "今日数据录入"),
    ("menu.import", "Excel导入"),
    ("menu.ai_assets", "AI素材中心"),
    ("menu.tiancang", "天藏：知识资产中心"),
    ("menu.workflows", "AI工作流"),
    ("menu.ai_employees", "AI员工管理"),
    ("menu.settings", "系统设置"),
    ("data.metrics.read", "读取经营数据"),
    ("data.metrics.write", "写入经营数据"),
    ("users.manage", "管理员工"),
    ("stores.manage", "管理店铺"),
    ("ai.tasks.read", "读取AI员工任务"),
    ("ai.tasks.manage", "管理AI员工任务"),
]

ROLE_PERMISSIONS = {
    "owner": [p[0] for p in PERMISSIONS],
    "admin": [p[0] for p in PERMISSIONS],
    "operator": [
        "menu.dashboard", "menu.stores", "menu.jd_data", "menu.ads",
        "menu.metrics", "menu.import", "menu.workflows",
        "data.metrics.read", "data.metrics.write", "stores.manage", "ai.tasks.read",
    ],
    "customer_service": ["menu.dashboard", "menu.metrics", "data.metrics.read", "data.metrics.write", "ai.tasks.read"],
    "designer": ["menu.ai_assets", "menu.workflows", "ai.tasks.read"],
    "editor": ["menu.ai_assets", "menu.workflows", "ai.tasks.read"],
    "finance": ["menu.dashboard", "menu.metrics", "menu.import", "data.metrics.read", "data.metrics.write"],
}

AI_EMPLOYEES = [
    ("ai_store_manager", "AI店长", "检查60店经营健康度，输出异常店铺和优先处理事项。"),
    ("ai_operator", "AI运营", "分析今日成交、ROI、访客和订单变化，给出运营动作。"),
    ("ai_designer", "AI美工", "整理待优化商品素材，生成图片和详情页优化建议。"),
    ("ai_video", "AI视频", "生成短视频脚本、剪辑任务和素材拍摄清单。"),
    ("ai_ads", "AI投流", "检查广告花费和ROI，定位低效计划。"),
    ("ai_service", "AI客服", "汇总退款、售后和客服异常问题。"),
    ("ai_data_analyst", "AI数据分析", "生成经营日报和跨店铺趋势分析。"),
]


PERMISSIONS.append(("menu.account_center", "账号资料中心"))
for role_code in ("owner", "admin", "operator"):
    ROLE_PERMISSIONS.setdefault(role_code, []).append("menu.account_center")


def seed_defaults(db: Session):
    permission_by_code = {}
    for code, name in PERMISSIONS:
        permission = db.query(Permission).filter(Permission.code == code).one_or_none()
        if not permission:
            permission = Permission(code=code, name=name)
            db.add(permission)
        else:
            permission.name = name
        permission_by_code[code] = permission

    for code, label in ROLE_LABELS.items():
        role = db.query(Role).filter(Role.code == code).one_or_none()
        if not role:
            role = Role(code=code, name=label, description=f"{label}角色")
            db.add(role)
        else:
            role.name = label
        role.permissions = [permission_by_code[p] for p in ROLE_PERMISSIONS.get(code, [])]

    for code, name, task in AI_EMPLOYEES:
        ai_task = db.query(AiTask).filter(AiTask.ai_employee_code == code).one_or_none()
        if not ai_task:
            db.add(AiTask(ai_employee_code=code, ai_employee_name=name, status="idle", today_task=task, execution_log=""))
        else:
            ai_task.ai_employee_name = name

    db.commit()

PERMISSIONS.extend([
])
PERMISSIONS.extend([("menu.knowledge_center", "\u5929\u85cf\uff1a\u77e5\u8bc6\u8d44\u4ea7\u4e2d\u5fc3"), ("knowledge.read", "read knowledge assets"), ("knowledge.manage", "manage knowledge assets")])
for role_code in ("owner", "admin", "operator"):
    ROLE_PERMISSIONS.setdefault(role_code, []).extend(["menu.knowledge_center", "knowledge.read", "knowledge.manage"])

PERMISSIONS.extend([
    ("task_center.read", "read task center"),
    ("task_center.manage", "manage task center"),
    ("task_center.execute", "execute task center tasks"),
    ("task_center.review", "review task center tasks"),
    ("task_center.audit", "audit task center tasks"),
])
for role_code in ("owner", "admin"):
    ROLE_PERMISSIONS.setdefault(role_code, []).extend([
        "task_center.read",
        "task_center.manage",
        "task_center.execute",
        "task_center.review",
        "task_center.audit",
    ])
