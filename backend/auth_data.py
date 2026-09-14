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
    {"key": "dashboard", "label": "经营概览", "href": "/", "permission": "menu.dashboard"},
    {"key": "stores", "label": "店铺中心", "href": "/stores.html", "permission": "menu.stores"},
    {"key": "import", "label": "数据导入", "href": "/import.html", "permission": "menu.import"},
    {"key": "jd_data", "label": "经营驾驶舱", "href": "/jd-dashboard.html", "permission": "menu.jd_data"},
    {"key": "ai_employees", "label": "AI员工", "href": "/ai-employees.html", "permission": "menu.ai_employees"},
    {"key": "computer_executor", "label": "电脑执行", "href": "/computer-execution-center.html", "permission": "menu.computer_executor"},
    {"key": "settings", "label": "系统设置", "href": "/settings.html", "permission": "menu.settings"},
]


def normalize_role(role: str) -> str:
    clean = (role or "").strip()
    return ROLE_ALIASES.get(clean, clean)
