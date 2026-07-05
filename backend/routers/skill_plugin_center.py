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


def require_skill_plugin_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in PRIVILEGED_ROLES:
        raise HTTPException(status_code=403, detail="no skill plugin center permission")
    return user


def make_skill(
    code: str,
    name: str,
    category: str,
    employees: list[str],
    departments: list[str],
    risk: str,
    cost: str,
    permission: str,
    confirm: bool,
    notes: list[str],
) -> dict:
    return {
        "skill_code": safe_text(code),
        "skill_name": safe_text(name),
        "skill_category": safe_text(category),
        "suitable_employees": safe_text_list(employees),
        "suitable_departments": safe_text_list(departments),
        "risk_level": safe_text(risk),
        "cost_level": safe_text(cost),
        "permission_level": safe_text(permission),
        "requires_boss_confirmation": bool(confirm),
        "can_auto_install": False,
        "can_auto_enable": False,
        "can_auto_execute": False,
        "safety_notes": safe_text_list(notes),
    }


def make_plugin(
    code: str,
    name: str,
    category: str,
    vendor: str,
    install_method: str,
    platforms: list[str],
    risk: str,
    cost: str,
    confirm: bool,
    notes: list[str],
) -> dict:
    return {
        "plugin_code": safe_text(code),
        "plugin_name": safe_text(name),
        "plugin_category": safe_text(category),
        "official_url": f"{safe_text(vendor).lower().replace(' ', '-')}.example",
        "vendor": safe_text(vendor),
        "install_method": safe_text(install_method),
        "supported_platform": safe_text_list(platforms),
        "risk_level": safe_text(risk),
        "cost_level": safe_text(cost),
        "requires_boss_confirmation": bool(confirm),
        "can_auto_download": False,
        "can_auto_install": False,
        "can_auto_enable": False,
        "can_auto_execute": False,
        "safety_notes": safe_text_list(notes),
    }


def make_mcp(
    code: str,
    name: str,
    capability: str,
    employee: str,
    department: str,
    risk: str,
    scope: str,
    can_read: bool,
    notes: list[str],
) -> dict:
    return {
        "mcp_code": safe_text(code),
        "mcp_name": safe_text(name),
        "capability": safe_text(capability),
        "target_employee": safe_text(employee),
        "target_department": safe_text(department),
        "risk_level": safe_text(risk),
        "permission_scope": safe_text(scope),
        "can_read": bool(can_read),
        "can_write": False,
        "can_execute": False,
        "can_spend_money": False,
        "safety_notes": safe_text_list(notes),
    }


def make_external_tool(
    code: str,
    name: str,
    category: str,
    vendor: str,
    capability: str,
    employee: str,
    department: str,
    risk: str,
    scope: str,
    confirm: bool,
    notes: list[str],
) -> dict:
    return {
        "tool_code": safe_text(code),
        "tool_name": safe_text(name),
        "tool_category": safe_text(category),
        "vendor": safe_text(vendor),
        "official_url": f"{safe_text(vendor).lower().replace(' ', '-')}.example",
        "capability": safe_text(capability),
        "target_employee": safe_text(employee),
        "target_department": safe_text(department),
        "risk_level": safe_text(risk),
        "permission_scope": safe_text(scope),
        "requires_boss_confirmation": bool(confirm),
        "can_read": True,
        "can_write": False,
        "can_execute": False,
        "can_spend_money": False,
        "can_auto_download": False,
        "can_auto_install": False,
        "can_auto_enable": False,
        "can_auto_execute": False,
        "safety_notes": safe_text_list(notes),
    }


SKILLS = [
    make_skill("skill_prompt_engineering", "提示词工程", "prompt", ["tiandao", "tiantong"], ["AI产品经理中心"], "medium", "low", "research_only", True, ["只读登记", "不自动执行模板"]),
    make_skill("skill_data_analysis", "数据分析", "data", ["tianshu", "tiancai_data"], ["数据分析中心"], "medium", "medium", "research_only", True, ["只展示能力候选", "不连接真实数据源"]),
    make_skill("skill_frontend_debug", "前端调试", "frontend", ["tianyan_frontend"], ["前端联调优化"], "high", "medium", "boss_confirm_required", True, ["可研究浏览器视图", "禁止自动点击"]),
    make_skill("skill_backend_debug", "后端调试", "backend", ["tianwang"], ["后端开发中心"], "high", "medium", "boss_confirm_required", True, ["只读评估", "不改服务状态"]),
    make_skill("skill_deploy_check", "部署检查", "deploy", ["tiandun_ops"], ["部署运维修复"], "critical", "medium", "boss_confirm_required", True, ["禁止自动部署", "需要天盾人工验证"]),
    make_skill("skill_security_review", "安全审计", "security", ["tianjian_audit"], ["AI审计中心"], "high", "low", "research_only", True, ["只读审计", "不自动改权限"]),
    make_skill("skill_sop_generation", "SOP 草案生成", "sop", ["tiandao", "tiancang"], ["知识资产中心"], "medium", "low", "draft_only", True, ["只允许草案规划", "不自动保存配置"]),
    make_skill("skill_market_research", "市场研究", "market", ["tianshang", "tiantou"], ["商品中心"], "medium", "medium", "research_only", True, ["不调用外部平台", "不投放广告"]),
    make_skill("skill_supplier_research", "供应商研究", "supplier", ["tianlian"], ["供应链找厂中心"], "medium", "medium", "research_only", True, ["只读供应链候选", "不自动联系供应商"]),
    make_skill("skill_image_prompting", "图片提示词", "design", ["tianchuang"], ["设计中心"], "medium", "medium", "draft_only", True, ["只做提示词规划", "不调用图片模型"]),
]

PLUGINS = [
    make_plugin("typeless_dictation", "Typeless Dictation", "input", "Typeless", "manual_review", ["macOS"], "medium", "medium", True, ["只登记输入增强能力", "不自动安装"]),
    make_plugin("raycast", "Raycast", "productivity", "Raycast", "manual_review", ["macOS"], "medium", "medium", True, ["只读候选", "不自动启用扩展"]),
    make_plugin("obsidian", "Obsidian", "knowledge", "Obsidian", "manual_review", ["desktop"], "medium", "low", True, ["可用于知识资产规划", "不读本地文件"]),
    make_plugin("notion", "Notion", "knowledge", "Notion", "manual_review", ["web", "desktop"], "high", "medium", True, ["不连接工作区", "不写入页面"]),
    make_plugin("github_desktop", "GitHub Desktop", "development", "GitHub", "manual_review", ["desktop"], "high", "low", True, ["不自动提交", "不自动推送"]),
    make_plugin("vscode_extension", "VS Code Extension", "development", "Microsoft", "manual_review", ["desktop"], "high", "low", True, ["不自动安装插件", "不执行代码"]),
    make_plugin("browser_extension", "Browser Extension", "browser", "Browser Vendor", "manual_review", ["browser"], "high", "low", True, ["不自动安装扩展", "不自动操作网页"]),
    make_plugin("figma_plugin", "Figma Plugin", "design", "Figma", "manual_review", ["web"], "medium", "medium", True, ["不连接 Figma 项目", "只做候选评估"]),
    make_plugin("screenshot_ocr", "Screenshot OCR", "recognition", "Local Tool", "manual_review", ["desktop"], "medium", "low", True, ["不上传截图", "不读取敏感内容"]),
    make_plugin("local_file_indexer", "Local File Indexer", "knowledge", "Local Tool", "manual_review", ["desktop"], "critical", "low", True, ["禁止自动扫描文件", "必须人工确认范围"]),
]

MCPS = [
    make_mcp("github_mcp", "GitHub MCP", "代码仓库只读研究", "tianwang", "后端开发中心", "high", "read_only_candidate", True, ["不提交代码", "不创建 PR"]),
    make_mcp("filesystem_mcp", "Filesystem MCP", "文件系统候选能力", "tiancang", "知识资产中心", "critical", "blocked_first_phase", False, ["不读取本地文件", "不写文件"]),
    make_mcp("browser_mcp", "Browser MCP", "浏览器观察候选能力", "tianyan_frontend", "前端联调优化", "high", "view_only_candidate", True, ["禁止自动点击", "禁止自动填表"]),
    make_mcp("database_mcp", "Database MCP", "数据库只读候选能力", "tianshu", "数据分析中心", "critical", "blocked_first_phase", False, ["不连接数据库", "不执行查询"]),
    make_mcp("slack_mcp", "Slack MCP", "团队通知候选能力", "tiantong", "AI总指挥", "high", "blocked_first_phase", False, ["不发送消息", "不读取会话"]),
    make_mcp("notion_mcp", "Notion MCP", "知识库候选能力", "tiancang", "知识资产中心", "high", "blocked_first_phase", False, ["不连接空间", "不写入知识库"]),
    make_mcp("figma_mcp", "Figma MCP", "设计稿候选能力", "tianchuang", "设计中心", "medium", "view_only_candidate", True, ["只做候选展示", "不修改设计稿"]),
    make_mcp("playwright_mcp", "Playwright MCP", "浏览器自动化候选能力", "tianyan_frontend", "前端联调优化", "critical", "forbidden_auto_execute", False, ["禁止自动化执行", "必须人工审批"]),
]

EXTERNAL_TOOLS = [
    make_external_tool("typeless", "Typeless", "input", "Typeless", "语音输入研究", "tiandao", "AI产品经理中心", "medium", "research_only", True, ["只登记候选"]),
    make_external_tool("github", "GitHub", "development", "GitHub", "代码协作", "tianwang", "后端开发中心", "high", "read_only_candidate", True, ["不提交代码"]),
    make_external_tool("figma", "Figma", "design", "Figma", "设计协作", "tianchuang", "设计中心", "medium", "view_only_candidate", True, ["不修改设计稿"]),
    make_external_tool("notion", "Notion", "knowledge", "Notion", "知识库管理", "tiancang", "知识资产中心", "high", "blocked_first_phase", True, ["不写入空间"]),
    make_external_tool("obsidian", "Obsidian", "knowledge", "Obsidian", "本地知识管理", "tiancang", "知识资产中心", "medium", "research_only", True, ["不扫描本地库"]),
    make_external_tool("raycast", "Raycast", "productivity", "Raycast", "效率入口", "tiantong", "AI总指挥", "medium", "research_only", True, ["不启用扩展"]),
    make_external_tool("vscode", "VS Code", "development", "Microsoft", "代码编辑", "tianwang", "后端开发中心", "high", "manual_only", True, ["不自动编辑代码"]),
    make_external_tool("browser", "Browser", "browser", "Browser Vendor", "页面查看", "tianyan_frontend", "前端联调优化", "high", "view_only_candidate", True, ["不自动点击"]),
    make_external_tool("docker", "Docker", "deployment", "Docker", "容器管理", "tiandun_ops", "部署运维修复", "critical", "forbidden_auto_execute", True, ["禁止自动执行"]),
    make_external_tool("shell", "Shell", "deployment", "Operating System", "命令行能力", "tiandun_ops", "部署运维修复", "critical", "forbidden_auto_execute", True, ["禁止自动执行命令"]),
    make_external_tool("aliyun", "Aliyun", "cloud", "Aliyun", "云资源管理", "tiandun_ops", "部署运维修复", "critical", "blocked_first_phase", True, ["不连接云账号"]),
    make_external_tool("openai_api", "OpenAI API", "model", "OpenAI", "模型能力候选", "tiantong", "AI总指挥", "high", "blocked_first_phase", True, ["不调用模型接口"]),
    make_external_tool("gemini_api", "Gemini API", "model", "Google", "模型能力候选", "tiantong", "AI总指挥", "high", "blocked_first_phase", True, ["不调用模型接口"]),
    make_external_tool("claude_api", "Claude API", "model", "Anthropic", "模型能力候选", "tiantong", "AI总指挥", "high", "blocked_first_phase", True, ["不调用模型接口"]),
    make_external_tool("1688_search", "1688 Search", "supplier", "1688", "供应商搜索", "tianlian", "供应链找厂中心", "medium", "research_only", True, ["不自动联系供应商"]),
    make_external_tool("jd_data", "JD Data", "ecommerce", "JD", "电商数据研究", "tianshang", "商品中心", "medium", "research_only", True, ["不连接账号"]),
    make_external_tool("taobao_data", "Taobao Data", "ecommerce", "Taobao", "电商数据研究", "tianshang", "商品中心", "medium", "research_only", True, ["不连接账号"]),
    make_external_tool("xiaohongshu_search", "Xiaohongshu Search", "content", "Xiaohongshu", "内容趋势研究", "tianyu", "GEO品牌增长中心", "medium", "research_only", True, ["不自动发布内容"]),
    make_external_tool("tiktok_search", "TikTok Search", "content", "TikTok", "海外内容趋势研究", "tianyu", "GEO品牌增长中心", "medium", "research_only", True, ["不自动发布内容"]),
]

EMPLOYEE_BINDINGS = [
    {
        "employee_code": "tiantong",
        "employee_name": "天统：AI总指挥",
        "department": "AI总指挥",
        "recommended_skills": ["skill_prompt_engineering", "skill_sop_generation"],
        "recommended_plugins": ["raycast"],
        "recommended_mcps": [],
        "recommended_external_tools": ["openai_api", "gemini_api", "claude_api"],
        "forbidden_tools": ["shell", "docker", "aliyun"],
        "boss_confirm_required_tools": ["openai_api", "gemini_api", "claude_api"],
    },
    {
        "employee_code": "tianwang",
        "employee_name": "天王：后端开发中心",
        "department": "后端开发中心",
        "recommended_skills": ["skill_backend_debug"],
        "recommended_plugins": ["github_desktop", "vscode_extension"],
        "recommended_mcps": ["github_mcp"],
        "recommended_external_tools": ["github", "vscode"],
        "forbidden_tools": ["payment", "aliyun"],
        "boss_confirm_required_tools": ["github", "vscode"],
    },
    {
        "employee_code": "tianyan_frontend",
        "employee_name": "天颜：前端联调优化",
        "department": "前端联调优化",
        "recommended_skills": ["skill_frontend_debug"],
        "recommended_plugins": ["browser_extension", "screenshot_ocr"],
        "recommended_mcps": ["browser_mcp"],
        "recommended_external_tools": ["browser"],
        "forbidden_tools": ["browser_click", "browser_form_fill"],
        "boss_confirm_required_tools": ["browser"],
    },
    {
        "employee_code": "tiandun_ops",
        "employee_name": "天盾：部署运维修复",
        "department": "部署运维修复",
        "recommended_skills": ["skill_deploy_check"],
        "recommended_plugins": [],
        "recommended_mcps": [],
        "recommended_external_tools": ["docker", "shell", "aliyun"],
        "forbidden_tools": ["docker", "shell", "aliyun"],
        "boss_confirm_required_tools": ["docker", "shell", "aliyun"],
    },
    {
        "employee_code": "tianjian_audit",
        "employee_name": "天监：AI审计中心",
        "department": "AI审计中心",
        "recommended_skills": ["skill_security_review"],
        "recommended_plugins": [],
        "recommended_mcps": [],
        "recommended_external_tools": ["github"],
        "forbidden_tools": ["shell", "docker"],
        "boss_confirm_required_tools": ["github"],
    },
    {
        "employee_code": "tiancang",
        "employee_name": "天藏：知识资产中心",
        "department": "知识资产中心",
        "recommended_skills": ["skill_sop_generation"],
        "recommended_plugins": ["obsidian", "notion"],
        "recommended_mcps": ["notion_mcp"],
        "recommended_external_tools": ["notion", "obsidian"],
        "forbidden_tools": ["filesystem_mcp"],
        "boss_confirm_required_tools": ["notion", "notion_mcp"],
    },
    {
        "employee_code": "tianlian",
        "employee_name": "天链：供应链找厂中心",
        "department": "供应链找厂中心",
        "recommended_skills": ["skill_supplier_research"],
        "recommended_plugins": [],
        "recommended_mcps": [],
        "recommended_external_tools": ["1688_search"],
        "forbidden_tools": ["payment"],
        "boss_confirm_required_tools": ["1688_search"],
    },
]


def department_bindings() -> list[dict]:
    departments: dict[str, dict[str, set[str]]] = {}
    for employee in EMPLOYEE_BINDINGS:
        department = employee["department"]
        data = departments.setdefault(
            department,
            {
                "recommended_skills": set(),
                "recommended_plugins": set(),
                "recommended_mcps": set(),
                "recommended_external_tools": set(),
                "forbidden_tools": set(),
            },
        )
        for key in data:
            for value in employee.get(key, []):
                data[key].add(value)
    return [
        {
            "department": department,
            "recommended_skills": sorted(values["recommended_skills"]),
            "recommended_plugins": sorted(values["recommended_plugins"]),
            "recommended_mcps": sorted(values["recommended_mcps"]),
            "recommended_external_tools": sorted(values["recommended_external_tools"]),
            "forbidden_tools": sorted(values["forbidden_tools"]),
        }
        for department, values in sorted(departments.items())
    ]


RISK_TOOLS = [
    {
        "tool_code": "shell",
        "tool_name": "Shell",
        "risk_type": "system_execution",
        "risk_level": "critical",
        "forbidden_reason": "命令行能力具备系统级风险，第一阶段永久禁止自动执行。",
        "can_auto_execute": False,
    },
    {
        "tool_code": "docker",
        "tool_name": "Docker",
        "risk_type": "deployment_execution",
        "risk_level": "critical",
        "forbidden_reason": "容器管理能力可能影响线上服务，第一阶段只登记不执行。",
        "can_auto_execute": False,
    },
    {
        "tool_code": "github_commit_push",
        "tool_name": "GitHub Commit / Push",
        "risk_type": "code_submission",
        "risk_level": "critical",
        "forbidden_reason": "代码提交必须人工确认。",
        "can_auto_execute": False,
    },
    {
        "tool_code": "browser_click_form_fill",
        "tool_name": "Browser Click / Form Fill",
        "risk_type": "browser_automation",
        "risk_level": "high",
        "forbidden_reason": "浏览器点击和填表可能产生真实业务动作。",
        "can_auto_execute": False,
    },
    {
        "tool_code": "payment_ad_budget",
        "tool_name": "Payment / Ad Budget Modify",
        "risk_type": "money_spending",
        "risk_level": "critical",
        "forbidden_reason": "涉及资金或预算，禁止自动执行。",
        "can_auto_execute": False,
    },
    {
        "tool_code": "account_credential_management",
        "tool_name": "Account Credential Management",
        "risk_type": "credential_control",
        "risk_level": "critical",
        "forbidden_reason": "账号能力必须人工管理，不能自动赋权。",
        "can_auto_execute": False,
    },
]

MISSING_CONFIGS = [
    {
        "target_type": "employee",
        "target_code": "tianzhi",
        "missing_fields": ["recommended_skills", "recommended_mcps"],
        "suggested_fix": "补充 AI 训练中心可研究 Skill，但暂不接入真实模型训练。",
        "risk_level": "medium",
    },
    {
        "target_type": "plugin",
        "target_code": "local_file_indexer",
        "missing_fields": ["file_scope_policy", "manual_review_rule"],
        "suggested_fix": "明确文件范围和人工复核规则后才能继续评估。",
        "risk_level": "critical",
    },
    {
        "target_type": "mcp",
        "target_code": "database_mcp",
        "missing_fields": ["readonly_scope", "connection_policy"],
        "suggested_fix": "只允许保留候选状态，不配置真实连接。",
        "risk_level": "critical",
    },
]

NEXT_UPGRADES = [
    {
        "upgrade_code": "sprint15_skill_research_workflow",
        "title": "Skill 研究流程评分",
        "target_module": "Skill / 插件赋能中心",
        "priority": "high",
        "allowed_stage": "readonly_scoring",
        "forbidden_actions": ["auto_download", "auto_install", "auto_enable", "auto_execute"],
        "acceptance_notes": "只能增加评分和人工验收，不接入执行。",
    },
    {
        "upgrade_code": "sprint16_plugin_manual_registry",
        "title": "插件人工登记增强",
        "target_module": "插件库",
        "priority": "medium",
        "allowed_stage": "manual_registry",
        "forbidden_actions": ["auto_download", "auto_install", "auto_grant_permission"],
        "acceptance_notes": "允许人工登记更多字段，但禁止自动安装。",
    },
]


def not_found(kind: str, code: str):
    raise HTTPException(status_code=404, detail={"error": "not_found", "kind": kind, "code": safe_text(code)})


@router.get("/overview")
def get_skill_plugin_overview(request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    all_auto_disabled = len(SKILLS) + len(PLUGINS) + len(EXTERNAL_TOOLS) + len(RISK_TOOLS)
    high_risk_count = sum(1 for row in SKILLS + PLUGINS + EXTERNAL_TOOLS if row["risk_level"] in {"high", "critical"})
    high_risk_count += sum(1 for row in MCPS if row["risk_level"] in {"high", "critical"})
    return {
        "total_skills": len(SKILLS),
        "total_plugins": len(PLUGINS),
        "total_mcps": len(MCPS),
        "total_external_tools": len(EXTERNAL_TOOLS),
        "high_risk_count": high_risk_count,
        "boss_confirmation_required_count": sum(1 for row in SKILLS + PLUGINS + EXTERNAL_TOOLS if row["requires_boss_confirmation"]),
        "auto_execute_disabled_count": all_auto_disabled + len(MCPS),
        "research_candidate_count": len(SKILLS) + len(PLUGINS) + len(MCPS) + len(EXTERNAL_TOOLS),
        "missing_config_count": len(MISSING_CONFIGS),
        "safe_readonly_mode": True,
        "can_auto_execute_all": False,
        "can_auto_install_all": False,
        "can_auto_enable_all": False,
    }


@router.get("/skills")
def get_skill_plugin_skills(request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    return {"skills": SKILLS}


@router.get("/skills/{skill_code}")
def get_skill_plugin_skill(skill_code: str, request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    skill = next((row for row in SKILLS if row["skill_code"] == skill_code), None)
    if not skill:
        not_found("skill", skill_code)
    return skill


@router.get("/plugins")
def get_skill_plugin_plugins(request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    return {"plugins": PLUGINS}


@router.get("/plugins/{plugin_code}")
def get_skill_plugin_plugin(plugin_code: str, request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    plugin = next((row for row in PLUGINS if row["plugin_code"] == plugin_code), None)
    if not plugin:
        not_found("plugin", plugin_code)
    return plugin


@router.get("/mcps")
def get_skill_plugin_mcps(request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    return {"mcps": MCPS}


@router.get("/mcps/{mcp_code}")
def get_skill_plugin_mcp(mcp_code: str, request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    mcp = next((row for row in MCPS if row["mcp_code"] == mcp_code), None)
    if not mcp:
        not_found("mcp", mcp_code)
    return mcp


@router.get("/external-tools")
def get_skill_plugin_external_tools(request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    return {"external_tools": EXTERNAL_TOOLS}


@router.get("/external-tools/{tool_code}")
def get_skill_plugin_external_tool(tool_code: str, request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    tool = next((row for row in EXTERNAL_TOOLS if row["tool_code"] == tool_code), None)
    if not tool:
        not_found("external_tool", tool_code)
    return tool


@router.get("/employees")
def get_skill_plugin_employees(request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    return {"employees": EMPLOYEE_BINDINGS}


@router.get("/employees/{employee_code}")
def get_skill_plugin_employee(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    employee = next((row for row in EMPLOYEE_BINDINGS if row["employee_code"] == employee_code), None)
    if not employee:
        not_found("employee", employee_code)
    return employee


@router.get("/departments")
def get_skill_plugin_departments(request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    return {"departments": department_bindings()}


@router.get("/risk-tools")
def get_skill_plugin_risk_tools(request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    return {"risk_tools": RISK_TOOLS}


@router.get("/missing-configs")
def get_skill_plugin_missing_configs(request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    return {"missing_configs": MISSING_CONFIGS}


@router.get("/next-upgrades")
def get_skill_plugin_next_upgrades(request: Request, db: Session = Depends(get_db)):
    require_skill_plugin_user(request, db)
    return {"next_upgrades": NEXT_UPGRADES}
