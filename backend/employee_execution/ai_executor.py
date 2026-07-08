from __future__ import annotations

from ..tools import analyze_market_data, generate_product_report, search_market


def execute_tian_shang_plan(goal: str, plan: dict) -> dict:
    market_data = search_market(goal)
    analysis = analyze_market_data(market_data)
    report = generate_product_report(goal, market_data, analysis)
    return {
        "employee_id": "tianshang",
        "employee_name": "天商：商品中心",
        "status": "completed",
        "goal": goal,
        "plan": plan,
        "tool_results": {
            "market_search": market_data,
            "data_analysis": analysis,
            "report_generator": report,
        },
        "report": report,
        "external_actions": [],
        "mode": "safe_internal_execution_mvp",
    }
