from __future__ import annotations

from typing import Any


DEFAULT_COMMAND_TEAM = (
    ("tiancai_data", "collect_context", "data_collection"),
    ("tiance_strategy", "make_strategy", "strategy_planning"),
    ("tianchuang", "create_assets", "creative_design"),
    ("tianshang", "commerce_plan", "ecommerce_operation"),
    ("tianjian_test", "acceptance_check", "quality_acceptance"),
    ("tiandun_ops", "ops_safety_check", "ops_safety_review"),
)

JD_SALES_DECLINE_TEAM = (
    ("tiancai_data", "fetch_sales_data", "jd_sales_collection"),
    ("tiance_strategy", "analyze_decline_strategy", "sales_decline_analysis"),
    ("tianshang", "optimize_products", "product_optimization"),
    ("tiantou", "check_ads", "ad_performance_check"),
    ("tianjian_test", "validate_result", "quality_acceptance"),
)


def parse_command(command: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    cleaned = (command or "").strip()
    if not cleaned:
        raise ValueError("command is required")
    task_type = infer_task_type(cleaned)
    context = {
        "original_command": cleaned,
        "metadata": metadata or {},
        "task_type": task_type,
    }
    team = command_team_for(cleaned, task_type)
    steps = [
        {
            "step_id": index + 1,
            "employee_code": employee,
            "role": role,
            "task_type": employee_task_type,
            "input": {
                **context,
                "upstream": "previous_step_result",
                "expected_output": expected_output(role),
            },
        }
        for index, (employee, role, employee_task_type) in enumerate(team)
    ]
    return {
        "command": cleaned,
        "task_type": task_type,
        "flow": "input_parse_allocate_approve_execute_feedback",
        "steps": steps,
        "safety": {
            "requires_orchestrator": True,
            "requires_tian_shen": True,
            "uses_tian_brain": True,
            "uses_redis_queue": True,
        },
    }


def infer_task_type(command: str) -> str:
    text = command.lower()
    if ("京东" in command or "jd" in text) and any(keyword in command for keyword in ["销量下降", "下降", "销量", "60店", "60 店"]):
        return "jd_sales_decline_diagnosis"
    if any(keyword in text for keyword in ["电商", "订单", "商品", "利润", "price", "sku", "ecommerce"]):
        return "ecommerce_business_command"
    if any(keyword in text for keyword in ["内容", "视频", "小红书", "脚本", "流量", "content", "video"]):
        return "content_growth_command"
    if any(keyword in text for keyword in ["部署", "上线", "运维", "deploy", "release"]):
        return "deploy_validation_command"
    return "business_growth_command"


def command_team_for(command: str, task_type: str) -> tuple[tuple[str, str, str], ...]:
    if task_type == "jd_sales_decline_diagnosis":
        return JD_SALES_DECLINE_TEAM
    return DEFAULT_COMMAND_TEAM


def expected_output(role: str) -> str:
    return {
        "collect_context": "结构化输入、数据线索和约束条件",
        "make_strategy": "策略方案、优先级和风险控制",
        "create_assets": "创意方向、素材建议和页面/内容结构",
        "commerce_plan": "商品、定价、转化和经营建议",
        "fetch_sales_data": "京东门店销量、订单和渠道数据",
        "analyze_decline_strategy": "销量下降原因、影响因素和策略建议",
        "optimize_products": "商品结构、价格、库存和详情页优化建议",
        "check_ads": "广告投放、预算和关键词表现检查",
        "acceptance_check": "验收结论、问题清单和回归建议",
        "ops_safety_check": "部署/运维安全边界和执行前检查",
    }.get(role, "结构化执行结果")
