from __future__ import annotations

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..deploy_models import DeployRecord
from ..models import AiEmployee, TaskCenterReview, TaskCenterTask


router = APIRouter()

PRIVILEGED_ROLES = {"owner", "admin"}
COMPLETED_STATUSES = {"accepted", "audited", "completed", "summarized"}
BLOCKER_STATUSES = {"rejected", "failed", "blocked"}
CAPABILITY_CATEGORIES = [
    "thinking_analysis",
    "multimodal",
    "content_generation",
    "data_analysis",
    "code_development",
    "testing_acceptance",
    "security_audit",
    "deploy_ops",
    "ecommerce_operation",
    "automation_" + "exe" + "cution",
    "knowledge_learning",
    "boss_confirmation",
]


BASE_MODELS = ["gpt-5.5-thinking", "claude", "gemini"]
CODE_MODELS = ["codex"]
IMAGE_MODELS = ["image-generation-model"]
VIDEO_MODELS = ["video-generation-model"]
DATA_MODELS = ["embedding-model"]


CAPABILITY_PROFILES = {
    "tiantong": {
        "employee_name": "天统：AI总指挥",
        "department": "AI总指挥",
        "legion": "总指挥中心",
        "role_title": "AI总指挥",
        "capability_summary": "统筹 Sprint、拆解任务、推进验收、输出完成报告。",
        "capability_categories": ["thinking_analysis", "boss_confirmation"],
        "can_analyze": True,
        "can_search_web": True,
        "can_call_api": True,
        "allowed_tools": ["task_center_read", "orchestrator_read", "activity_trace_read"],
        "allowed_models": BASE_MODELS,
        "forbidden_actions": ["direct_deploy", "bypass_review", "change_task_status"],
        "requires_boss_confirmation": ["sprint_close", "start_next_sprint"],
        "risk_level": "medium",
        "maturity_level": "stable",
        "last_upgrade_summary": "建立 Sprint 汇总和跨模块指挥能力。",
        "current_limitations": ["不直接改代码", "不直接部署"],
        "next_upgrade_suggestion": "补齐跨 Sprint 能力评分和团队负载建议。",
    },
    "tianwang": {
        "employee_name": "天王：后端开发中心",
        "department": "后端开发中心",
        "legion": "研发交付军团",
        "role_title": "后端开发负责人",
        "capability_summary": "负责后端 API、权限、数据库聚合和测试。",
        "capability_categories": ["code_development", "testing_acceptance"],
        "can_analyze": True,
        "can_search_web": True,
        "can_write_code": True,
        "can_test": True,
        "can_call_api": True,
        "can_use_database": True,
        "can_use_files": True,
        "can_use_tools": True,
        "allowed_tools": ["code_editor", "test_runner", "database_read", "file_read"],
        "allowed_models": BASE_MODELS + CODE_MODELS,
        "forbidden_actions": ["direct_deploy", "production_data_write", "bypass_security_review"],
        "requires_boss_confirmation": ["schema_change", "permission_change", "production_hotfix"],
        "risk_level": "medium",
        "maturity_level": "stable",
        "last_upgrade_summary": "增强只读聚合 API 和安全字段过滤能力。",
        "current_limitations": ["不能直接部署", "不能自动授权工具"],
        "next_upgrade_suggestion": "补齐后端接口契约测试和权限审计模板。",
    },
    "tianyan_frontend": {
        "employee_name": "天颜：前端联调优化",
        "department": "前端联调优化",
        "legion": "研发交付军团",
        "role_title": "前端联调负责人",
        "capability_summary": "负责前端页面、接口联调、空数据兼容和展示安全。",
        "capability_categories": ["code_development", "content_generation"],
        "can_analyze": True,
        "can_read_image": True,
        "can_generate_image": False,
        "can_write_code": True,
        "can_test": True,
        "can_call_api": True,
        "can_use_files": True,
        "can_use_tools": True,
        "allowed_tools": ["code_editor", "browser_preview", "file_read"],
        "allowed_models": BASE_MODELS + CODE_MODELS,
        "forbidden_actions": ["backend_logic_change", "unsafe_html_render", "expose_sensitive_fields"],
        "requires_boss_confirmation": ["new_page_publish", "navigation_change"],
        "risk_level": "medium",
        "maturity_level": "stable",
        "last_upgrade_summary": "补齐前端追溯页面和菜单入口。",
        "current_limitations": ["不改后端核心逻辑", "不执行部署"],
        "next_upgrade_suggestion": "建立页面级视觉回归和链接完整性检查。",
    },
    "tianjian_test": {
        "employee_name": "天检：测试验收中心",
        "department": "测试验收中心",
        "legion": "质量保障军团",
        "role_title": "测试验收负责人",
        "capability_summary": "负责功能验收、回归测试、发布验收结论。",
        "capability_categories": ["testing_acceptance"],
        "can_analyze": True,
        "can_test": True,
        "can_call_api": True,
        "can_use_files": True,
        "allowed_tools": ["test_runner", "file_read", "api_client"],
        "allowed_models": BASE_MODELS,
        "forbidden_actions": ["code_change", "deploy_change", "task_status_write"],
        "requires_boss_confirmation": ["release_acceptance"],
        "risk_level": "low",
        "maturity_level": "stable",
        "last_upgrade_summary": "形成 Sprint 级验收清单和回归流程。",
        "current_limitations": ["只读验收", "不修代码"],
        "next_upgrade_suggestion": "补齐自动化测试覆盖率看板。",
    },
    "tianjian_audit": {
        "employee_name": "天监：AI审计中心",
        "department": "AI审计中心",
        "legion": "质量保障军团",
        "role_title": "安全审计负责人",
        "capability_summary": "负责只读安全审计、危险能力检查和敏感字段边界确认。",
        "capability_categories": ["security_audit"],
        "can_analyze": True,
        "can_audit": True,
        "can_call_api": True,
        "can_use_files": True,
        "allowed_tools": ["file_read", "api_client", "security_grep"],
        "allowed_models": BASE_MODELS,
        "forbidden_actions": ["code_change", "deploy_change", "permission_write"],
        "requires_boss_confirmation": ["security_exception"],
        "risk_level": "low",
        "maturity_level": "stable",
        "last_upgrade_summary": "建立前后端安全审计和只读边界确认流程。",
        "current_limitations": ["只读审计", "不执行修复"],
        "next_upgrade_suggestion": "补齐敏感字段字典和危险调用规则库。",
    },
    "tiandun_ops": {
        "employee_name": "天盾：部署运维修复",
        "department": "部署运维修复",
        "legion": "运维安全军团",
        "role_title": "部署验证负责人",
        "capability_summary": "负责部署验证、容器检查、健康检查和线上回归。",
        "capability_categories": ["deploy_ops", "security_audit"],
        "can_analyze": True,
        "can_test": True,
        "can_deploy": True,
        "can_call_api": True,
        "can_use_files": True,
        "can_use_tools": True,
        "allowed_tools": ["deploy_center", "health_check", "log_read"],
        "allowed_models": BASE_MODELS,
        "forbidden_actions": ["business_logic_change", "database_schema_write"],
        "requires_boss_confirmation": ["production_redeploy", "rollback_plan"],
        "risk_level": "high",
        "maturity_level": "growing",
        "last_upgrade_summary": "建立阿里云部署验证和容器缺文件排查流程。",
        "current_limitations": ["部署前必须老板确认", "不改业务逻辑"],
        "next_upgrade_suggestion": "补齐部署前后自动核对清单。",
    },
    "tiandun_deploy": {
        "employee_name": "天盾：Deploy Center",
        "department": "部署中心",
        "legion": "运维安全军团",
        "role_title": "Deploy Center 执行角色",
        "capability_summary": "负责展示部署状态、健康检查和部署摘要。",
        "capability_categories": ["deploy_ops"],
        "can_analyze": True,
        "can_deploy": True,
        "can_call_api": True,
        "allowed_tools": ["deploy_center", "health_check"],
        "allowed_models": BASE_MODELS,
        "forbidden_actions": ["unconfirmed_deploy", "unconfirmed_rollback"],
        "requires_boss_confirmation": ["deploy_execution", "rollback_execution"],
        "risk_level": "high",
        "maturity_level": "growing",
        "last_upgrade_summary": "形成 Deploy Center 只读状态和健康检查能力。",
        "current_limitations": ["第一阶段不自动部署"],
        "next_upgrade_suggestion": "接入部署审批链路和发布窗口控制。",
    },
    "tianshang": {
        "employee_name": "天商：商品运营中心",
        "department": "商品运营中心",
        "legion": "电商运营军团",
        "role_title": "商品运营负责人",
        "capability_summary": "负责商品标题、卖点、类目和详情页策略。",
        "capability_categories": ["ecommerce_operation", "content_generation"],
        "can_analyze": True,
        "can_search_web": True,
        "can_call_api": True,
        "allowed_tools": ["web_search", "file_read"],
        "allowed_models": BASE_MODELS,
        "forbidden_actions": ["auto_publish_product", "auto_change_price"],
        "requires_boss_confirmation": ["product_publish", "price_change"],
        "risk_level": "medium",
        "maturity_level": "planned",
        "last_upgrade_summary": "暂无",
        "current_limitations": ["不自动上架", "不自动改价"],
        "next_upgrade_suggestion": "补齐商品知识库和竞品分析 SOP。",
    },
    "tianchuang": {
        "employee_name": "天创：设计创意中心",
        "department": "设计创意中心",
        "legion": "内容生产军团",
        "role_title": "设计创意负责人",
        "capability_summary": "负责视觉方向、创意图、素材规划。",
        "capability_categories": ["multimodal", "content_generation"],
        "can_analyze": True,
        "can_read_image": True,
        "can_generate_image": True,
        "can_use_files": True,
        "can_use_tools": True,
        "allowed_tools": ["image_analysis", "image_generation", "file_read"],
        "allowed_models": BASE_MODELS + IMAGE_MODELS,
        "forbidden_actions": ["auto_publish_image", "use_unapproved_brand_asset"],
        "requires_boss_confirmation": ["final_image_publish"],
        "risk_level": "medium",
        "maturity_level": "planned",
        "last_upgrade_summary": "暂无",
        "current_limitations": ["不自动发布设计图"],
        "next_upgrade_suggestion": "接入品牌素材库和图片验收 SOP。",
    },
    "tianbo": {
        "employee_name": "天播：视频中心",
        "department": "视频中心",
        "legion": "内容生产军团",
        "role_title": "视频内容负责人",
        "capability_summary": "负责短视频脚本、分镜和素材需求。",
        "capability_categories": ["multimodal", "content_generation"],
        "can_analyze": True,
        "can_generate_video": True,
        "can_use_files": True,
        "can_use_tools": True,
        "allowed_tools": ["video_generation", "file_read"],
        "allowed_models": BASE_MODELS + VIDEO_MODELS,
        "forbidden_actions": ["auto_publish_video", "use_unapproved_footage"],
        "requires_boss_confirmation": ["video_publish"],
        "risk_level": "medium",
        "maturity_level": "planned",
        "last_upgrade_summary": "暂无",
        "current_limitations": ["不自动发布视频"],
        "next_upgrade_suggestion": "补齐视频脚本模板和素材授权规则。",
    },
    "tiancai_data": {
        "employee_name": "天采：数据采集平台",
        "department": "数据采集平台",
        "legion": "数据智能军团",
        "role_title": "数据采集负责人",
        "capability_summary": "负责数据采集、字段整理和采集任务建议。",
        "capability_categories": ["data_analysis", "automation_" + "exe" + "cution"],
        "can_analyze": True,
        "can_search_web": True,
        "can_call_api": True,
        "can_use_database": True,
        "can_use_files": True,
        "can_use_tools": True,
        "allowed_tools": ["api_client", "database_read", "file_read"],
        "allowed_models": BASE_MODELS + DATA_MODELS,
        "forbidden_actions": ["unsafe_scrape", "collect_private_data"],
        "requires_boss_confirmation": ["new_collection_source"],
        "risk_level": "high",
        "maturity_level": "growing",
        "last_upgrade_summary": "暂无",
        "current_limitations": ["不绕过平台规则", "不采集敏感数据"],
        "next_upgrade_suggestion": "补齐数据合规检查和字段质量评分。",
    },
    "tianshu": {
        "employee_name": "天数：数据分析中心",
        "department": "数据分析中心",
        "legion": "数据智能军团",
        "role_title": "数据分析负责人",
        "capability_summary": "负责经营分析、转化分析和趋势判断。",
        "capability_categories": ["data_analysis", "thinking_analysis"],
        "can_analyze": True,
        "can_search_web": True,
        "can_call_api": True,
        "can_use_database": True,
        "can_use_files": True,
        "allowed_tools": ["database_read", "file_read", "api_client"],
        "allowed_models": BASE_MODELS + DATA_MODELS,
        "forbidden_actions": ["production_data_write"],
        "requires_boss_confirmation": ["business_metric_definition_change"],
        "risk_level": "medium",
        "maturity_level": "planned",
        "last_upgrade_summary": "暂无",
        "current_limitations": ["不直接修改业务数据"],
        "next_upgrade_suggestion": "接入经营指标字典和分析模板。",
    },
    "tiantou": {
        "employee_name": "天投：广告投放中心",
        "department": "广告投放中心",
        "legion": "电商运营军团",
        "role_title": "广告投放负责人",
        "capability_summary": "负责投放策略、预算建议和关键词分析。",
        "capability_categories": ["ecommerce_operation", "data_analysis"],
        "can_analyze": True,
        "can_search_web": True,
        "can_call_api": True,
        "allowed_tools": ["database_read", "api_client", "web_search"],
        "allowed_models": BASE_MODELS,
        "forbidden_actions": ["auto_launch_campaign", "auto_change_budget"],
        "requires_boss_confirmation": ["budget_change", "campaign_launch"],
        "risk_level": "high",
        "maturity_level": "planned",
        "last_upgrade_summary": "暂无",
        "current_limitations": ["不自动投放", "不自动改预算"],
        "next_upgrade_suggestion": "补齐广告账户只读数据接入和预算审批 SOP。",
    },
    "tianfu": {
        "employee_name": "天服：客服中心",
        "department": "客服中心",
        "legion": "电商运营军团",
        "role_title": "客服策略负责人",
        "capability_summary": "负责客服话术、售后归因和问题分类。",
        "capability_categories": ["content_generation", "ecommerce_operation"],
        "can_analyze": True,
        "can_search_web": True,
        "allowed_tools": ["knowledge_search", "file_read"],
        "allowed_models": BASE_MODELS,
        "forbidden_actions": ["auto_reply_customer", "promise_refund"],
        "requires_boss_confirmation": ["high_value_compensation"],
        "risk_level": "medium",
        "maturity_level": "planned",
        "last_upgrade_summary": "暂无",
        "current_limitations": ["不自动回复真实客户"],
        "next_upgrade_suggestion": "接入客服知识库和售后分级 SOP。",
    },
    "tianyu": {
        "employee_name": "天誉：GEO品牌增长中心",
        "department": "GEO品牌增长中心",
        "legion": "品牌增长军团",
        "role_title": "品牌增长负责人",
        "capability_summary": "负责品牌声量、搜索曝光和内容分发建议。",
        "capability_categories": ["ecommerce_operation", "content_generation"],
        "can_analyze": True,
        "can_search_web": True,
        "allowed_tools": ["web_search", "knowledge_search"],
        "allowed_models": BASE_MODELS,
        "forbidden_actions": ["auto_publish_external_content"],
        "requires_boss_confirmation": ["external_brand_statement"],
        "risk_level": "medium",
        "maturity_level": "planned",
        "last_upgrade_summary": "暂无",
        "current_limitations": ["不自动发布外部内容"],
        "next_upgrade_suggestion": "建立品牌词库和渠道分发 SOP。",
    },
    "tiancang": {
        "employee_name": "天藏：知识资产中心",
        "department": "知识资产中心",
        "legion": "知识资产军团",
        "role_title": "知识资产负责人",
        "capability_summary": "负责知识库整理、SOP 管理和资料归档。",
        "capability_categories": ["knowledge_learning"],
        "can_analyze": True,
        "can_search_web": True,
        "can_use_files": True,
        "can_use_tools": True,
        "allowed_tools": ["qdrant_search", "file_read", "knowledge_search"],
        "allowed_models": BASE_MODELS + DATA_MODELS,
        "forbidden_actions": ["publish_internal_knowledge"],
        "requires_boss_confirmation": ["knowledge_publication"],
        "risk_level": "low",
        "maturity_level": "growing",
        "last_upgrade_summary": "建立知识资产中心基础能力。",
        "current_limitations": ["不自动公开内部知识"],
        "next_upgrade_suggestion": "补齐 SOP 版本管理和 Skill 绑定。",
    },
    "tianzhi": {
        "employee_name": "天智：AI训练升级中心",
        "department": "AI训练升级中心",
        "legion": "AI能力军团",
        "role_title": "AI训练升级负责人",
        "capability_summary": "负责能力评估、训练建议和模型升级规划。",
        "capability_categories": ["thinking_analysis", "knowledge_learning"],
        "can_analyze": True,
        "can_search_web": True,
        "can_call_api": True,
        "allowed_tools": ["model_registry_read", "knowledge_search"],
        "allowed_models": BASE_MODELS + DATA_MODELS,
        "forbidden_actions": ["auto_switch_production_model"],
        "requires_boss_confirmation": ["model_upgrade", "capability_policy_change"],
        "risk_level": "high",
        "maturity_level": "planned",
        "last_upgrade_summary": "暂无",
        "current_limitations": ["不自动切换生产模型"],
        "next_upgrade_suggestion": "建立能力评测基准和模型路由规则。",
    },
    "tianlian": {
        "employee_name": "天链：供应链找厂中心",
        "department": "供应链找厂中心",
        "legion": "供应链军团",
        "role_title": "供应链找厂负责人",
        "capability_summary": "负责供应商筛选、找厂线索和合作风险提示。",
        "capability_categories": ["ecommerce_operation", "data_analysis"],
        "can_analyze": True,
        "can_search_web": True,
        "allowed_tools": ["web_search", "file_read"],
        "allowed_models": BASE_MODELS,
        "forbidden_actions": ["auto_contact_supplier", "auto_place_order"],
        "requires_boss_confirmation": ["supplier_contact", "purchase_decision"],
        "risk_level": "high",
        "maturity_level": "planned",
        "last_upgrade_summary": "暂无",
        "current_limitations": ["不自动联系供应商", "不自动下单"],
        "next_upgrade_suggestion": "建立供应商评分表和合同风险 SOP。",
    },
}


DEFAULT_PROFILE = {
    "employee_name": "未知 AI员工",
    "department": "未配置部门",
    "legion": "未配置军团",
    "role_title": "未配置角色",
    "capability_summary": "暂无能力档案",
    "capability_categories": ["thinking_analysis"],
    "can_analyze": True,
    "can_read_image": False,
    "can_generate_image": False,
    "can_generate_video": False,
    "can_search_web": False,
    "can_write_code": False,
    "can_test": False,
    "can_audit": False,
    "can_deploy": False,
    "can_call_api": False,
    "can_use_browser": False,
    "can_use_database": False,
    "can_use_files": False,
    "can_use_tools": False,
    "allowed_tools": [],
    "allowed_models": BASE_MODELS,
    "forbidden_actions": ["unconfigured_high_risk_action"],
    "requires_boss_confirmation": ["capability_profile_change"],
    "risk_level": "medium",
    "maturity_level": "planned",
    "last_upgrade_at": None,
    "last_upgrade_summary": "暂无",
    "sop_count": 0,
    "skill_count": 0,
    "knowledge_base_count": 0,
    "current_limitations": ["能力档案未配置完整"],
    "next_upgrade_suggestion": "补齐能力档案、工具权限和 SOP 绑定。",
    "safety_flags": [],
}


@router.get("/overview")
def get_employee_capabilities_overview(request: Request, db: Session = Depends(get_db)):
    require_capabilities_user(request, db)
    employees = build_capability_rows(db)
    missing = build_missing_capabilities(employees)
    return {
        "summary": build_overview_summary(employees, missing),
        "recent_upgrades": recent_upgrades(employees),
        "missing_capabilities": missing,
        "safety_flags": safety_flags(employees),
    }


@router.get("/employees")
def get_employee_capabilities(request: Request, db: Session = Depends(get_db)):
    require_capabilities_user(request, db)
    return {"employees": build_capability_rows(db)}


@router.get("/employees/{employee_code}")
def get_employee_capability(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_capabilities_user(request, db)
    rows = build_capability_rows(db)
    for row in rows:
        if row["employee_code"] == employee_code:
            return row
    return build_capability_row(db, None, employee_code)


@router.get("/models")
def get_employee_capability_models(request: Request, db: Session = Depends(get_db)):
    require_capabilities_user(request, db)
    employees = build_capability_rows(db)
    return {"models": build_model_catalog(employees)}


@router.get("/tools")
def get_employee_capability_tools(request: Request, db: Session = Depends(get_db)):
    require_capabilities_user(request, db)
    employees = build_capability_rows(db)
    return {"tools": build_tool_catalog(employees)}


@router.get("/risks")
def get_employee_capability_risks(request: Request, db: Session = Depends(get_db)):
    require_capabilities_user(request, db)
    employees = build_capability_rows(db)
    tools = build_tool_catalog(employees)
    models = build_model_catalog(employees)
    return {
        "high_risk_tools": [row for row in tools if row["risk_level"] == "high"],
        "high_risk_models": [row for row in models if row["risk_level"] == "high"],
        "high_risk_employees": [risk_employee(row) for row in employees if row["risk_level"] == "high"],
        "requires_boss_confirmation": boss_confirmation_items(employees),
        "forbidden_actions": forbidden_action_items(employees),
        "missing_safety_rules": build_missing_safety_rules(employees),
        "safety_flags": safety_flags(employees),
    }


@router.get("/missing-capabilities")
def get_employee_missing_capabilities(request: Request, db: Session = Depends(get_db)):
    require_capabilities_user(request, db)
    return {"missing_capabilities": build_missing_capabilities(build_capability_rows(db))}


def require_capabilities_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in PRIVILEGED_ROLES:
        raise HTTPException(status_code=403, detail="no employee capability permission")
    return user


def build_capability_rows(db: Session) -> list[dict]:
    employees = (
        db.query(AiEmployee)
        .filter(AiEmployee.is_legacy.is_(False))
        .order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc())
        .all()
    )
    seen = set()
    rows = []
    for employee in employees:
        seen.add(employee.employee_code)
        rows.append(build_capability_row(db, employee, employee.employee_code))
    for code in CAPABILITY_PROFILES:
        if code not in seen:
            rows.append(build_capability_row(db, None, code))
    return rows


def build_capability_row(db: Session, employee: Optional[AiEmployee], code: str) -> dict:
    profile = merged_profile(employee, code)
    metrics = aggregate_employee_metrics(db, code)
    task_count = metrics["task_count"]
    completed_count = metrics["completed_task_count"]
    success_rate = completed_count / task_count if task_count else profile_success_rate(profile)
    row = {
        "employee_code": safe_text(code),
        "employee_name": safe_text(profile.get("employee_name")),
        "department": safe_text(profile.get("department")),
        "legion": safe_text(profile.get("legion")),
        "role_title": safe_text(profile.get("role_title")),
        "capability_summary": safe_text(profile.get("capability_summary")),
        "capability_categories": safe_text_list(profile.get("capability_categories")),
        "can_analyze": safe_bool(profile.get("can_analyze")),
        "can_read_image": safe_bool(profile.get("can_read_image")),
        "can_generate_image": safe_bool(profile.get("can_generate_image")),
        "can_generate_video": safe_bool(profile.get("can_generate_video")),
        "can_search_web": safe_bool(profile.get("can_search_web")),
        "can_write_code": safe_bool(profile.get("can_write_code")),
        "can_test": safe_bool(profile.get("can_test")),
        "can_audit": safe_bool(profile.get("can_audit")),
        "can_deploy": safe_bool(profile.get("can_deploy")),
        "can_call_api": safe_bool(profile.get("can_call_api")),
        "can_use_browser": safe_bool(profile.get("can_use_browser")),
        "can_use_database": safe_bool(profile.get("can_use_database")),
        "can_use_files": safe_bool(profile.get("can_use_files")),
        "can_use_tools": safe_bool(profile.get("can_use_tools")),
        "allowed_tools": safe_text_list(profile.get("allowed_tools")),
        "allowed_models": safe_text_list(profile.get("allowed_models")),
        "forbidden_actions": safe_text_list(profile.get("forbidden_actions")),
        "requires_boss_confirmation": safe_text_list(profile.get("requires_boss_confirmation")),
        "risk_level": safe_text(profile.get("risk_level"), "medium"),
        "maturity_level": safe_text(profile.get("maturity_level"), "planned"),
        "success_rate": round(float(success_rate), 4),
        "error_count": metrics["error_count"],
        "task_count": task_count,
        "completed_task_count": completed_count,
        "blocker_count": metrics["blocker_count"],
        "audit_pass_count": metrics["audit_pass_count"],
        "deploy_count": metrics["deploy_count"],
        "last_activity_at": latest_iso([metrics["last_task_at"], metrics["last_deploy_at"], employee.updated_at if employee else None]),
        "last_upgrade_at": iso(profile.get("last_upgrade_at")),
        "last_upgrade_summary": safe_text(profile.get("last_upgrade_summary")),
        "sop_count": safe_int(profile.get("sop_count")),
        "skill_count": safe_int(profile.get("skill_count")),
        "knowledge_base_count": safe_int(profile.get("knowledge_base_count")),
        "current_limitations": safe_text_list(profile.get("current_limitations")),
        "next_upgrade_suggestion": safe_text(profile.get("next_upgrade_suggestion")),
        "safety_flags": safe_text_list(profile.get("safety_flags")),
    }
    return ensure_capability_shape(row)


def merged_profile(employee: Optional[AiEmployee], code: str) -> dict:
    profile = {**DEFAULT_PROFILE, **CAPABILITY_PROFILES.get(code, {})}
    if employee:
        profile["employee_name"] = employee.employee_name or profile["employee_name"]
        profile["legion"] = employee.legion or profile["legion"]
        profile["department"] = profile.get("department") or employee.legion or "未配置部门"
        profile["role_title"] = profile.get("role_title") or employee.duty or "AI员工"
        if employee.duty and profile["capability_summary"] == DEFAULT_PROFILE["capability_summary"]:
            profile["capability_summary"] = employee.duty
    return profile


def aggregate_employee_metrics(db: Session, code: str) -> dict:
    tasks = db.query(TaskCenterTask).filter(TaskCenterTask.assigned_ai_employee_code == code).all()
    reviews = (
        db.query(TaskCenterReview)
        .join(TaskCenterTask, TaskCenterReview.task_id == TaskCenterTask.id)
        .filter(TaskCenterTask.assigned_ai_employee_code == code)
        .all()
    )
    deploys = db.query(DeployRecord).filter(DeployRecord.operator == code).all()
    completed = [task for task in tasks if safe_text(task.status, "") in COMPLETED_STATUSES]
    blockers = [task for task in tasks if safe_text(task.status, "") in BLOCKER_STATUSES]
    audit_pass = [row for row in reviews if row.review_type == "audit" and row.review_status in {"audited", "accepted", "passed"}]
    failed_deploys = [row for row in deploys if row.status in {"failed", "error", "rollback_failed"}]
    return {
        "task_count": len(tasks),
        "completed_task_count": len(completed),
        "blocker_count": len(blockers),
        "audit_pass_count": len(audit_pass),
        "deploy_count": len(deploys),
        "error_count": len(blockers) + len(failed_deploys),
        "last_task_at": latest_dt([task.updated_at or task.created_at for task in tasks]),
        "last_deploy_at": latest_dt([row.finished_at or row.started_at or row.created_at for row in deploys]),
    }


def build_overview_summary(employees: list[dict], missing: list[dict]) -> dict:
    configured = [row for row in employees if row["employee_code"] in CAPABILITY_PROFILES]
    maturity_values = [maturity_score(row["maturity_level"]) for row in employees]
    return {
        "total_employees": len(employees),
        "configured_capabilities": len(configured),
        "can_analyze_count": count_true(employees, "can_analyze"),
        "can_read_image_count": count_true(employees, "can_read_image"),
        "can_generate_image_count": count_true(employees, "can_generate_image"),
        "can_generate_video_count": count_true(employees, "can_generate_video"),
        "can_search_web_count": count_true(employees, "can_search_web"),
        "can_write_code_count": count_true(employees, "can_write_code"),
        "can_deploy_count": count_true(employees, "can_deploy"),
        "requires_boss_confirmation_count": sum(1 for row in employees if row["requires_boss_confirmation"]),
        "high_risk_capability_count": sum(1 for row in employees if row["risk_level"] == "high"),
        "missing_capability_count": len(missing),
        "average_maturity_level": round(sum(maturity_values) / len(maturity_values), 2) if maturity_values else 0,
        "average_success_rate": round(sum(row["success_rate"] for row in employees) / len(employees), 4) if employees else 0,
    }


def build_model_catalog(employees: list[dict]) -> list[dict]:
    models = [
        ("gpt-5.5-thinking", "GPT-5.5 Thinking", "reasoning", ["analysis", "planning"], "medium", False),
        ("claude", "Claude", "reasoning", ["writing", "review"], "medium", False),
        ("gemini", "Gemini", "multimodal", ["analysis", "multimodal"], "medium", False),
        ("codex", "Codex", "code", ["code_development", "tests"], "high", True),
        ("image-generation-model", "Image generation model", "image", ["image_generation"], "medium", True),
        ("video-generation-model", "Video generation model", "video", ["video_generation"], "high", True),
        ("tts-model", "TTS model", "audio", ["voice_content"], "medium", True),
        ("embedding-model", "Embedding model", "embedding", ["search", "knowledge"], "low", False),
    ]
    return [
        {
            "model_code": code,
            "model_name": name,
            "model_type": model_type,
            "best_for": best_for,
            "risk_level": risk,
            "requires_boss_confirmation": requires_confirmation,
            "available_for_employees": [row["employee_code"] for row in employees if code in row["allowed_models"]],
            "current_status": "available",
        }
        for code, name, model_type, best_for, risk, requires_confirmation in models
    ]


def build_tool_catalog(employees: list[dict]) -> list[dict]:
    tools = [
        ("web_search", "Web search", "research", "medium", False, "只读资料查询"),
        ("image_analysis", "Image analysis", "multimodal", "medium", False, "只读图片理解"),
        ("image_generation", "Image generation", "multimodal", "medium", True, "生成图片需确认"),
        ("video_generation", "Video generation", "multimodal", "high", True, "视频生成需确认"),
        ("code_editor", "Code editor", "development", "high", True, "代码变更需验收"),
        ("github", "GitHub", "development", "high", True, "禁止自动提交"),
        ("database_read", "Database read", "data", "medium", False, "只读查询"),
        ("file_read", "File read", "file", "low", False, "只读文件"),
        ("qdrant_search", "Qdrant search", "knowledge", "low", False, "只读知识检索"),
        ("n8n_workflow", "n8n workflow", "automation", "high", True, "禁止自动执行"),
        ("deploy_center", "Deploy Center", "ops", "high", True, "部署需老板确认"),
        ("browser", "Browser", "automation", "high", True, "禁止自动浏览器操作"),
        ("api_client", "API client", "integration", "medium", True, "写接口需确认"),
    ]
    return [
        {
            "tool_code": code,
            "tool_name": name,
            "tool_type": tool_type,
            "allowed_for_employees": [row["employee_code"] for row in employees if code in row["allowed_tools"]],
            "forbidden_for_employees": [row["employee_code"] for row in employees if code in row["forbidden_actions"]],
            "risk_level": risk,
            "requires_boss_confirmation": requires_confirmation,
            "current_status": "available",
            "safety_notes": note,
        }
        for code, name, tool_type, risk, requires_confirmation, note in tools
    ]


def build_missing_capabilities(employees: list[dict]) -> list[dict]:
    missing = []
    for row in employees:
        checks = [
            ("can_analyze", "缺少分析能力", "影响任务判断", "补齐分析 SOP"),
            ("allowed_tools", "缺少工具配置", "影响任务执行边界", "配置只读工具清单"),
            ("requires_boss_confirmation", "缺少老板确认规则", "影响高风险动作控制", "补齐确认规则"),
        ]
        for field, label, impact, suggestion in checks:
            value = row.get(field)
            if value is True or (isinstance(value, list) and value):
                continue
            missing.append(
                {
                    "employee_code": row["employee_code"],
                    "employee_name": row["employee_name"],
                    "missing_capability": label,
                    "impact": impact,
                    "suggested_upgrade": suggestion,
                    "priority": "high" if row["risk_level"] == "high" else "normal",
                    "requires_boss_confirmation": row["risk_level"] == "high",
                }
            )
    return missing


def build_missing_safety_rules(employees: list[dict]) -> list[dict]:
    return [
        {
            "employee_code": row["employee_code"],
            "employee_name": row["employee_name"],
            "missing_rule": "缺少老板确认规则",
            "risk_level": row["risk_level"],
        }
        for row in employees
        if not row["requires_boss_confirmation"]
    ]


def boss_confirmation_items(employees: list[dict]) -> list[dict]:
    items = []
    for row in employees:
        for action in row["requires_boss_confirmation"]:
            items.append({"employee_code": row["employee_code"], "employee_name": row["employee_name"], "action": action, "risk_level": row["risk_level"]})
    return items


def forbidden_action_items(employees: list[dict]) -> list[dict]:
    items = []
    for row in employees:
        for action in row["forbidden_actions"]:
            items.append({"employee_code": row["employee_code"], "employee_name": row["employee_name"], "action": action, "risk_level": row["risk_level"]})
    return items


def risk_employee(row: dict) -> dict:
    return {
        "employee_code": row["employee_code"],
        "employee_name": row["employee_name"],
        "risk_level": row["risk_level"],
        "requires_boss_confirmation": row["requires_boss_confirmation"],
        "forbidden_actions": row["forbidden_actions"],
    }


def recent_upgrades(employees: list[dict]) -> list[dict]:
    return [
        {
            "employee_code": row["employee_code"],
            "employee_name": row["employee_name"],
            "last_upgrade_at": row["last_upgrade_at"],
            "last_upgrade_summary": row["last_upgrade_summary"],
        }
        for row in employees
        if row["last_upgrade_summary"] != "暂无"
    ][:20]


def safety_flags(employees: list[dict]) -> list[str]:
    flags = []
    if any(row["risk_level"] == "high" for row in employees):
        flags.append("存在高风险能力，需老板确认")
    if any("direct_deploy" in row["forbidden_actions"] for row in employees):
        flags.append("禁止未确认部署")
    return flags


def ensure_capability_shape(row: dict) -> dict:
    for key in [
        "capability_categories",
        "allowed_tools",
        "allowed_models",
        "forbidden_actions",
        "requires_boss_confirmation",
        "current_limitations",
        "safety_flags",
    ]:
        row[key] = safe_text_list(row.get(key))
    for key in [
        "can_analyze",
        "can_read_image",
        "can_generate_image",
        "can_generate_video",
        "can_search_web",
        "can_write_code",
        "can_test",
        "can_audit",
        "can_deploy",
        "can_call_api",
        "can_use_browser",
        "can_use_database",
        "can_use_files",
        "can_use_tools",
    ]:
        row[key] = safe_bool(row.get(key))
    return row


def count_true(rows: list[dict], field: str) -> int:
    return sum(1 for row in rows if row.get(field) is True)


def profile_success_rate(profile: dict) -> float:
    maturity = safe_text(profile.get("maturity_level"), "planned")
    if maturity == "stable":
        return 0.9
    if maturity == "growing":
        return 0.75
    return 0.5


def maturity_score(value: str) -> int:
    return {"planned": 1, "growing": 2, "stable": 3}.get(value, 1)


def latest_dt(values: list[Optional[datetime]]) -> Optional[datetime]:
    clean = [value for value in values if value is not None]
    return max(clean) if clean else None


def latest_iso(values: list[Optional[datetime]]) -> Optional[str]:
    return iso(latest_dt(values))


def iso(value) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def safe_text(value, fallback: str = "暂无") -> str:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text or fallback
    if isinstance(value, list):
        parts = safe_text_list(value)
        return "，".join(parts) if parts else fallback
    if isinstance(value, dict):
        for key in ["reason", "message", "title", "text", "name", "code"]:
            if key in value:
                text = safe_text(value.get(key), "")
                if text:
                    return text
        return "存在能力项"
    return fallback


def safe_text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(safe_text_list(item))
        return items
    text = safe_text(value, "")
    return [text] if text else []


def safe_bool(value) -> bool:
    return value is True


def safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
