from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db


router = APIRouter()

PRIVILEGED_ROLES = {"owner", "admin"}


def safe_text(value, fallback: str = "暂无") -> str:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, dict):
        for key in ("name", "code", "title", "summary", "description"):
            if key in value:
                return safe_text(value.get(key), fallback)
        return fallback
    if isinstance(value, (list, tuple, set)):
        values = safe_text_list(value)
        return "、".join(values) if values else fallback
    return fallback


def safe_text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            if isinstance(item, (list, tuple, set)):
                result.extend(safe_text_list(item))
            else:
                text = safe_text(item, "")
                if text:
                    result.append(text)
        return result
    text = safe_text(value, "")
    return [text] if text else []


def require_sop_skill_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in PRIVILEGED_ROLES:
        raise HTTPException(status_code=403, detail="no sop skill center permission")
    return user


def make_sop(
    code: str,
    name: str,
    department: str,
    task_types: list[str],
    owner: str,
    confirm: bool,
    test: bool,
    audit: bool,
    deploy: bool,
) -> dict:
    return {
        "sop_code": safe_text(code),
        "sop_name": safe_text(name),
        "department": safe_text(department),
        "task_types": safe_text_list(task_types),
        "description": f"{name} 的只读流程档案，用于展示推荐步骤和验收边界。",
        "steps_summary": ["确认任务来源", "核对输入材料", "按规则产出草稿", "提交人工确认链路"],
        "required_inputs": ["task_id", "task_type", "employee_code"],
        "expected_outputs": ["执行摘要", "风险提示", "下一步建议"],
        "acceptance_rules": ["结果必须可追溯", "高风险任务必须人工确认"],
        "safety_rules": ["不自动执行", "不修改状态", "不调用外部工具"],
        "owner_employee": safe_text(owner),
        "required_roles": ["boss", "owner", "admin"],
        "requires_boss_confirmation": bool(confirm),
        "requires_test_acceptance": bool(test),
        "requires_security_audit": bool(audit),
        "requires_deploy_review": bool(deploy),
        "can_auto_execute": False,
        "current_status": "readonly_configured",
        "next_upgrade_suggestion": "后续可接入版本号和执行记录，但仍需保持人工确认边界。",
    }


def make_skill(
    code: str,
    name: str,
    category: str,
    employees: list[str],
    task_types: list[str],
    tools: list[str],
    models: list[str],
    level: str,
    confirm: bool,
    test: bool,
    audit: bool,
) -> dict:
    return {
        "skill_code": safe_text(code),
        "skill_name": safe_text(name),
        "skill_category": safe_text(category),
        "description": f"{name} 的只读能力绑定档案。",
        "suitable_employees": safe_text_list(employees),
        "suitable_task_types": safe_text_list(task_types),
        "required_tools": safe_text_list(tools),
        "forbidden_tools": ["payment", "billing", "credential_management"],
        "recommended_models": safe_text_list(models),
        "safety_level": safe_text(level),
        "requires_boss_confirmation": bool(confirm),
        "requires_test_acceptance": bool(test),
        "requires_security_audit": bool(audit),
        "can_auto_execute": False,
        "current_status": "readonly_configured",
        "next_upgrade_suggestion": "后续接入能力评分和 SOP 执行覆盖率。",
    }


SOPS = [
    make_sop("sop_product_design", "产品设计验收 SOP", "AI产品经理中心", ["product_design"], "tiandao", True, True, False, False),
    make_sop("sop_architecture_design", "系统架构评审 SOP", "系统架构中心", ["architecture_design"], "tiangong", True, True, True, False),
    make_sop("sop_backend_coding", "后端开发交付 SOP", "后端开发中心", ["backend_coding"], "tianwang", True, True, True, False),
    make_sop("sop_frontend_integration", "前端联调验收 SOP", "前端联调优化", ["frontend_coding"], "tianyan_frontend", True, True, False, False),
    make_sop("sop_testing_acceptance", "天检测试验收 SOP", "测试验收中心", ["testing_acceptance"], "tianjian_test", False, True, False, False),
    make_sop("sop_security_audit", "天监安全审计 SOP", "AI审计中心", ["security_audit"], "tianjian_audit", False, True, True, False),
    make_sop("sop_deploy_validation", "天盾部署验证 SOP", "部署运维修复", ["deployment_ops"], "tiandun_ops", True, True, True, True),
    make_sop("sop_ecommerce_operation", "电商运营分析 SOP", "商品中心", ["ecommerce_operation"], "tianshang", True, False, True, False),
    make_sop("sop_data_analysis", "数据分析报告 SOP", "数据分析中心", ["data_analysis"], "tianshu", False, True, False, False),
    make_sop("sop_supplier_search", "供应链找厂 SOP", "供应链找厂中心", ["supplier_search"], "tianlian", True, False, True, False),
]

SKILLS = [
    make_skill("skill_product_planning", "产品规划", "planning", ["tiandao", "tiantong"], ["product_design"], ["report_generation"], ["gpt-5-5-thinking"], "medium", True, True, False),
    make_skill("skill_architecture_review", "架构评审", "architecture", ["tiangong"], ["architecture_design"], ["code_editor"], ["claude", "gpt-5-5-thinking"], "high", True, True, True),
    make_skill("skill_backend_patch_review", "后端补丁评审", "coding", ["tianwang"], ["backend_coding"], ["github", "test_runner"], ["codex"], "high", True, True, True),
    make_skill("skill_frontend_quality", "前端质量联调", "frontend", ["tianyan_frontend"], ["frontend_coding"], ["browser_view", "test_runner"], ["codex"], "medium", True, True, False),
    make_skill("skill_acceptance_check", "测试验收", "testing", ["tianjian_test"], ["testing_acceptance"], ["test_runner"], ["gpt-5-5"], "medium", False, True, False),
    make_skill("skill_security_review", "安全审计", "audit", ["tianjian_audit"], ["security_audit"], ["github"], ["claude"], "high", False, True, True),
    make_skill("skill_deploy_validation", "部署验证", "deploy", ["tiandun_ops"], ["deployment_ops"], ["deploy_center"], ["gpt-5-5"], "critical", True, True, True),
    make_skill("skill_market_analysis", "市场分析", "ecommerce", ["tianshang", "tianshu"], ["ecommerce_operation", "data_analysis"], ["report_generation"], ["gemini"], "medium", True, False, True),
]

PROMPTS = [
    {
        "prompt_code": "prompt_product_design_summary",
        "prompt_name": "产品设计摘要模板",
        "task_type": "product_design",
        "employee_code": "tiandao",
        "template_content_summary": "要求输出目标、用户场景、页面模块、安全边界和验收标准。",
        "required_variables": ["task_title", "business_goal", "safety_boundary"],
        "output_format": "结构化 Markdown 摘要",
        "safety_notes": ["只返回模板摘要", "不返回完整模板正文"],
        "forbidden_content": ["敏感凭证", "外部账号资料", "完整执行命令"],
        "current_status": "readonly_configured",
        "next_upgrade_suggestion": "增加模板版本和适用 Sprint 范围。",
    },
    {
        "prompt_code": "prompt_backend_fix_review",
        "prompt_name": "后端修复复核模板",
        "task_type": "backend_coding",
        "employee_code": "tianwang",
        "template_content_summary": "要求输出修复范围、接口变化、权限边界、只读检查和测试结果。",
        "required_variables": ["commit_id", "changed_files", "api_paths"],
        "output_format": "修复报告清单",
        "safety_notes": ["不包含 Prompt 原文", "不包含敏感字段"],
        "forbidden_content": ["真实密钥", "数据库连接", "外部登录信息"],
        "current_status": "readonly_configured",
        "next_upgrade_suggestion": "绑定测试验收 SOP。",
    },
    {
        "prompt_code": "prompt_deploy_validation",
        "prompt_name": "部署验证模板",
        "task_type": "deployment_ops",
        "employee_code": "tiandun_ops",
        "template_content_summary": "要求输出同步、构建、路由、健康检查、页面检查和日志检查结果。",
        "required_variables": ["commit_id", "page_path", "api_prefix"],
        "output_format": "部署验证报告",
        "safety_notes": ["只展示命令类别和验证项", "不展示服务器敏感配置"],
        "forbidden_content": ["完整环境变量", "外部凭证", "未脱敏日志"],
        "current_status": "readonly_configured",
        "next_upgrade_suggestion": "接入部署追溯中心。",
    },
]

EMPLOYEE_BINDINGS = [
    ("tiantong", "天统：AI总指挥", "AI总指挥", ["sop_product_design", "sop_architecture_design"], ["skill_product_planning"], ["prompt_product_design_summary"], ["gpt-5-5-thinking"], ["report_generation"], ["payment"], True, True, True, False, []),
    ("tiandao", "天道：AI产品经理中心", "AI产品经理中心", ["sop_product_design"], ["skill_product_planning"], ["prompt_product_design_summary"], ["gpt-5-5-thinking"], ["report_generation", "copywriting"], ["deploy_center"], True, True, False, False, []),
    ("tiangong", "天工：系统架构中心", "系统架构中心", ["sop_architecture_design"], ["skill_architecture_review"], [], ["claude"], ["code_editor"], ["payment"], True, True, True, False, ["prompt_template"]),
    ("tianwang", "天王：后端开发中心", "后端开发中心", ["sop_backend_coding"], ["skill_backend_patch_review"], ["prompt_backend_fix_review"], ["codex"], ["github", "test_runner"], ["payment"], True, True, True, False, []),
    ("tianyan_frontend", "天颜：前端联调优化", "前端联调优化", ["sop_frontend_integration"], ["skill_frontend_quality"], [], ["codex"], ["browser_view", "test_runner"], ["browser_click"], True, True, False, False, ["prompt_template"]),
    ("tianjian_test", "天检：测试验收中心", "测试验收中心", ["sop_testing_acceptance"], ["skill_acceptance_check"], [], ["gpt-5-5"], ["test_runner"], ["deploy_center"], False, True, False, False, ["prompt_template"]),
    ("tianjian_audit", "天监：AI审计中心", "AI审计中心", ["sop_security_audit"], ["skill_security_review"], [], ["claude"], ["github"], ["payment"], False, True, True, False, ["prompt_template"]),
    ("tiandun_ops", "天盾：部署运维修复", "部署运维修复", ["sop_deploy_validation"], ["skill_deploy_validation"], ["prompt_deploy_validation"], ["gpt-5-5"], ["deploy_center"], ["payment"], True, True, True, True, []),
    ("tianshang", "天商：商品中心", "商品中心", ["sop_ecommerce_operation"], ["skill_market_analysis"], [], ["gemini"], ["report_generation"], ["payment"], True, False, True, False, ["prompt_template"]),
    ("tianshu", "天数：数据分析中心", "数据分析中心", ["sop_data_analysis"], ["skill_market_analysis"], [], ["gemini"], ["report_generation"], ["payment"], False, True, False, False, ["prompt_template"]),
    ("tianlian", "天链：供应链找厂中心", "供应链找厂中心", ["sop_supplier_search"], [], [], ["gpt-5-5"], ["supplier_1688_search"], ["payment"], True, False, True, False, ["skill", "prompt_template"]),
]

TASK_TYPE_BINDINGS = [
    ("product_design", "产品设计", "tiandao", "sop_product_design", "skill_product_planning", "prompt_product_design_summary", "gpt-5-5-thinking", ["report_generation"], ["deploy_center"], ["boss_confirm", "test_acceptance"], "medium", True, True, False, False),
    ("architecture_design", "架构设计", "tiangong", "sop_architecture_design", "skill_architecture_review", "", "claude", ["code_editor"], ["payment"], ["boss_confirm", "test_acceptance", "security_audit"], "high", True, True, True, False),
    ("backend_coding", "后端开发", "tianwang", "sop_backend_coding", "skill_backend_patch_review", "prompt_backend_fix_review", "codex", ["github", "test_runner"], ["payment"], ["boss_confirm", "test_acceptance", "security_audit"], "high", True, True, True, False),
    ("frontend_coding", "前端开发", "tianyan_frontend", "sop_frontend_integration", "skill_frontend_quality", "", "codex", ["browser_view", "test_runner"], ["browser_click"], ["boss_confirm", "test_acceptance"], "medium", True, True, False, False),
    ("deployment_ops", "部署运维", "tiandun_ops", "sop_deploy_validation", "skill_deploy_validation", "prompt_deploy_validation", "gpt-5-5", ["deploy_center"], ["payment"], ["boss_confirm", "test_acceptance", "security_audit", "deploy_review"], "critical", True, True, True, True),
]


def employee_binding(row: tuple) -> dict:
    (
        code,
        name,
        department,
        sops,
        skills,
        prompts,
        models,
        allowed,
        forbidden,
        confirm,
        test,
        audit,
        deploy,
        missing,
    ) = row
    return {
        "employee_code": safe_text(code),
        "employee_name": safe_text(name),
        "department": safe_text(department),
        "bound_sops": safe_text_list(sops),
        "bound_skills": safe_text_list(skills),
        "bound_prompt_templates": safe_text_list(prompts),
        "recommended_models": safe_text_list(models),
        "allowed_tools": safe_text_list(allowed),
        "forbidden_tools": safe_text_list(forbidden),
        "requires_boss_confirmation": bool(confirm),
        "requires_test_acceptance": bool(test),
        "requires_security_audit": bool(audit),
        "requires_deploy_review": bool(deploy),
        "safety_rules": ["不自动执行", "不返回完整模板正文", "不越权调用工具"],
        "can_auto_execute": False,
        "missing_bindings": safe_text_list(missing),
        "next_upgrade_suggestion": "补齐缺失绑定后再进入自动化候选评估。" if missing else "保持只读展示并补充执行记录。",
    }


def task_type_binding(row: tuple) -> dict:
    (
        task_type,
        name,
        employee,
        sop,
        skill,
        prompt,
        model,
        tools,
        forbidden,
        flow,
        level,
        confirm,
        test,
        audit,
        deploy,
    ) = row
    return {
        "task_type": safe_text(task_type),
        "task_type_name": safe_text(name),
        "recommended_employee": safe_text(employee),
        "recommended_sop": safe_text(sop),
        "recommended_skill": safe_text(skill),
        "recommended_prompt": safe_text(prompt),
        "recommended_model": safe_text(model),
        "recommended_tools": safe_text_list(tools),
        "forbidden_tools": safe_text_list(forbidden),
        "required_acceptance_flow": safe_text_list(flow),
        "safety_level": safe_text(level),
        "requires_boss_confirmation": bool(confirm),
        "requires_test_acceptance": bool(test),
        "requires_security_audit": bool(audit),
        "requires_deploy_review": bool(deploy),
        "can_auto_execute": False,
        "next_upgrade_suggestion": "后续可与 Task Center 的 task_type 做只读联动。",
    }


def employee_bindings() -> list[dict]:
    return [employee_binding(row) for row in EMPLOYEE_BINDINGS]


def task_type_bindings() -> list[dict]:
    return [task_type_binding(row) for row in TASK_TYPE_BINDINGS]


def department_bindings() -> list[dict]:
    departments: dict[str, dict[str, set[str]]] = {}
    for employee in employee_bindings():
        department = employee["department"]
        data = departments.setdefault(
            department,
            {
                "bound_sops": set(),
                "bound_skills": set(),
                "bound_prompt_templates": set(),
                "recommended_models": set(),
                "allowed_tools": set(),
                "forbidden_tools": set(),
                "missing_bindings": set(),
            },
        )
        for key in data:
            for value in employee.get(key, []):
                data[key].add(value)
    return [
        {
            "department": department,
            "department_name": department,
            "bound_sops": sorted(values["bound_sops"]),
            "bound_skills": sorted(values["bound_skills"]),
            "bound_prompt_templates": sorted(values["bound_prompt_templates"]),
            "recommended_models": sorted(values["recommended_models"]),
            "allowed_tools": sorted(values["allowed_tools"]),
            "forbidden_tools": sorted(values["forbidden_tools"]),
            "required_acceptance_flow": ["boss_confirm", "test_acceptance"],
            "safety_level": "medium",
            "missing_bindings": sorted(values["missing_bindings"]),
            "next_upgrade_suggestion": "按部门补齐 SOP / Skill / Prompt 绑定覆盖率。",
        }
        for department, values in sorted(departments.items())
    ]


def acceptance_rules() -> list[dict]:
    return [
        {
            "rule_code": "accept_backend_change",
            "rule_name": "后端变更验收规则",
            "task_type": "backend_coding",
            "department": "后端开发中心",
            "required_checker": "tianjian_test",
            "requires_boss_confirmation": True,
            "requires_test_acceptance": True,
            "requires_security_audit": True,
            "requires_deploy_review": False,
            "acceptance_steps": ["py_compile", "route_check", "permission_check", "schema_check"],
            "failure_handling": "退回修复并重新验收",
            "current_status": "active",
        },
        {
            "rule_code": "accept_deploy_change",
            "rule_name": "部署变更验收规则",
            "task_type": "deployment_ops",
            "department": "部署运维修复",
            "required_checker": "tiandun_ops",
            "requires_boss_confirmation": True,
            "requires_test_acceptance": True,
            "requires_security_audit": True,
            "requires_deploy_review": True,
            "acceptance_steps": ["commit_check", "container_check", "api_check", "log_check"],
            "failure_handling": "停止上线并回到部署验证",
            "current_status": "active",
        },
    ]


def security_rules() -> list[dict]:
    return [
        {
            "rule_code": "security_no_auto_execute",
            "rule_name": "禁止自动执行规则",
            "scope": "all",
            "forbidden_actions": ["auto_dispatch", "auto_deploy", "auto_code_submission", "auto_tool_call"],
            "sensitive_fields": ["credential", "connection_string", "private_material"],
            "requires_boss_confirmation": True,
            "can_auto_execute": False,
            "safety_level": "critical",
            "current_status": "active",
        },
        {
            "rule_code": "security_prompt_summary_only",
            "rule_name": "模板摘要展示规则",
            "scope": "prompt_templates",
            "forbidden_actions": ["return_full_template", "return_sensitive_context"],
            "sensitive_fields": ["full_template_body", "source_material"],
            "requires_boss_confirmation": False,
            "can_auto_execute": False,
            "safety_level": "high",
            "current_status": "active",
        },
    ]


def missing_bindings() -> list[dict]:
    rows = []
    for employee in employee_bindings():
        for missing in employee["missing_bindings"]:
            rows.append(
                {
                    "target_type": "employee",
                    "target_code": employee["employee_code"],
                    "target_name": employee["employee_name"],
                    "missing_type": missing,
                    "missing_fields": [missing],
                    "severity": "medium",
                    "suggestion": "补齐绑定后再进入下一阶段联动。",
                }
            )
    return rows


def next_upgrades() -> list[dict]:
    return [
        {
            "upgrade_code": "sprint14_binding_quality",
            "upgrade_name": "绑定质量评分",
            "target_sprint": "Sprint 14",
            "description": "统计 SOP / Skill 覆盖率与任务执行质量。",
            "depends_on": ["Sprint 13"],
            "risk_level": "medium",
            "requires_boss_confirmation": True,
            "can_auto_execute": False,
        },
        {
            "upgrade_code": "sprint15_rule_recommendation",
            "upgrade_name": "规则推荐增强",
            "target_sprint": "Sprint 15",
            "description": "根据任务类型推荐 SOP / Skill / Prompt 组合，但仍不自动执行。",
            "depends_on": ["Sprint 13", "Sprint 14"],
            "risk_level": "high",
            "requires_boss_confirmation": True,
            "can_auto_execute": False,
        },
    ]


def not_found(kind: str, code: str):
    raise HTTPException(status_code=404, detail={"error": "not_found", "kind": kind, "code": safe_text(code)})


@router.get("/overview")
def get_sop_skill_overview(request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    employees = employee_bindings()
    task_types = task_type_bindings()
    departments = department_bindings()
    return {
        "total_sops": len(SOPS),
        "total_skills": len(SKILLS),
        "total_prompt_templates": len(PROMPTS),
        "bound_employee_count": len(employees),
        "bound_task_type_count": len(task_types),
        "department_binding_count": len(departments),
        "boss_confirmation_rule_count": sum(1 for row in task_types if row["requires_boss_confirmation"]),
        "test_acceptance_rule_count": sum(1 for row in task_types if row["requires_test_acceptance"]),
        "security_audit_rule_count": sum(1 for row in task_types if row["requires_security_audit"]),
        "deploy_required_rule_count": sum(1 for row in task_types if row["requires_deploy_review"]),
        "auto_execute_disabled_count": len(SOPS) + len(SKILLS) + len(task_types),
        "missing_binding_count": len(missing_bindings()),
    }


@router.get("/sops")
def get_sop_skill_sops(request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    return {"sops": SOPS}


@router.get("/sops/{sop_code}")
def get_sop_skill_sop(sop_code: str, request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    sop = next((row for row in SOPS if row["sop_code"] == sop_code), None)
    if not sop:
        not_found("sop", sop_code)
    return sop


@router.get("/skills")
def get_sop_skill_skills(request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    return {"skills": SKILLS}


@router.get("/skills/{skill_code}")
def get_sop_skill_skill(skill_code: str, request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    skill = next((row for row in SKILLS if row["skill_code"] == skill_code), None)
    if not skill:
        not_found("skill", skill_code)
    return skill


@router.get("/prompts")
def get_sop_skill_prompts(request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    return {"prompts": PROMPTS}


@router.get("/prompts/{prompt_code}")
def get_sop_skill_prompt(prompt_code: str, request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    prompt = next((row for row in PROMPTS if row["prompt_code"] == prompt_code), None)
    if not prompt:
        not_found("prompt", prompt_code)
    return prompt


@router.get("/employees")
def get_sop_skill_employees(request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    return {"employees": employee_bindings()}


@router.get("/employees/{employee_code}")
def get_sop_skill_employee(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    employee = next((row for row in employee_bindings() if row["employee_code"] == employee_code), None)
    if not employee:
        not_found("employee", employee_code)
    return employee


@router.get("/task-types")
def get_sop_skill_task_types(request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    return {"task_types": task_type_bindings()}


@router.get("/departments")
def get_sop_skill_departments(request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    return {"departments": department_bindings()}


@router.get("/acceptance-rules")
def get_sop_skill_acceptance_rules(request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    return {"acceptance_rules": acceptance_rules()}


@router.get("/security-rules")
def get_sop_skill_security_rules(request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    return {"security_rules": security_rules()}


@router.get("/missing-bindings")
def get_sop_skill_missing_bindings(request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    return {"missing_bindings": missing_bindings()}


@router.get("/next-upgrades")
def get_sop_skill_next_upgrades(request: Request, db: Session = Depends(get_db)):
    require_sop_skill_user(request, db)
    return {"next_upgrades": next_upgrades()}
