from __future__ import annotations


TIAN_SHANG_REQUIRED_TOOLS = ["market_search", "data_analysis", "report_generator"]


def build_tian_shang_plan(goal: str) -> dict:
    clean_goal = (goal or "").strip()[:500]
    if not clean_goal:
        raise ValueError("goal is required")
    steps = [
        {
            "step": 1,
            "name": "获取市场数据",
            "tool": "market_search",
            "instruction": f"围绕“{clean_goal}”收集类目、价格、品牌和需求信号。",
        },
        {
            "step": 2,
            "name": "分析价格区间",
            "tool": "data_analysis",
            "instruction": "汇总价格带、竞争强度和机会空位。",
        },
        {
            "step": 3,
            "name": "分析竞争品牌",
            "tool": "data_analysis",
            "instruction": "识别主流品牌、差异化卖点和风险。",
        },
        {
            "step": 4,
            "name": "输出新品建议",
            "tool": "report_generator",
            "instruction": "生成可给老板查看的商品开发建议报告。",
        },
    ]
    return {
        "employee_id": "tianshang",
        "employee_name": "天商：商品中心",
        "goal": clean_goal,
        "required_tools": list(TIAN_SHANG_REQUIRED_TOOLS),
        "steps": steps,
        "mode": "safe_internal_simulation",
    }
