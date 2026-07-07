from __future__ import annotations

from typing import Any


AGENT_PROFILES = {
    "tiancai_data": {
        "name": "天采",
        "role": "数据采集",
        "focus": "补齐销售、流量、商品、广告和客服数据口径。",
    },
    "tiance_strategy": {
        "name": "天策",
        "role": "策略分析",
        "focus": "判断核心矛盾、优先级和经营策略路径。",
    },
    "tianshang": {
        "name": "天商",
        "role": "商品经营",
        "focus": "优化商品结构、价格呈现、详情页和转化承接。",
    },
    "tiantou": {
        "name": "天投",
        "role": "投放检查",
        "focus": "检查广告计划、关键词、预算效率和流量质量。",
    },
    "tianjian_test": {
        "name": "天检",
        "role": "验收验证",
        "focus": "定义验收指标、回归检查和失败处理规则。",
    },
    "tian_shen": {
        "name": "天审",
        "role": "安全审批",
        "focus": "识别执行风险，确保只讨论不自动执行。",
    },
}


DEFAULT_INVITEES = ["tiancai_data", "tiance_strategy", "tianshang", "tiantou", "tianjian_test", "tian_shen"]


def build_agent_message(employee_code: str, goal: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = AGENT_PROFILES.get(employee_code) or {"name": employee_code, "role": "协作成员", "focus": "提供专业意见。"}
    context_summary = summarize_context(context or {})
    return {
        "employee_code": employee_code,
        "employee_name": profile["name"],
        "role": profile["role"],
        "analysis": f"围绕“{goal}”，{profile['name']}认为当前需要先明确{profile['focus']}",
        "suggestion": suggestion_for(employee_code, goal),
        "risk": risk_for(employee_code),
        "expected_result": expected_result_for(employee_code, goal),
        "context_summary": context_summary,
        "can_auto_execute": False,
    }


def suggestion_for(employee_code: str, goal: str) -> str:
    suggestions = {
        "tiancai_data": "先建立数据看板快照，拆出销售、转化、广告、商品和客服五类指标。",
        "tiance_strategy": "用影响程度和可控性排序，优先处理转化链路和高损耗流量。",
        "tianshang": "聚焦主推商品、价格带、卖点表达和详情页承接。",
        "tiantou": "检查异常广告计划，输出暂停、降预算或换关键词的人工审批建议。",
        "tianjian_test": "把方案拆成验收清单，要求每个动作都有指标、阈值和回滚条件。",
        "tian_shen": "会议只形成建议，任何改价、改预算、发布、部署或权限动作必须另走审批。",
    }
    return suggestions.get(employee_code, f"针对 {goal} 输出只读建议。")


def risk_for(employee_code: str) -> str:
    risks = {
        "tiancai_data": "数据口径不一致会导致误判。",
        "tiance_strategy": "策略过度激进会放大经营波动。",
        "tianshang": "商品和价格建议不得自动改线上配置。",
        "tiantou": "广告预算和投放动作不得自动修改。",
        "tianjian_test": "缺少验收阈值会导致复盘失真。",
        "tian_shen": "未审批的执行动作必须阻断。",
    }
    return risks.get(employee_code, "保持只读讨论，禁止自动执行。")


def expected_result_for(employee_code: str, goal: str) -> str:
    results = {
        "tiancai_data": "形成数据缺口和采集清单。",
        "tiance_strategy": "形成优先级排序和策略框架。",
        "tianshang": "形成商品和转化优化建议。",
        "tiantou": "形成广告检查和人工审批建议。",
        "tianjian_test": "形成验收计划。",
        "tian_shen": "形成安全边界和审批要求。",
    }
    return results.get(employee_code, f"形成 {goal} 的协作建议。")


def summarize_context(context: dict[str, Any]) -> str:
    if not context:
        return "暂无额外上下文"
    keys = sorted(str(key) for key in context.keys())
    return "已提供上下文字段：" + ", ".join(keys[:8])
