from __future__ import annotations

from typing import Any


def build_consensus(goal: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    core_actions = [
        "先由天采补齐经营数据和异常证据",
        "再由天策判断主因与策略优先级",
        "天商输出商品和转化承接建议",
        "天投输出广告检查和人工审批建议",
        "天检定义验收指标和复盘规则",
        "天审确认任何执行动作必须另走审批",
    ]
    risk_summary = [message["risk"] for message in messages if message.get("risk")]
    return {
        "goal": goal,
        "final_consensus": f"围绕“{goal}”，AI会议共识是先诊断、再排序、后审批执行，当前阶段只形成建议。",
        "agreed_actions": core_actions,
        "risk_summary": risk_summary,
        "approval_required": True,
        "recommended_next_step": "提交老板审批后，再由 Command Center 创建正式任务流。",
        "can_auto_execute": False,
        "can_modify_data": False,
        "can_call_external_tool": False,
        "can_spend_budget": False,
    }
