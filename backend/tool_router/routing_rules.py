from __future__ import annotations


DEFAULT_TOOL_ROUTES = [
    {"employee_code": "tiancai", "tool_name": "browser_search", "priority": 20, "risk_level": "high", "enabled": True},
    {"employee_code": "tiancai", "tool_name": "excel_analyzer", "priority": 10, "risk_level": "low", "enabled": True},
    {"employee_code": "tiancai", "tool_name": "database_read", "priority": 30, "risk_level": "low", "enabled": True},
    {"employee_code": "tiancai_data", "tool_name": "browser_search", "priority": 20, "risk_level": "high", "enabled": True},
    {"employee_code": "tiancai_data", "tool_name": "excel_analyzer", "priority": 10, "risk_level": "low", "enabled": True},
    {"employee_code": "tiancai_data", "tool_name": "database_read", "priority": 30, "risk_level": "low", "enabled": True},
    {"employee_code": "tianchuang", "tool_name": "image_reader", "priority": 10, "risk_level": "medium", "enabled": True},
    {"employee_code": "tianyu", "tool_name": "seo_analyzer", "priority": 10, "risk_level": "low", "enabled": True},
    {"employee_code": "tiancai_finance", "tool_name": "financial_reader", "priority": 10, "risk_level": "high", "enabled": True},
]


TASK_TOOL_KEYWORDS = [
    (("excel", "表格", "报表", "xlsx", "csv"), "excel_analyzer"),
    (("网页", "搜索", "联网", "市场", "趋势", "竞品", "新闻"), "browser_search"),
    (("数据库", "查询", "数据读取", "指标"), "database_read"),
    (("图片", "视觉", "素材", "设计"), "image_reader"),
    (("seo", "geo", "搜索排名", "品牌曝光"), "seo_analyzer"),
    (("财务", "成本", "利润", "收入", "费用"), "financial_reader"),
    (("api", "接口"), "api_read"),
]


def match_tool_by_text(task: str, requirement: str) -> str | None:
    text = f"{task or ''} {requirement or ''}".lower()
    for keywords, tool_name in TASK_TOOL_KEYWORDS:
        if any(keyword.lower() in text for keyword in keywords):
            return tool_name
    return None

