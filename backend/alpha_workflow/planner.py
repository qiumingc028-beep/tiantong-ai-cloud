from __future__ import annotations

from uuid import uuid4

from .constants import (
    DEFAULT_ALPHA_SCENARIO_CODE,
    DEFAULT_ALPHA_SCENARIO_DESCRIPTION,
    DEFAULT_ALPHA_SCENARIO_INPUT_HINT,
    DEFAULT_ALPHA_SCENARIO_TITLE,
)
from .context import AlphaWorkflowPlan, AlphaWorkflowPlanStep


def build_alpha_workflow_plan(input_text: str, *, scenario_code: str | None = None, trace_id: str | None = None) -> AlphaWorkflowPlan:
    topic = input_text.strip() or DEFAULT_ALPHA_SCENARIO_TITLE
    return AlphaWorkflowPlan(
        scenario_code=scenario_code or DEFAULT_ALPHA_SCENARIO_CODE,
        title=DEFAULT_ALPHA_SCENARIO_TITLE,
        description=DEFAULT_ALPHA_SCENARIO_DESCRIPTION,
        input_hint=DEFAULT_ALPHA_SCENARIO_INPUT_HINT,
        trace_id=trace_id or uuid4().hex,
        steps=[
            AlphaWorkflowPlanStep(
                step_code="task_create",
                title="Task Center 创建任务",
                description="由老板输入形成任务条目，进入任务中心。",
                expected_result="生成可追踪的任务记录",
                module="Task Center",
                risk_level="低",
            ),
            AlphaWorkflowPlanStep(
                step_code="orchestrator_dispatch",
                title="Orchestrator 自动派给天采",
                description="将任务分配给天采，建立统一上下文。",
                expected_result="任务进入已分配状态",
                module="Orchestrator",
                risk_level="低",
            ),
            AlphaWorkflowPlanStep(
                step_code="research_execute",
                title="Research 执行",
                description="执行多来源公开信息研究，产出结构化研究结果。",
                expected_result="生成研究执行记录和证据链",
                module="Research",
                risk_level="低",
            ),
            AlphaWorkflowPlanStep(
                step_code="knowledge_candidate",
                title="Knowledge 生成候选",
                description="将研究报告沉淀为知识候选。",
                expected_result="形成知识草稿和版本",
                module="Knowledge Center",
                risk_level="低",
            ),
            AlphaWorkflowPlanStep(
                step_code="skill_retrieve",
                title="Skills 调用知识检索",
                description="通过 Skills Engine 调用已发布知识检索技能。",
                expected_result="生成检索调用记录",
                module="Skills Engine",
                risk_level="低",
            ),
            AlphaWorkflowPlanStep(
                step_code="final_report",
                title="生成最终研究报告",
                description="汇总研究、知识与技能结果，形成最终报告。",
                expected_result="产出完整中文报告",
                module="Workflow",
                risk_level="低",
            ),
            AlphaWorkflowPlanStep(
                step_code="dashboard_refresh",
                title="老板驾驶舱展示结果",
                description="将最终结果回写老板驾驶舱和 Alpha 页面。",
                expected_result="dashboard 可查看链路结果",
                module="Dashboard",
                risk_level="低",
            ),
        ],
    )
