from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from ..tool_center.gateway import clean_text
from ..tool_router.router_engine import route_tool
from .models import BrainExecutionLog
from .schemas import TaskIntent


EMPLOYEE_RULES = [
    {
        "employee_code": "tiancai",
        "employee_role": "数据采集中心",
        "keywords": ("采集", "搜索", "网页", "市场", "趋势", "竞品", "数据", "报表", "excel"),
        "task_type": "data_research",
    },
    {
        "employee_code": "tiance_strategy",
        "employee_role": "策略分析中心",
        "keywords": ("策略", "方案", "增长", "利润", "推广", "经营", "决策"),
        "task_type": "strategy_analysis",
    },
    {
        "employee_code": "tianchuang",
        "employee_role": "视觉创意中心",
        "keywords": ("图片", "视觉", "素材", "设计", "海报"),
        "task_type": "creative_analysis",
    },
    {
        "employee_code": "tianyu",
        "employee_role": "SEO/GEO分析中心",
        "keywords": ("seo", "geo", "搜索排名", "品牌曝光", "内容优化"),
        "task_type": "seo_analysis",
    },
    {
        "employee_code": "tiancai_finance",
        "employee_role": "财务分析中心",
        "keywords": ("财务", "成本", "费用", "收入", "预算"),
        "task_type": "finance_analysis",
    },
]

RISK_KEYWORDS = {
    "high": ("部署", "生产", "删库", "删除数据", "付款", "支付", "购买", "提交代码", "改权限", "shell", "docker"),
    "medium": ("联网", "浏览器", "搜索", "外部", "api", "账号", "表单"),
}


def analyze_request(request_text: str) -> dict:
    goal = clean_text(request_text)[:2000]
    employee = match_employee(goal)
    required_tools = infer_required_tools(goal)
    risk_level = infer_risk_level(goal, required_tools)
    intent = TaskIntent(
        task_id=build_task_id(goal),
        goal=goal,
        employee_code=employee["employee_code"],
        employee_role=employee["employee_role"],
        required_tools=required_tools,
        risk_level=risk_level,
        approval_required=risk_level in {"medium", "high"},
        execution_plan=build_execution_plan(goal, employee["employee_role"], required_tools),
    )
    return {
        "task_type": employee["task_type"],
        "recommended_employee": {
            "employee_code": intent.employee_code,
            "employee_role": intent.employee_role,
            "reason": f"根据任务目标匹配到{intent.employee_role}",
        },
        "required_tools": intent.required_tools,
        "risk_level": intent.risk_level,
        "approval_required": intent.approval_required,
        "task_intent": intent.model_dump(),
        "mode": "simulation",
    }


def build_plan(
    db: Session,
    request_text: str,
    task_id: str | None = None,
    employee_code: str | None = None,
    boss_confirmed: bool = False,
    security_audited: bool = False,
) -> dict:
    analysis = analyze_request(request_text)
    intent = analysis["task_intent"]
    selected_employee = clean_text(employee_code) or intent["employee_code"]
    routed_tools = []
    for tool_name in intent["required_tools"]:
        result = route_tool(
            db,
            selected_employee,
            request_text,
            tool_name,
            boss_confirmed=boss_confirmed,
            security_audited=security_audited,
        )
        routed_tools.append(
            {
                "tool_name": result.get("recommended_tool") or tool_name,
                "allowed": bool(result.get("allowed", False)),
                "risk_level": result.get("risk_level") or "unknown",
                "require_approval": bool(result.get("require_approval", True)),
                "reason": result.get("reason"),
                "mode": "simulation",
            }
        )
    plan = {
        "employee": selected_employee,
        "tools": routed_tools,
        "steps": intent["execution_plan"],
        "dry_run": True,
        "task_id": clean_text(task_id) or intent["task_id"],
        "risk_level": max_risk([intent["risk_level"], *[tool["risk_level"] for tool in routed_tools]]),
        "approval_required": any(tool["require_approval"] for tool in routed_tools) or intent["approval_required"],
        "mode": "simulation",
    }
    write_brain_log(
        db,
        request_text,
        analysis,
        selected_employee,
        {"tools": routed_tools, "steps": plan["steps"], "dry_run": True},
        "pending_approval" if plan["approval_required"] else "approved",
        "plan_generated_dry_run",
    )
    return plan


def check_approval(risk_level: str, boss_confirmed: bool = False, security_audited: bool = False) -> dict:
    risk = clean_text(risk_level).lower() or "low"
    if risk == "high":
        allowed = bool(boss_confirmed and security_audited)
        return {
            "allowed": allowed,
            "approval_status": "approved" if allowed else "blocked",
            "risk_level": "high",
            "required_confirmations": ["boss_confirmed", "security_audited"],
            "reason": "高风险任务必须老板确认和天监审核" if not allowed else "高风险双确认已通过",
            "mode": "simulation",
        }
    if risk == "medium":
        allowed = bool(boss_confirmed)
        return {
            "allowed": allowed,
            "approval_status": "approved" if allowed else "needs_boss_confirmation",
            "risk_level": "medium",
            "required_confirmations": ["boss_confirmed"],
            "reason": "中风险任务需要老板确认" if not allowed else "中风险老板确认已通过",
            "mode": "simulation",
        }
    return {
        "allowed": True,
        "approval_status": "approved",
        "risk_level": "low",
        "required_confirmations": [],
        "reason": "低风险任务允许生成 dry-run 计划",
        "mode": "simulation",
    }


def write_brain_log(
    db: Session,
    request_text: str,
    analysis_result: Any,
    recommended_employee: str | None,
    tool_selection: Any,
    approval_status: str,
    execution_result: str,
) -> BrainExecutionLog:
    row = BrainExecutionLog(
        user_request=clean_text(request_text)[:2000],
        ai_analysis_result=to_json_summary(analysis_result),
        recommended_employee=clean_text(recommended_employee)[:100],
        tool_selection=to_json_summary(tool_selection),
        approval_status=clean_text(approval_status)[:40],
        execution_result=clean_text(execution_result)[:1000],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_brain_logs(db: Session) -> list[dict]:
    rows = db.query(BrainExecutionLog).order_by(BrainExecutionLog.created_at.desc(), BrainExecutionLog.id.desc()).limit(100).all()
    return [brain_log_to_dict(row) for row in rows]


def brain_log_to_dict(row: BrainExecutionLog) -> dict:
    return {
        "id": row.id,
        "user_request": clean_text(row.user_request),
        "ai_analysis_result": parse_json(row.ai_analysis_result),
        "recommended_employee": clean_text(row.recommended_employee),
        "tool_selection": parse_json(row.tool_selection),
        "approval_status": clean_text(row.approval_status),
        "execution_result": clean_text(row.execution_result),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def match_employee(text: str) -> dict:
    lowered = text.lower()
    for row in EMPLOYEE_RULES:
        if any(keyword.lower() in lowered for keyword in row["keywords"]):
            return row
    return EMPLOYEE_RULES[1]


def infer_required_tools(text: str) -> list[str]:
    lowered = text.lower()
    tools = []
    if any(word in lowered for word in ("excel", "表格", "报表", "csv")):
        tools.append("excel_analyzer")
    if any(word in lowered for word in ("搜索", "网页", "联网", "趋势", "竞品", "市场")):
        tools.append("browser_search")
    if any(word in lowered for word in ("数据库", "查询", "指标")):
        tools.append("database_read")
    if any(word in lowered for word in ("图片", "视觉", "素材", "设计")):
        tools.append("image_reader")
    if any(word in lowered for word in ("seo", "geo", "搜索排名")):
        tools.append("seo_analyzer")
    if any(word in lowered for word in ("财务", "利润", "成本", "收入")):
        tools.append("financial_reader")
    return tools or ["excel_analyzer"]


def infer_risk_level(text: str, tools: list[str]) -> str:
    lowered = text.lower()
    if any(keyword in lowered for keyword in RISK_KEYWORDS["high"]):
        return "high"
    if any(keyword in lowered for keyword in RISK_KEYWORDS["medium"]) or "browser_search" in tools:
        return "medium"
    return "low"


def build_execution_plan(goal: str, employee_role: str, tools: list[str]) -> list[str]:
    return [
        "解析老板需求并形成标准 TaskIntent",
        f"分配候选员工角色: {employee_role}",
        f"通过 Tool Router 检查候选工具: {', '.join(tools)}",
        "生成 dry-run 执行计划并等待必要审批",
        "记录 Brain Center 与 Tool Router 联动日志",
    ]


def build_task_id(goal: str) -> str:
    digest = hashlib.sha256(goal.encode("utf-8")).hexdigest()[:12]
    return f"brain-{digest}"


def max_risk(levels: list[str]) -> str:
    order = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    return max((clean_text(level).lower() or "unknown" for level in levels), key=lambda item: order.get(item, 0))


def to_json_summary(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:4000]


def parse_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return clean_text(value)

