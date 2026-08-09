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
    {"key": "import", "label": "店铺与数据", "href": "/import.html", "permission": "menu.import"},
    {"key": "jd_data", "label": "经营中心", "href": "/jd-dashboard.html", "permission": "menu.jd_data"},
]


def normalize_role(role: str) -> str:
    clean = (role or "").strip()
    return ROLE_ALIASES.get(clean, clean)
