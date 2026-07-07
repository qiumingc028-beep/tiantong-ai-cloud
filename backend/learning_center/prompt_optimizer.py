from __future__ import annotations

from typing import Any


def optimize_prompt_suggestions(analysis: dict[str, Any], scores: list[dict[str, Any]], logs: list[dict[str, Any]]) -> dict[str, Any]:
    failed_cases = [row for row in logs if str(row.get("status") or "").lower() in {"failed", "error"}]
    risky_cases = [row for row in logs if str(row.get("risk_decision") or "").upper() in {"YELLOW", "RED"}]
    lessons = extract_lessons(analysis, scores, failed_cases, risky_cases)
    suggestions = build_suggestions(analysis, failed_cases, risky_cases)
    return {
        "failed_case_count": len(failed_cases),
        "risky_case_count": len(risky_cases),
        "lessons": lessons,
        "optimization_suggestions": suggestions,
        "prompt_update_mode": "suggestion_only",
        "requires_tian_shen_approval": True,
        "can_auto_update_prompt": False,
        "can_modify_production_prompt": False,
        "safety_notes": "天悟只生成 Prompt 优化建议；生产 Prompt 更新必须另走 TianShen Approval Center。",
    }


def extract_lessons(
    analysis: dict[str, Any],
    scores: list[dict[str, Any]],
    failed_cases: list[dict[str, Any]],
    risky_cases: list[dict[str, Any]],
) -> list[str]:
    lessons = []
    if failed_cases:
        lessons.append("失败步骤需要在 Prompt 中要求补充输入字段、异常处理和验收标准。")
    if risky_cases:
        lessons.append("命中 YELLOW/RED 的步骤需要在 Prompt 中提前声明安全边界和审批条件。")
    low_score = [row for row in scores if row.get("overall_score", 0) < 70]
    if low_score:
        lessons.append("低分员工需要更明确的角色边界、输出格式和检查清单。")
    if analysis.get("completion_rate") == 1:
        lessons.append("成功执行链路可沉淀为 SOP 示例和 Prompt 正例。")
    return lessons or ["暂无明显失败模式，建议继续积累执行样本。"]


def build_suggestions(analysis: dict[str, Any], failed_cases: list[dict[str, Any]], risky_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions = [
        {
            "suggestion_code": "add_output_contract",
            "title": "补充结构化输出契约",
            "reason": "让每个 AI 员工输出目标、依据、风险、下一步。",
            "requires_approval": True,
            "can_auto_apply": False,
        }
    ]
    if failed_cases:
        suggestions.append(
            {
                "suggestion_code": "add_failure_handling",
                "title": "补充失败处理分支",
                "reason": "失败案例显示当前任务需要明确异常输入和回滚说明。",
                "requires_approval": True,
                "can_auto_apply": False,
            }
        )
    if risky_cases or analysis.get("risk_steps", 0):
        suggestions.append(
            {
                "suggestion_code": "add_safety_gate",
                "title": "补充 TianShen 审批门说明",
                "reason": "风险步骤必须先输出审批建议，不能直接执行。",
                "requires_approval": True,
                "can_auto_apply": False,
            }
        )
    return suggestions
