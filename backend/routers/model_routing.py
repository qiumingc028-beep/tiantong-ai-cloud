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
        for key in ("reason", "message", "title", "text", "name", "code", "model_code", "employee_code", "task_type"):
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


def safe_bool(value) -> bool:
    return value is True


def require_model_routing_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in PRIVILEGED_ROLES:
        raise HTTPException(status_code=403, detail="no model routing permission")
    return user


MODEL_CONFIGS = [
    {
        "model_code": "gpt_5_5_thinking",
        "model_name": "GPT-5.5 Thinking",
        "provider": "OpenAI",
        "model_type": "reasoning",
        "best_for": ["strategy_analysis", "architecture_design", "security_audit", "data_analysis"],
        "not_good_for": ["image_design", "video_generation"],
        "cost_level": "high",
        "risk_level": "medium",
        "speed_level": "medium",
        "quality_level": "high",
        "reasoning_level": "high",
        "coding_level": "medium",
        "vision_level": "low",
        "image_generation_level": "none",
        "video_generation_level": "none",
        "tool_call_level": "recommended_only",
        "recommended_employees": ["tiantong", "tiandao", "tiangong", "tianjian_test", "tianjian_audit", "tiandun_ops", "tianzhi"],
        "recommended_task_types": ["strategy_analysis", "product_design", "architecture_design", "testing_acceptance", "security_audit", "deployment_ops", "data_analysis"],
        "fallback_models": ["gpt_5_5", "claude"],
        "requires_boss_confirmation": True,
        "current_status": "active",
        "safety_notes": ["第一阶段只展示推荐，不自动调用模型。"],
    },
    {
        "model_code": "gpt_5_5",
        "model_name": "GPT-5.5",
        "provider": "OpenAI",
        "model_type": "general",
        "best_for": ["product_design", "content_generation", "ecommerce_operation", "customer_service"],
        "not_good_for": ["video_generation"],
        "cost_level": "medium",
        "risk_level": "medium",
        "speed_level": "high",
        "quality_level": "high",
        "reasoning_level": "medium",
        "coding_level": "medium",
        "vision_level": "low",
        "image_generation_level": "none",
        "video_generation_level": "none",
        "tool_call_level": "recommended_only",
        "recommended_employees": ["tiantong", "tianshang", "tianfu", "tianyu", "tianlian"],
        "recommended_task_types": ["product_design", "ecommerce_operation", "content_generation", "customer_service", "supplier_search", "ad_optimization", "geo_seo"],
        "fallback_models": ["claude", "gemini"],
        "requires_boss_confirmation": False,
        "current_status": "active",
        "safety_notes": ["通用推荐模型，仍不允许自动扣费调用。"],
    },
    {
        "model_code": "claude",
        "model_name": "Claude",
        "provider": "Anthropic",
        "model_type": "document_reasoning",
        "best_for": ["product_design", "testing_acceptance", "security_audit", "content_generation", "geo_seo"],
        "not_good_for": ["image_design", "video_generation", "deployment_ops"],
        "cost_level": "medium",
        "risk_level": "medium",
        "speed_level": "medium",
        "quality_level": "high",
        "reasoning_level": "high",
        "coding_level": "medium",
        "vision_level": "low",
        "image_generation_level": "none",
        "video_generation_level": "none",
        "tool_call_level": "recommended_only",
        "recommended_employees": ["tiandao", "tiangong", "tianjian_test", "tianjian_audit", "tianyu"],
        "recommended_task_types": ["product_design", "testing_acceptance", "security_audit", "content_generation", "geo_seo"],
        "fallback_models": ["gpt_5_5", "gpt_5_5_thinking"],
        "requires_boss_confirmation": False,
        "current_status": "active",
        "safety_notes": ["适合长文审查，第一阶段不接入外部调用。"],
    },
    {
        "model_code": "gemini",
        "model_name": "Gemini",
        "provider": "Google",
        "model_type": "multimodal_analysis",
        "best_for": ["data_analysis", "supplier_search", "knowledge_learning"],
        "not_good_for": ["backend_coding", "deployment_ops"],
        "cost_level": "medium",
        "risk_level": "medium",
        "speed_level": "high",
        "quality_level": "medium",
        "reasoning_level": "medium",
        "coding_level": "low",
        "vision_level": "medium",
        "image_generation_level": "none",
        "video_generation_level": "none",
        "tool_call_level": "recommended_only",
        "recommended_employees": ["tiancai_data", "tianshu", "tianlian"],
        "recommended_task_types": ["data_analysis", "supplier_search", "knowledge_learning"],
        "fallback_models": ["gpt_5_5", "claude"],
        "requires_boss_confirmation": False,
        "current_status": "active",
        "safety_notes": ["仅展示多模态分析适配，不自动调用。"],
    },
    {
        "model_code": "codex",
        "model_name": "Codex",
        "provider": "OpenAI",
        "model_type": "coding",
        "best_for": ["backend_coding", "frontend_coding"],
        "not_good_for": ["image_design", "video_generation", "customer_service"],
        "cost_level": "medium",
        "risk_level": "high",
        "speed_level": "high",
        "quality_level": "high",
        "reasoning_level": "medium",
        "coding_level": "high",
        "vision_level": "none",
        "image_generation_level": "none",
        "video_generation_level": "none",
        "tool_call_level": "recommended_only",
        "recommended_employees": ["tianwang", "tianyan_frontend"],
        "recommended_task_types": ["backend_coding", "frontend_coding"],
        "fallback_models": ["gpt_5_5", "gpt_5_5_thinking"],
        "requires_boss_confirmation": True,
        "current_status": "active",
        "safety_notes": ["只允许推荐给开发员工，不能自动发送任务或修改代码。"],
    },
    {
        "model_code": "image_generation",
        "model_name": "Image generation model",
        "provider": "Image Provider",
        "model_type": "image_generation",
        "best_for": ["image_design"],
        "not_good_for": ["backend_coding", "security_audit", "deployment_ops"],
        "cost_level": "high",
        "risk_level": "high",
        "speed_level": "medium",
        "quality_level": "high",
        "reasoning_level": "low",
        "coding_level": "none",
        "vision_level": "medium",
        "image_generation_level": "high",
        "video_generation_level": "none",
        "tool_call_level": "recommended_only",
        "recommended_employees": ["tianchuang"],
        "recommended_task_types": ["image_design"],
        "fallback_models": ["gpt_5_5"],
        "requires_boss_confirmation": True,
        "current_status": "recommended_only",
        "safety_notes": ["图片生成必须老板确认，第一阶段不自动生成图片。"],
    },
    {
        "model_code": "video_generation",
        "model_name": "Video generation model",
        "provider": "Video Provider",
        "model_type": "video_generation",
        "best_for": ["video_generation"],
        "not_good_for": ["backend_coding", "security_audit", "customer_service"],
        "cost_level": "very_high",
        "risk_level": "high",
        "speed_level": "low",
        "quality_level": "high",
        "reasoning_level": "low",
        "coding_level": "none",
        "vision_level": "medium",
        "image_generation_level": "low",
        "video_generation_level": "high",
        "tool_call_level": "recommended_only",
        "recommended_employees": ["tianbo"],
        "recommended_task_types": ["video_generation"],
        "fallback_models": ["image_generation", "gpt_5_5"],
        "requires_boss_confirmation": True,
        "current_status": "recommended_only",
        "safety_notes": ["视频生成高成本高风险，第一阶段仅展示。"],
    },
    {
        "model_code": "tts",
        "model_name": "TTS model",
        "provider": "Voice Provider",
        "model_type": "speech",
        "best_for": ["customer_service", "content_generation"],
        "not_good_for": ["backend_coding", "deployment_ops"],
        "cost_level": "medium",
        "risk_level": "medium",
        "speed_level": "high",
        "quality_level": "medium",
        "reasoning_level": "none",
        "coding_level": "none",
        "vision_level": "none",
        "image_generation_level": "none",
        "video_generation_level": "none",
        "tool_call_level": "recommended_only",
        "recommended_employees": ["tianfu"],
        "recommended_task_types": ["customer_service", "content_generation"],
        "fallback_models": ["gpt_5_5"],
        "requires_boss_confirmation": True,
        "current_status": "recommended_only",
        "safety_notes": ["语音输出涉及对外内容，需老板确认。"],
    },
    {
        "model_code": "embedding",
        "model_name": "Embedding model",
        "provider": "Vector Provider",
        "model_type": "embedding",
        "best_for": ["knowledge_learning", "geo_seo"],
        "not_good_for": ["image_design", "video_generation", "deployment_ops"],
        "cost_level": "low",
        "risk_level": "low",
        "speed_level": "high",
        "quality_level": "medium",
        "reasoning_level": "none",
        "coding_level": "none",
        "vision_level": "none",
        "image_generation_level": "none",
        "video_generation_level": "none",
        "tool_call_level": "recommended_only",
        "recommended_employees": ["tiancang", "tianshu", "tianyu"],
        "recommended_task_types": ["knowledge_learning", "geo_seo"],
        "fallback_models": ["rerank", "gpt_5_5"],
        "requires_boss_confirmation": False,
        "current_status": "active",
        "safety_notes": ["用于检索推荐，不自动写入知识库。"],
    },
    {
        "model_code": "rerank",
        "model_name": "Rerank model",
        "provider": "Search Provider",
        "model_type": "rerank",
        "best_for": ["knowledge_learning", "geo_seo"],
        "not_good_for": ["backend_coding", "image_design", "video_generation"],
        "cost_level": "low",
        "risk_level": "low",
        "speed_level": "high",
        "quality_level": "medium",
        "reasoning_level": "none",
        "coding_level": "none",
        "vision_level": "none",
        "image_generation_level": "none",
        "video_generation_level": "none",
        "tool_call_level": "recommended_only",
        "recommended_employees": ["tiancang", "tianyu", "tianshu"],
        "recommended_task_types": ["knowledge_learning", "geo_seo"],
        "fallback_models": ["embedding", "gpt_5_5"],
        "requires_boss_confirmation": False,
        "current_status": "active",
        "safety_notes": ["仅做排序推荐，不自动调用外部搜索。"],
    },
]


TASK_TYPE_CONFIGS = [
    ("strategy_analysis", "战略分析", "gpt_5_5_thinking", ["claude", "gpt_5_5"], [], "复杂战略需要高推理模型。", "high", "medium", True),
    ("product_design", "产品设计", "gpt_5_5_thinking", ["gpt_5_5", "claude"], [], "产品设计需要推理和表达兼顾。", "medium", "medium", False),
    ("architecture_design", "架构设计", "gpt_5_5_thinking", ["claude"], ["image_generation", "video_generation"], "架构设计优先深度推理。", "high", "medium", True),
    ("backend_coding", "后端开发", "codex", ["gpt_5_5", "gpt_5_5_thinking"], ["image_generation", "video_generation"], "代码任务优先 Codex。", "medium", "high", True),
    ("frontend_coding", "前端开发", "codex", ["gpt_5_5"], ["video_generation"], "前端代码和联调优先 Codex。", "medium", "high", True),
    ("testing_acceptance", "测试验收", "gpt_5_5_thinking", ["claude"], ["image_generation", "video_generation"], "验收需要严格推理和清单化。", "medium", "low", False),
    ("security_audit", "安全审计", "gpt_5_5_thinking", ["claude"], ["image_generation", "video_generation"], "安全审计需要高推理和谨慎输出。", "high", "high", True),
    ("deployment_ops", "部署运维", "gpt_5_5_thinking", ["gpt_5_5"], ["image_generation", "video_generation"], "部署只给建议，不自动执行。", "high", "high", True),
    ("ecommerce_operation", "电商运营", "gpt_5_5", ["claude"], ["codex"], "运营内容适合通用模型。", "medium", "medium", False),
    ("data_analysis", "数据分析", "gpt_5_5_thinking", ["gemini", "embedding"], ["video_generation"], "数据分析需要推理和多源摘要。", "medium", "medium", False),
    ("image_design", "图片设计", "image_generation", ["gpt_5_5"], ["codex"], "图片任务适合图片生成模型。", "high", "high", True),
    ("video_generation", "视频生成", "video_generation", ["image_generation", "gpt_5_5"], ["codex"], "视频生成高成本，必须确认。", "very_high", "high", True),
    ("content_generation", "内容生成", "gpt_5_5", ["claude", "tts"], [], "内容生成适合通用模型。", "medium", "medium", False),
    ("knowledge_learning", "知识学习", "embedding", ["rerank", "gpt_5_5"], ["video_generation"], "知识学习优先检索向量和重排。", "low", "low", False),
    ("customer_service", "客服处理", "gpt_5_5", ["tts"], ["codex", "video_generation"], "客服优先稳定通用回答。", "medium", "medium", False),
    ("supplier_search", "供应链找厂", "gpt_5_5", ["gemini"], ["video_generation"], "供应链分析需要资料整理。", "medium", "medium", False),
    ("ad_optimization", "广告投放优化", "gpt_5_5_thinking", ["gpt_5_5"], ["image_generation"], "广告优化需要策略分析。", "high", "medium", True),
    ("geo_seo", "GEO / SEO 优化", "gpt_5_5", ["claude", "rerank"], ["video_generation"], "GEO/SEO 需要内容和排序能力。", "medium", "medium", False),
]


EMPLOYEE_CONFIGS = [
    ("tiantong", "天统：AI总指挥", "AI总指挥", "gpt_5_5_thinking", ["gpt_5_5"], ["strategy_analysis", "product_design"], "总指挥需要高推理模型。", "high", "medium", True),
    ("tiandao", "天道：AI产品经理中心", "AI产品经理中心", "gpt_5_5_thinking", ["claude"], ["product_design", "strategy_analysis"], "产品设计需要推理和文档能力。", "medium", "medium", False),
    ("tiangong", "天工：系统架构中心", "系统架构中心", "gpt_5_5_thinking", ["claude"], ["architecture_design"], "架构设计需要高推理。", "high", "medium", True),
    ("tianwang", "天王：后端开发中心", "后端开发中心", "codex", ["gpt_5_5", "gpt_5_5_thinking"], ["backend_coding"], "后端代码优先 Codex。", "medium", "high", True),
    ("tianyan_frontend", "天颜：前端联调优化", "前端联调优化", "codex", ["gpt_5_5"], ["frontend_coding"], "前端代码优先 Codex。", "medium", "high", True),
    ("tianjian_test", "天检：测试验收中心", "测试验收中心", "gpt_5_5_thinking", ["claude"], ["testing_acceptance"], "验收需要清单和推理。", "medium", "low", False),
    ("tianjian_audit", "天监：AI审计中心", "AI审计中心", "gpt_5_5_thinking", ["claude"], ["security_audit"], "审计需要谨慎推理。", "high", "high", True),
    ("tiandun_ops", "天盾：部署运维修复", "部署运维修复", "gpt_5_5_thinking", ["gpt_5_5"], ["deployment_ops"], "部署只读建议，禁止自动执行。", "high", "high", True),
    ("tiandun_deploy", "天盾：Deploy Center", "部署中心", "gpt_5_5_thinking", ["gpt_5_5"], ["deployment_ops"], "部署中心只展示推荐模型。", "high", "high", True),
    ("tianshang", "天商：商品运营中心", "商品运营中心", "gpt_5_5", ["claude"], ["ecommerce_operation", "content_generation"], "商品运营适合通用内容模型。", "medium", "medium", False),
    ("tianchuang", "天创：设计创意中心", "设计创意中心", "image_generation", ["gpt_5_5"], ["image_design"], "设计任务需要图片生成模型。", "high", "high", True),
    ("tianbo", "天播：视频中心", "视频中心", "video_generation", ["gpt_5_5"], ["video_generation"], "视频生成高成本需确认。", "very_high", "high", True),
    ("tiancai_data", "天采：数据采集平台", "数据采集平台", "gemini", ["gpt_5_5"], ["supplier_search", "data_analysis"], "采集资料适合多模态分析。", "medium", "medium", False),
    ("tianshu", "天数：数据分析中心", "数据分析中心", "gpt_5_5_thinking", ["embedding", "rerank"], ["data_analysis", "knowledge_learning"], "数据分析需要推理和检索。", "medium", "medium", False),
    ("tiantou", "天投：广告投放中心", "广告投放中心", "gpt_5_5_thinking", ["gpt_5_5"], ["ad_optimization"], "广告优化需要策略推理。", "high", "medium", True),
    ("tianfu", "天服：客服中心", "客服中心", "gpt_5_5", ["tts"], ["customer_service"], "客服适合稳定通用模型。", "medium", "medium", False),
    ("tianyu", "天誉：GEO品牌增长中心", "GEO品牌增长中心", "gpt_5_5", ["claude", "rerank"], ["geo_seo", "content_generation"], "GEO 需要内容与排序能力。", "medium", "medium", False),
    ("tiancang", "天藏：知识资产中心", "知识资产中心", "embedding", ["rerank", "gpt_5_5"], ["knowledge_learning"], "知识资产优先检索模型。", "low", "low", False),
    ("tianzhi", "天智：AI训练升级中心", "AI训练升级中心", "gpt_5_5_thinking", ["gpt_5_5"], ["strategy_analysis", "knowledge_learning"], "训练升级需要高推理建议。", "high", "medium", True),
    ("tianlian", "天链：供应链找厂中心", "供应链找厂中心", "gpt_5_5", ["gemini"], ["supplier_search"], "供应链找厂需要资料整理。", "medium", "medium", False),
]


@router.get("/overview")
def get_model_routing_overview(request: Request, db: Session = Depends(get_db)):
    require_model_routing_user(request, db)
    models = build_models()
    employees = build_employees()
    task_types = build_task_types()
    fallbacks = build_fallbacks()
    return {
        "total_models": len(models),
        "active_models": sum(1 for row in models if row["current_status"] == "active"),
        "high_cost_models": sum(1 for row in models if row["cost_level"] in {"high", "very_high"}),
        "high_risk_models": sum(1 for row in models if row["risk_level"] == "high"),
        "boss_confirmation_required_count": sum(1 for row in models if row["requires_boss_confirmation"]),
        "employees_with_model_profile": len(employees),
        "task_types_configured": len(task_types),
        "auto_call_disabled_count": sum(1 for row in models + employees + task_types if not row["can_auto_call"]),
        "fallback_strategy_count": len(fallbacks),
        "recommended_model_summary": recommended_model_summary(models),
        "risk_summary": count_by(models, "risk_level"),
        "cost_summary": count_by(models, "cost_level"),
        "safety_flags": ["第一阶段只读", "禁止自动调用模型", "禁止自动扣费", "禁止执行型接口"],
        "next_upgrade_suggestions": [
            "接入模型质量评分前仍保持只读。",
            "未来自动路由必须经过老板确认和安全审计。",
        ],
    }


@router.get("/models")
def get_model_routing_models(request: Request, db: Session = Depends(get_db)):
    require_model_routing_user(request, db)
    return {"models": build_models()}


@router.get("/models/{model_code}")
def get_model_routing_model(model_code: str, request: Request, db: Session = Depends(get_db)):
    require_model_routing_user(request, db)
    model = next((row for row in build_models() if row["model_code"] == model_code), None)
    if not model:
        raise HTTPException(status_code=404, detail="model not found")
    return model


@router.get("/employees")
def get_model_routing_employees(request: Request, db: Session = Depends(get_db)):
    require_model_routing_user(request, db)
    return {"employees": build_employees()}


@router.get("/employees/{employee_code}")
def get_model_routing_employee(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_model_routing_user(request, db)
    employee = next((row for row in build_employees() if row["employee_code"] == employee_code), None)
    if not employee:
        raise HTTPException(status_code=404, detail="employee model routing not found")
    return employee


@router.get("/task-types")
def get_model_routing_task_types(request: Request, db: Session = Depends(get_db)):
    require_model_routing_user(request, db)
    return {"task_types": build_task_types()}


@router.get("/recommendations")
def get_model_routing_recommendations(request: Request, db: Session = Depends(get_db)):
    require_model_routing_user(request, db)
    return {
        "recommendations": [
            {
                "recommendation_id": f"recommend-{row['task_type']}",
                "task_type": row["task_type"],
                "employee_codes": employees_for_task(row["task_type"]),
                "primary_model": row["primary_model"],
                "backup_models": row["backup_models"],
                "recommended_reason": row["recommended_reason"],
                "cost_level": row["cost_level"],
                "risk_level": row["risk_level"],
                "requires_boss_confirmation": row["requires_boss_confirmation"],
                "can_auto_call": False,
                "safety_notes": row["safety_notes"],
            }
            for row in build_task_types()
        ]
    }


@router.get("/risks")
def get_model_routing_risks(request: Request, db: Session = Depends(get_db)):
    require_model_routing_user(request, db)
    models = build_models()
    employees = build_employees()
    task_types = build_task_types()
    return {
        "high_risk_models": [row for row in models if row["risk_level"] == "high"],
        "high_cost_models": [row for row in models if row["cost_level"] in {"high", "very_high"}],
        "boss_confirmation_required": [row for row in models if row["requires_boss_confirmation"]],
        "recommended_only_models": [row for row in models if row["current_status"] == "recommended_only"],
        "high_risk_employees": [row for row in employees if row["risk_level"] == "high"],
        "high_risk_task_types": [row for row in task_types if row["risk_level"] == "high"],
        "disabled_auto_call": [row["model_code"] for row in models if not row["can_auto_call"]],
        "safety_flags": ["全部模型 can_auto_call=false", "不返回任何密钥或外部凭证"],
    }


@router.get("/fallbacks")
def get_model_routing_fallbacks(request: Request, db: Session = Depends(get_db)):
    require_model_routing_user(request, db)
    return {"fallbacks": build_fallbacks()}


def build_models() -> list[dict]:
    return [ensure_model_shape(row) for row in MODEL_CONFIGS]


def build_task_types() -> list[dict]:
    rows = []
    for task_type, task_name, primary, backups, forbidden, reason, cost, risk, confirm in TASK_TYPE_CONFIGS:
        rows.append(
            {
                "task_type": safe_text(task_type),
                "task_name": safe_text(task_name),
                "primary_model": safe_text(primary),
                "backup_models": safe_text_list(backups),
                "forbidden_models": safe_text_list(forbidden),
                "recommended_reason": safe_text(reason),
                "cost_level": safe_text(cost),
                "risk_level": safe_text(risk),
                "requires_boss_confirmation": safe_bool(confirm),
                "can_auto_call": False,
                "safety_notes": ["第一阶段只推荐模型，不自动调用。"],
            }
        )
    return rows


def build_employees() -> list[dict]:
    rows = []
    model_codes = {row["model_code"] for row in build_models()}
    for code, name, department, primary, backups, task_types, reason, cost, risk, confirm in EMPLOYEE_CONFIGS:
        allowed = [primary] + list(backups)
        forbidden = sorted(model_codes - set(allowed))
        rows.append(
            {
                "employee_code": safe_text(code),
                "employee_name": safe_text(name),
                "department": safe_text(department),
                "primary_model": safe_text(primary),
                "backup_models": safe_text_list(backups),
                "allowed_models": safe_text_list(allowed),
                "forbidden_models": safe_text_list(forbidden),
                "recommended_task_types": safe_text_list(task_types),
                "model_selection_reason": safe_text(reason),
                "cost_control_level": safe_text(cost),
                "risk_level": safe_text(risk),
                "requires_boss_confirmation": safe_bool(confirm),
                "can_auto_call": False,
                "safety_notes": ["员工模型适配只读展示，不自动授权模型。"],
            }
        )
    return rows


def build_fallbacks() -> list[dict]:
    return [
        {
            "strategy_id": f"fallback-{row['primary_model']}-{row['task_type']}",
            "scope": row["task_type"],
            "primary_model": row["primary_model"],
            "fallback_models": row["backup_models"],
            "trigger_conditions": ["primary_unavailable", "quality_check_failed", "cost_control_required"],
            "requires_boss_confirmation": row["requires_boss_confirmation"],
            "can_auto_switch": False,
            "can_auto_call": False,
            "safety_notes": ["第一阶段只展示降级建议，不自动切换模型。"],
        }
        for row in build_task_types()
    ]


def ensure_model_shape(row: dict) -> dict:
    return {
        "model_code": safe_text(row.get("model_code")),
        "model_name": safe_text(row.get("model_name")),
        "provider": safe_text(row.get("provider")),
        "model_type": safe_text(row.get("model_type")),
        "best_for": safe_text_list(row.get("best_for")),
        "not_good_for": safe_text_list(row.get("not_good_for")),
        "cost_level": safe_text(row.get("cost_level"), "medium"),
        "risk_level": safe_text(row.get("risk_level"), "medium"),
        "speed_level": safe_text(row.get("speed_level"), "medium"),
        "quality_level": safe_text(row.get("quality_level"), "medium"),
        "reasoning_level": safe_text(row.get("reasoning_level"), "none"),
        "coding_level": safe_text(row.get("coding_level"), "none"),
        "vision_level": safe_text(row.get("vision_level"), "none"),
        "image_generation_level": safe_text(row.get("image_generation_level"), "none"),
        "video_generation_level": safe_text(row.get("video_generation_level"), "none"),
        "tool_call_level": safe_text(row.get("tool_call_level"), "recommended_only"),
        "recommended_employees": safe_text_list(row.get("recommended_employees")),
        "recommended_task_types": safe_text_list(row.get("recommended_task_types")),
        "fallback_models": safe_text_list(row.get("fallback_models")),
        "requires_boss_confirmation": safe_bool(row.get("requires_boss_confirmation")),
        "can_auto_call": False,
        "current_status": safe_text(row.get("current_status"), "active"),
        "safety_notes": safe_text_list(row.get("safety_notes")),
    }


def recommended_model_summary(models: list[dict]) -> list[dict]:
    return [
        {
            "model_code": row["model_code"],
            "model_name": row["model_name"],
            "recommended_task_count": len(row["recommended_task_types"]),
            "recommended_employee_count": len(row["recommended_employees"]),
            "risk_level": row["risk_level"],
            "cost_level": row["cost_level"],
            "can_auto_call": False,
        }
        for row in models
    ]


def count_by(rows: list[dict], key: str) -> dict:
    result: dict[str, int] = {}
    for row in rows:
        value = safe_text(row.get(key), "unknown")
        result[value] = result.get(value, 0) + 1
    return result


def employees_for_task(task_type: str) -> list[str]:
    return [row["employee_code"] for row in build_employees() if task_type in row["recommended_task_types"]]
