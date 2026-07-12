import json
from sqlalchemy.orm import Session

from .ai_employees.registry import AI_EMPLOYEE_REGISTRY, TIANBO, TIANCAI_DATA, TIANCE_STRATEGY, TIANSHU
from .auth import hash_password, verify_password
from .auth_data import ROLE_LABELS
from .config import get_settings
from .models import AiEmployee, AiTask, Permission, Role, User
from .skills_engine.registry import ensure_default_skills, resolve_manager_user


BOSS_USERNAME = "boss"


PERMISSIONS = [
    ("menu.dashboard", "老板驾驶舱"),
    ("menu.employees", "员工中心"),
    ("menu.stores", "店铺管理"),
    ("menu.jd_data", "京东数据中心"),
    ("menu.ads", "广告中心"),
    ("menu.metrics", "今日数据录入"),
    ("menu.import", "Excel导入"),
    ("menu.ai_assets", "AI素材中心"),
    ("menu.skills_center", "技能中心"),
    ("menu.computer_executor", "电脑执行中心"),
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
    ("skills.read", "读取技能中心"),
    ("skills.manage", "管理技能中心"),
    ("skills.install", "安装技能"),
    ("skills.invoke", "调用技能"),
    ("skills.audit", "审计技能"),
    ("computer_executor.read", "读取电脑执行中心"),
    ("computer_executor.manage", "管理电脑执行中心"),
]

ROLE_PERMISSIONS = {
    "owner": [p[0] for p in PERMISSIONS],
    "admin": [p[0] for p in PERMISSIONS],
    "operator": [
        "menu.dashboard", "menu.stores", "menu.jd_data", "menu.ads",
        "menu.metrics", "menu.import", "menu.workflows",
        "data.metrics.read", "data.metrics.write", "stores.manage", "ai.tasks.read",
        "skills.read",
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

REAL_AI_EMPLOYEES = [
    ("tiantong", "天统：AI总指挥", "研发交付军团", "统筹任务拆分、分配、汇总与推进", ["command", "summary"], ["task_center.manage"], 10),
    ("tiangong", "天工：系统架构中心", "研发交付军团", "系统架构设计、技术方案与边界控制", ["architecture"], ["task_center.read"], 20),
    ("tianwang", "天王：后端开发中心", "研发交付军团", "后端 API、数据库模型、迁移、权限和测试", ["backend"], ["task_center.execute"], 30),
    ("tianyan_frontend", "天颜：前端联调优化", "研发交付军团", "前端页面、交互联调与体验优化", ["frontend"], ["task_center.execute"], 40),
    ("tianjian_test", "天检：测试验收中心", "研发交付军团", "测试验收、缺陷复核与回归验证", ["test", "acceptance"], ["task_center.review"], 50),
    ("tianjian_audit", "天监：AI审计中心", "研发交付军团", "审计任务过程、权限和结果合规性", ["audit"], ["task_center.audit"], 60),
    ("tiandun_ops", "天盾：部署运维修复", "研发交付军团", "部署运维、环境修复与运行保障", ["ops"], ["task_center.execute"], 70),
    ("tiandun_deploy", "天盾：Deploy Center", "研发交付军团", "Deploy Center 建设与发布链路", ["deploy"], ["task_center.execute"], 80),
    ("tiandao", "天道：AI产品经理中心", "产品策略军团", "产品规划、需求拆解与验收口径", ["product"], ["task_center.read"], 90),
    (TIANCE_STRATEGY, AI_EMPLOYEE_REGISTRY[TIANCE_STRATEGY].name, "经营策略军团", "经营策略、行业分析与策略建议", ["strategy"], ["task_center.read"], 100),
    ("tianyan_sim", "天演：系统推演中心", "经营策略军团", "系统推演、流程模拟与风险预判", ["simulation"], ["task_center.read"], 110),
    ("tianshi", "天市：全球市场研究中心", "市场增长军团", "全球市场、竞品和行业研究", ["market"], ["task_center.read"], 120),
    ("tianying", "天盈：商业增长中心", "市场增长军团", "商业增长、转化提升与增长方案", ["growth"], ["task_center.read"], 130),
    (TIANCAI_DATA, AI_EMPLOYEE_REGISTRY[TIANCAI_DATA].name, "数据资产军团", "数据采集、数据源接入与采集质量", ["data_collection"], ["task_center.execute"], 140),
    ("tiance_account", "天册：账号资料模板中心", "数据资产军团", "账号资料、模板与字段规范管理", ["account_template"], ["task_center.read"], 150),
    ("tiancang", "天藏：知识资产中心", "数据资产军团", "知识资产沉淀、SOP 与资料管理", ["knowledge"], ["task_center.read"], 160),
    ("tianyu", "天誉：GEO品牌增长中心", "品牌运营军团", "GEO 品牌增长、声誉和内容分发", ["brand_growth"], ["task_center.read"], 170),
    ("tianshang", "天商：商品运营中心", "电商运营军团", "商品运营、商品分析与运营动作", ["product_ops"], ["task_center.execute"], 180),
    ("tiantou", "天投：广告投放中心", "电商运营军团", "广告投放、ROI 分析与计划优化", ["ads"], ["task_center.execute"], 190),
    ("tianchuang", "天创：设计创意中心", "内容创意军团", "设计创意、图片素材与视觉优化", ["design"], ["task_center.execute"], 200),
    (TIANBO, AI_EMPLOYEE_REGISTRY[TIANBO].name, "内容创意军团", "视频脚本、剪辑任务与短视频素材", ["video"], ["task_center.execute"], 210),
    ("tianfu", "天服：客服中心", "服务保障军团", "客服、售后和退款异常分析", ["service"], ["task_center.execute"], 220),
    (TIANSHU, AI_EMPLOYEE_REGISTRY[TIANSHU].name, "数据资产军团", "经营数据分析、日报和趋势洞察", ["data_analysis"], ["task_center.execute"], 230),
    ("tiancai_finance", "天财：财务中心", "管理保障军团", "财务核算、利润和费用分析", ["finance"], ["task_center.read"], 240),
    ("tianfa", "天法：法务中心", "管理保障军团", "法务审查、合同和合规支持", ["legal"], ["task_center.read"], 250),
    ("tianan", "天安：安全中心", "管理保障军团", "安全策略、账号和系统安全", ["security"], ["task_center.read"], 260),
    ("tianzhi", "天智：AI训练中心", "AI能力军团", "AI 训练、能力评测和提示词优化", ["ai_training"], ["task_center.read"], 270),
]


PERMISSIONS.append(("menu.account_center", "账号资料中心"))
PERMISSIONS.append(("menu.computer_executor", "电脑执行中心"))
for role_code in ("owner", "admin", "operator"):
    ROLE_PERMISSIONS.setdefault(role_code, []).extend(["menu.account_center"])
for role_code in ("owner", "admin"):
    ROLE_PERMISSIONS.setdefault(role_code, []).append("menu.computer_executor")
    ROLE_PERMISSIONS.setdefault(role_code, []).extend(["computer_executor.read", "computer_executor.manage"])


def seed_defaults(db: Session):
    boss_initial_password = get_settings().BOSS_INITIAL_PASSWORD
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

    boss_user = db.query(User).filter(User.username == BOSS_USERNAME).one_or_none()
    if not boss_user:
        boss_user = User(
            username=BOSS_USERNAME,
            password_hash=hash_password(boss_initial_password),
            role="boss",
            display_name="老板",
            active=True,
        )
        db.add(boss_user)
    else:
        boss_user.role = "boss"
        boss_user.display_name = boss_user.display_name or "老板"
        boss_user.active = True
        if not verify_password(boss_initial_password, boss_user.password_hash):
            boss_user.password_hash = hash_password(boss_initial_password)

    for code, name, task in AI_EMPLOYEES:
        ai_task = db.query(AiTask).filter(AiTask.ai_employee_code == code).one_or_none()
        if not ai_task:
            db.add(AiTask(ai_employee_code=code, ai_employee_name=name, status="idle", today_task=task, execution_log=""))
        else:
            ai_task.ai_employee_name = name

    for code, name, legion, duty, task_types, default_permissions, sort_order in REAL_AI_EMPLOYEES:
        employee = db.query(AiEmployee).filter(AiEmployee.employee_code == code).one_or_none()
        if not employee:
            employee = AiEmployee(employee_code=code)
            db.add(employee)
        employee.employee_name = name
        employee.legion = legion
        employee.duty = duty
        employee.status = "active"
        employee.task_types = json.dumps(task_types, ensure_ascii=False)
        employee.default_permissions = json.dumps(default_permissions, ensure_ascii=False)
        employee.is_legacy = False
        employee.sort_order = sort_order

    db.commit()
    ensure_default_skills(db, created_by=(resolve_manager_user(db).id if resolve_manager_user(db) else None))

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
PERMISSIONS.extend([
    ("ai_employees.read", "read AI employee registry"),
    ("ai_employees.manage", "manage AI employee registry"),
])
PERMISSIONS.extend([
    ("orchestrator.read", "read AI Orchestrator"),
    ("orchestrator.analyze", "analyze AI Orchestrator replies"),
    ("orchestrator.confirm", "confirm AI Orchestrator prompts"),
])
for role_code in ("owner", "admin"):
    ROLE_PERMISSIONS.setdefault(role_code, []).extend([
        "task_center.read",
        "task_center.manage",
        "task_center.execute",
        "task_center.review",
        "task_center.audit",
        "ai_employees.read",
        "ai_employees.manage",
        "orchestrator.read",
        "orchestrator.analyze",
        "orchestrator.confirm",
        "skills.read",
        "skills.manage",
        "skills.install",
        "skills.invoke",
        "skills.audit",
    ])
