from __future__ import annotations

from typing import Final

ALPHA_WORKFLOW_STATUSES: Final[tuple[str, ...]] = (
    "草稿",
    "待校验",
    "运行中",
    "已暂停",
    "等待恢复",
    "已完成",
    "已失败",
)

ALPHA_WORKFLOW_EVENT_CODES: Final[tuple[str, ...]] = (
    "workflow_created",
    "workflow_started",
    "task_created",
    "task_assigned",
    "research_executed",
    "knowledge_candidate_created",
    "skill_invoked",
    "report_generated",
    "dashboard_refreshed",
    "workflow_completed",
    "workflow_failed",
    "workflow_recovered",
)

ALPHA_WORKFLOW_FEATURE_FLAGS: Final[tuple[str, ...]] = (
    "ALPHA_WORKFLOW_ENABLED",
    "ALPHA_WORKFLOW_DASHBOARD_ENABLED",
)

DEFAULT_ALPHA_SCENARIO_CODE = "apple_latest_ai_strategy"
DEFAULT_ALPHA_SCENARIO_TITLE = "研究 Apple 最新 AI 战略"
DEFAULT_ALPHA_SCENARIO_DESCRIPTION = "老板输入研究主题后，自动串联 Task Center、Research、Knowledge、Skills、Workflow 与 Dashboard 的第一次全链路验证。"
DEFAULT_ALPHA_SCENARIO_INPUT = "研究 Apple 最新 AI 战略"
DEFAULT_ALPHA_SCENARIO_INPUT_HINT = "示例：研究 Apple 最新 AI 战略"
DEFAULT_ALPHA_WORKFLOW_TARGET_EMPLOYEE = "tiancai_data"
DEFAULT_ALPHA_WORKFLOW_SKILL_CODE = "knowledge.local.search"
DEFAULT_ALPHA_WORKFLOW_QUALITY_THRESHOLD = 80
DEFAULT_ALPHA_WORKFLOW_RISK_THRESHOLD = 35
