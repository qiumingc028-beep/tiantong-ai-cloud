ROLE_ALIASES = {
    "boss": "owner",
    "owner": "owner",
    "admin": "admin",
    "administrator": "admin",
    "operator": "operator",
    "ads": "operator",
    "service": "customer_service",
    "customer_service": "customer_service",
    "designer": "designer",
    "editor": "editor",
    "finance": "finance",
}

ROLE_LABELS = {
    "owner": "Owner",
    "admin": "管理员",
    "operator": "运营",
    "customer_service": "客服",
    "designer": "美工",
    "editor": "剪辑",
    "finance": "财务",
}

MENU_ITEMS = [
    {"key": "dashboard", "label": "老板驾驶舱", "href": "/", "permission": "menu.dashboard"},
    {"key": "employees", "label": "员工中心", "href": "/control.html", "permission": "menu.employees"},
    {"key": "stores", "label": "店铺管理", "href": "/stores.html", "permission": "menu.stores"},
    {"key": "jd_data", "label": "京东数据中心", "href": "/jd-dashboard.html", "permission": "menu.jd_data"},
    {"key": "ads", "label": "广告中心", "href": "/ads.html", "permission": "menu.ads"},
    {"key": "metrics", "label": "今日数据录入", "href": "/metrics.html", "permission": "menu.metrics"},
    {"key": "import", "label": "Excel导入", "href": "/import.html", "permission": "menu.import"},
    {"key": "ai_assets", "label": "AI素材中心", "href": "/ai-assets.html", "permission": "menu.ai_assets"},
    {"key": "tiancang", "label": "天藏：知识资产中心", "href": "/tiancang.html", "permission": "menu.tiancang"},
    {"key": "workflows", "label": "AI工作流", "href": "/workflows.html", "permission": "menu.workflows"},
    {"key": "ai_employees", "label": "AI员工管理", "href": "/ai-employees.html", "permission": "menu.ai_employees"},
    {"key": "settings", "label": "系统设置", "href": "/settings.html", "permission": "menu.settings"},
]


def normalize_role(role: str) -> str:
    clean = (role or "").strip()
    return ROLE_ALIASES.get(clean, clean)


MENU_ITEMS.insert(-1, {"key": "account_center", "label": "账号资料中心", "href": "/account-center.html", "permission": "menu.account_center"})
MENU_ITEMS.insert(-1, {"key": "knowledge_center", "label": "天藏知识资产中心", "href": "/knowledge-asset-center.html", "permission": "menu.knowledge_center"})
