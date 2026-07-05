from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db


router = APIRouter()

PRIVILEGED_ROLES = {"owner", "admin"}
PERMISSION_LEVELS = {"view_only", "draft_only", "boss_confirm_required", "manual_execute_only", "automation_candidate", "forbidden"}
RISK_LEVELS = {"low", "medium", "high", "critical"}


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
        for key in ("reason", "message", "title", "text", "name", "code", "tool_code", "employee_code", "category_code"):
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


def require_tool_permission_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in PRIVILEGED_ROLES:
        raise HTTPException(status_code=403, detail="no tool permission center permission")
    return user


CATEGORIES = [
    ("model_tools", "模型工具", "模型推荐、推理、生成和检索类工具", "high", "boss_confirm_required", ["第一阶段只展示，不真实调用模型。"]),
    ("development_tools", "开发工具", "代码、测试、构建和代码托管相关工具", "high", "draft_only", ["可生成草稿或查看结果，不自动提交代码。"]),
    ("deployment_tools", "部署工具", "部署、容器、服务和回滚相关工具", "critical", "boss_confirm_required", ["真实部署必须人工确认，第一阶段禁止执行。"]),
    ("browser_tools", "浏览器工具", "浏览器查看、点击、填写、上传下载相关工具", "high", "view_only", ["第一阶段只允许查看类能力，不自动操作浏览器。"]),
    ("ecommerce_tools", "电商工具", "店铺、商品、订单、广告和平台数据相关工具", "high", "view_only", ["涉及店铺和广告的操作必须保持只读。"]),
    ("content_tools", "内容工具", "图片、视频、文案和商品详情页内容工具", "medium", "draft_only", ["只生成草稿，不自动发布。"]),
    ("data_tools", "数据工具", "采集、清洗、报表、指标和分析相关工具", "medium", "view_only", ["只读或生成报表草稿，不修改源数据。"]),
    ("notification_tools", "通知工具", "邮件、企业微信、飞书、短信和站内通知", "high", "boss_confirm_required", ["第一阶段不自动发送外部通知。"]),
    ("finance_security_tools", "财务与权限高风险工具", "资金、预算、权限和凭证管理工具", "critical", "forbidden", ["永久默认禁止自动执行。"]),
]


TOOLS = [
    ("gpt", "GPT", "model_tools", "通用大模型推荐", "draft_only", "medium", "medium", False, True, True, False, False, False, False, False, False, "advanced", "middle", "review_required", "claude", ["只推荐，不调用。"], "recommended_only", "接入模型调用前先接审批。"),
    ("claude", "Claude", "model_tools", "长文推理模型推荐", "draft_only", "medium", "medium", False, True, True, False, False, False, False, False, False, "advanced", "middle", "review_required", "gpt", ["只展示适配信息。"], "recommended_only", "后续接入质量评分。"),
    ("gemini", "Gemini", "model_tools", "多模态资料分析模型推荐", "draft_only", "medium", "medium", False, True, True, False, False, False, False, False, False, "advanced", "middle", "review_required", "gpt", ["不调用外部模型。"], "recommended_only", "完善多模态任务映射。"),
    ("codex", "Codex", "model_tools", "代码任务模型推荐", "boss_confirm_required", "high", "medium", True, True, True, False, False, False, False, False, False, "advanced", "senior", "security_review_required", "gpt", ["不得自动发送任务或修改代码。"], "recommended_only", "与代码审计链路绑定。"),
    ("image_generation", "图片生成模型", "model_tools", "图片生成模型推荐", "boss_confirm_required", "high", "high", True, True, True, False, False, False, False, False, False, "advanced", "middle", "review_required", "image_design", ["高成本生成必须确认。"], "recommended_only", "后续接入生成预算规则。"),
    ("video_generation", "视频生成模型", "model_tools", "视频生成模型推荐", "boss_confirm_required", "high", "high", True, True, True, False, False, False, False, False, False, "advanced", "senior", "review_required", "video_creation", ["视频生成高成本，第一阶段只读。"], "recommended_only", "接入预算审批。"),
    ("tts", "TTS", "model_tools", "语音生成模型推荐", "boss_confirm_required", "medium", "medium", True, True, True, False, False, False, False, False, False, "middle", "middle", "review_required", "copywriting", ["对外音频必须确认。"], "recommended_only", "增加品牌声线审核。"),
    ("embedding", "Embedding", "model_tools", "向量检索模型推荐", "view_only", "low", "low", False, True, False, False, False, False, False, False, False, "basic", "middle", "normal", "rerank", ["只做检索推荐展示。"], "active", "后续接知识资产索引。"),
    ("rerank", "Rerank", "model_tools", "检索重排模型推荐", "view_only", "low", "low", False, True, False, False, False, False, False, False, False, "basic", "middle", "normal", "embedding", ["只展示排序建议。"], "active", "后续接排序评估。"),
    ("github", "GitHub", "development_tools", "代码仓库查看与变更摘要", "boss_confirm_required", "high", "low", True, True, True, False, False, False, False, True, True, "advanced", "senior", "security_review_required", "code_editor", ["不自动提交或合并。"], "recommended_only", "增加 PR 只读检查。"),
    ("code_editor", "Code editor", "development_tools", "代码草稿编辑能力", "draft_only", "high", "low", True, True, True, False, False, True, False, False, True, "advanced", "senior", "security_review_required", "github", ["只生成补丁草稿。"], "recommended_only", "接入审计后再考虑执行。"),
    ("test_runner", "Test runner", "development_tools", "测试命令建议与结果记录", "automation_candidate", "medium", "low", False, True, True, False, False, False, False, False, False, "middle", "middle", "normal", "manual_test_checklist", ["第一阶段不自动运行测试。"], "recommended_only", "后续接只读测试报告。"),
    ("package_manager", "Package manager", "development_tools", "依赖管理建议", "boss_confirm_required", "high", "low", True, True, True, False, False, True, False, True, True, "advanced", "senior", "security_review_required", "build_tool", ["不自动安装依赖。"], "recommended_only", "增加依赖安全扫描。"),
    ("build_tool", "Build tool", "development_tools", "构建工具建议", "automation_candidate", "medium", "low", False, True, True, False, False, False, False, False, False, "middle", "middle", "normal", "test_runner", ["不自动构建发布。"], "recommended_only", "接入构建日志只读展示。"),
    ("deploy_center", "Deploy Center", "deployment_tools", "部署中心状态查看和部署草稿", "boss_confirm_required", "critical", "medium", True, True, True, False, False, False, False, False, True, "advanced", "senior", "security_review_required", "manual_deploy_checklist", ["真实部署必须老板确认。"], "recommended_only", "接入部署审批链路。"),
    ("docker", "Docker", "deployment_tools", "容器状态与构建建议", "forbidden", "critical", "medium", True, True, False, False, False, False, False, False, True, "advanced", "senior", "security_review_required", "deploy_center", ["禁止自动执行容器命令。"], "disabled", "保持人工运维。"),
    ("nginx", "Nginx", "deployment_tools", "Web 服务配置查看建议", "forbidden", "critical", "low", True, True, False, False, False, False, False, False, True, "advanced", "senior", "security_review_required", "deploy_center", ["禁止自动改配置。"], "disabled", "仅保留人工检查。"),
    ("systemctl", "system service", "deployment_tools", "系统服务状态建议", "forbidden", "critical", "low", True, True, False, False, False, False, False, False, True, "advanced", "senior", "security_review_required", "deploy_center", ["禁止自动控制系统服务。"], "disabled", "只做清单展示。"),
    ("shell", "command line", "deployment_tools", "命令行执行能力", "forbidden", "critical", "low", True, True, False, False, False, False, False, False, True, "advanced", "senior", "security_review_required", "deploy_center", ["禁止自动命令执行。"], "disabled", "长期默认禁用。"),
    ("rollback", "Rollback", "deployment_tools", "回滚流程建议", "boss_confirm_required", "critical", "medium", True, True, True, False, False, False, False, False, True, "advanced", "senior", "security_review_required", "deploy_center", ["回滚必须人工确认。"], "recommended_only", "接入回滚审批。"),
    ("browser_view", "browser view", "browser_tools", "浏览器页面查看", "view_only", "medium", "low", False, True, False, False, False, False, False, True, False, "basic", "middle", "normal", "manual_screenshot", ["只允许查看。"], "active", "补充截图验收。"),
    ("browser_click", "browser click", "browser_tools", "浏览器点击动作", "forbidden", "high", "low", True, True, False, False, False, False, False, True, False, "middle", "senior", "review_required", "browser_view", ["禁止自动点击。"], "disabled", "等待交互审计。"),
    ("browser_form_fill", "browser form fill", "browser_tools", "表单填写动作", "forbidden", "high", "low", True, True, False, False, False, True, False, True, True, "middle", "senior", "review_required", "browser_view", ["禁止自动填表。"], "disabled", "等待老板确认流。"),
    ("browser_upload", "browser upload", "browser_tools", "浏览器上传动作", "forbidden", "high", "low", True, True, False, False, False, True, False, True, True, "middle", "senior", "review_required", "browser_view", ["禁止自动上传。"], "disabled", "后续接文件审计。"),
    ("browser_download", "browser download", "browser_tools", "浏览器下载动作", "view_only", "medium", "low", False, True, False, False, False, False, False, True, True, "basic", "middle", "normal", "browser_view", ["下载需避免敏感资料。"], "recommended_only", "接入下载记录。"),
    ("jd_data", "京东数据", "ecommerce_tools", "京东数据查看", "view_only", "low", "low", False, True, False, False, False, False, False, True, False, "basic", "middle", "normal", "report_generation", ["只读查看。"], "active", "补充字段权限。"),
    ("taobao_data", "淘宝数据", "ecommerce_tools", "淘宝数据查看", "view_only", "low", "low", False, True, False, False, False, False, False, True, False, "basic", "middle", "normal", "report_generation", ["只读查看。"], "planned", "后续接平台授权。"),
    ("tmall_data", "天猫数据", "ecommerce_tools", "天猫数据查看", "view_only", "low", "low", False, True, False, False, False, False, False, True, False, "basic", "middle", "normal", "report_generation", ["只读查看。"], "planned", "后续接平台授权。"),
    ("pdd_data", "拼多多数据", "ecommerce_tools", "拼多多数据查看", "view_only", "low", "low", False, True, False, False, False, False, False, True, False, "basic", "middle", "normal", "report_generation", ["只读查看。"], "planned", "后续接平台授权。"),
    ("douyin_data", "抖音数据", "ecommerce_tools", "抖音数据查看", "view_only", "low", "low", False, True, False, False, False, False, False, True, False, "basic", "middle", "normal", "report_generation", ["只读查看。"], "planned", "后续接平台授权。"),
    ("kuaishou_data", "快手数据", "ecommerce_tools", "快手数据查看", "view_only", "low", "low", False, True, False, False, False, False, False, True, False, "basic", "middle", "normal", "report_generation", ["只读查看。"], "planned", "后续接平台授权。"),
    ("xiaohongshu_data", "小红书数据", "ecommerce_tools", "小红书数据查看", "view_only", "low", "low", False, True, False, False, False, False, False, True, False, "basic", "middle", "normal", "report_generation", ["只读查看。"], "planned", "后续接平台授权。"),
    ("shipinhao_data", "视频号数据", "ecommerce_tools", "视频号数据查看", "view_only", "low", "low", False, True, False, False, False, False, False, True, False, "basic", "middle", "normal", "report_generation", ["只读查看。"], "planned", "后续接平台授权。"),
    ("tiktok_data", "TikTok 数据", "ecommerce_tools", "TikTok 数据查看", "view_only", "medium", "low", False, True, False, False, False, False, False, True, False, "middle", "middle", "normal", "report_generation", ["跨境数据只读。"], "planned", "后续接平台授权。"),
    ("supplier_1688_search", "1688 供应商搜索", "ecommerce_tools", "供应商搜索和摘要", "view_only", "medium", "low", False, True, True, False, False, False, False, True, False, "middle", "middle", "normal", "supplier_analysis", ["不自动下单。"], "active", "接入供应商追溯。"),
    ("store_management", "店铺管理", "ecommerce_tools", "店铺信息查看", "view_only", "high", "low", True, True, False, False, False, True, False, True, True, "middle", "senior", "review_required", "jd_data", ["禁止自动改店铺。"], "recommended_only", "接入改动审批。"),
    ("product_management", "商品管理", "ecommerce_tools", "商品信息查看和草稿", "draft_only", "high", "low", True, True, True, False, False, True, False, True, True, "middle", "senior", "review_required", "store_management", ["不自动发布商品改动。"], "recommended_only", "接入商品审批。"),
    ("order_view", "订单查看", "ecommerce_tools", "订单信息只读查看", "view_only", "high", "low", True, True, False, False, False, False, False, True, True, "middle", "senior", "review_required", "jd_data", ["订单涉及敏感数据，只读。"], "recommended_only", "增加脱敏视图。"),
    ("ad_data_view", "广告数据查看", "ecommerce_tools", "广告数据只读查看", "view_only", "medium", "low", False, True, False, False, False, False, False, True, False, "middle", "middle", "normal", "report_generation", ["只读查看广告数据。"], "active", "接入预算风险提示。"),
    ("ad_campaign_modify", "广告投放修改", "ecommerce_tools", "广告投放和预算修改", "forbidden", "critical", "high", True, True, True, False, False, True, False, True, True, "advanced", "senior", "security_review_required", "ad_data_view", ["禁止自动改预算或投放。"], "disabled", "必须保持人工审批。"),
    ("image_design", "图片设计", "content_tools", "图片设计草稿", "draft_only", "medium", "medium", False, True, True, False, False, False, False, False, False, "middle", "middle", "normal", "image_generation", ["只生成草稿。"], "active", "接入品牌审核。"),
    ("image_editing", "图片编辑", "content_tools", "图片编辑草稿", "draft_only", "medium", "medium", False, True, True, False, False, False, False, False, False, "middle", "middle", "normal", "image_design", ["只生成草稿。"], "active", "接入素材版本。"),
    ("video_creation", "视频生成", "content_tools", "视频生成草稿", "boss_confirm_required", "high", "high", True, True, True, False, False, False, False, False, False, "advanced", "senior", "review_required", "video_editing", ["高成本视频需确认。"], "recommended_only", "接入预算审批。"),
    ("video_editing", "视频剪辑", "content_tools", "视频剪辑草稿", "draft_only", "medium", "medium", False, True, True, False, False, False, False, False, False, "middle", "middle", "normal", "video_creation", ["只生成剪辑方案。"], "active", "接入素材库。"),
    ("copywriting", "文案生成", "content_tools", "文案草稿", "draft_only", "low", "low", False, True, True, False, False, False, False, False, False, "basic", "middle", "normal", "seo_geo_content", ["不自动发布。"], "active", "接入品牌词库。"),
    ("seo_geo_content", "SEO/GEO 内容", "content_tools", "搜索和 GEO 内容草稿", "draft_only", "low", "low", False, True, True, False, False, False, False, False, False, "basic", "middle", "normal", "copywriting", ["不自动发布。"], "active", "接入排名追踪。"),
    ("xiaohongshu_content", "小红书内容", "content_tools", "小红书内容草稿", "draft_only", "medium", "low", False, True, True, False, False, False, False, False, False, "middle", "middle", "normal", "copywriting", ["不自动发布。"], "active", "接入内容审核。"),
    ("douyin_script", "抖音脚本", "content_tools", "短视频脚本草稿", "draft_only", "medium", "low", False, True, True, False, False, False, False, False, False, "middle", "middle", "normal", "copywriting", ["不自动发布。"], "active", "接入脚本评审。"),
    ("product_detail_page", "商品详情页", "content_tools", "商品详情页草稿", "draft_only", "medium", "low", False, True, True, False, False, False, False, False, False, "middle", "middle", "normal", "copywriting", ["不自动上架。"], "active", "接入商品审核。"),
    ("data_collection", "数据采集", "data_tools", "数据采集建议", "view_only", "medium", "low", False, True, False, False, False, False, False, True, False, "middle", "middle", "normal", "jd_data", ["不自动采集外部账号数据。"], "recommended_only", "接入合规检查。"),
    ("data_cleaning", "数据清洗", "data_tools", "数据清洗草稿", "draft_only", "medium", "low", False, True, True, False, False, True, False, False, False, "middle", "middle", "normal", "report_generation", ["不修改源数据。"], "active", "接入版本化输出。"),
    ("report_generation", "报表生成", "data_tools", "报表生成草稿", "draft_only", "low", "low", False, True, True, False, False, False, False, False, False, "basic", "middle", "normal", "metric_calculation", ["只生成报表草稿。"], "active", "接入定时报表审批。"),
    ("metric_calculation", "指标计算", "data_tools", "指标计算", "view_only", "low", "low", False, True, False, False, False, False, False, False, False, "basic", "middle", "normal", "report_generation", ["只读计算展示。"], "active", "接入指标定义中心。"),
    ("bestseller_analysis", "爆款分析", "data_tools", "爆款趋势分析", "draft_only", "medium", "low", False, True, True, False, False, False, False, False, False, "middle", "middle", "normal", "market_analysis", ["只输出分析建议。"], "active", "接入商品库。"),
    ("market_analysis", "市场分析", "data_tools", "市场趋势分析", "draft_only", "medium", "low", False, True, True, False, False, False, False, False, False, "middle", "middle", "normal", "bestseller_analysis", ["只输出分析建议。"], "active", "接入竞品数据。"),
    ("supplier_analysis", "供应商分析", "data_tools", "供应商信息分析", "draft_only", "medium", "low", False, True, True, False, False, False, False, True, False, "middle", "middle", "normal", "supplier_1688_search", ["不自动联系或下单。"], "active", "接入供应商评分。"),
    ("email", "邮件", "notification_tools", "邮件通知草稿", "boss_confirm_required", "high", "low", True, True, True, False, False, False, False, True, False, "middle", "senior", "review_required", "internal_notification", ["不自动发送邮件。"], "recommended_only", "接入发送审批。"),
    ("wecom", "企业微信", "notification_tools", "企业微信通知草稿", "boss_confirm_required", "high", "low", True, True, True, False, False, False, False, True, False, "middle", "senior", "review_required", "internal_notification", ["不自动发送外部消息。"], "recommended_only", "接入发送审批。"),
    ("feishu", "飞书", "notification_tools", "飞书通知草稿", "boss_confirm_required", "high", "low", True, True, True, False, False, False, False, True, False, "middle", "senior", "review_required", "internal_notification", ["不自动发送外部消息。"], "recommended_only", "接入发送审批。"),
    ("sms", "短信", "notification_tools", "短信通知草稿", "boss_confirm_required", "critical", "medium", True, True, True, False, False, False, False, True, True, "advanced", "senior", "security_review_required", "internal_notification", ["短信可能扣费，第一阶段禁止发送。"], "disabled", "保持人工确认。"),
    ("internal_notification", "站内通知", "notification_tools", "站内通知草稿", "draft_only", "medium", "low", False, True, True, False, False, False, False, False, False, "basic", "middle", "normal", "report_generation", ["不自动发送。"], "recommended_only", "接入通知审批。"),
    ("payment", "付款", "finance_security_tools", "付款操作", "forbidden", "critical", "high", True, True, False, False, False, False, False, True, True, "advanced", "senior", "security_review_required", "manual_finance_process", ["禁止自动付款。"], "disabled", "永久人工执行。"),
    ("recharge", "充值", "finance_security_tools", "账户充值操作", "forbidden", "critical", "high", True, True, False, False, False, False, False, True, True, "advanced", "senior", "security_review_required", "manual_finance_process", ["禁止自动充值。"], "disabled", "永久人工执行。"),
    ("billing", "扣费", "finance_security_tools", "费用扣减相关操作", "forbidden", "critical", "high", True, True, False, False, False, False, False, True, True, "advanced", "senior", "security_review_required", "manual_finance_process", ["禁止自动扣费。"], "disabled", "永久人工执行。"),
    ("ad_budget_modify", "广告预算修改", "finance_security_tools", "广告预算修改操作", "forbidden", "critical", "high", True, True, True, False, False, True, False, True, True, "advanced", "senior", "security_review_required", "ad_data_view", ["禁止自动改预算。"], "disabled", "必须老板确认。"),
    ("store_fund_operation", "店铺资金操作", "finance_security_tools", "店铺资金相关操作", "forbidden", "critical", "high", True, True, False, False, False, True, False, True, True, "advanced", "senior", "security_review_required", "manual_finance_process", ["禁止自动操作店铺资金。"], "disabled", "永久人工执行。"),
    ("employee_permission_modify", "员工权限修改", "finance_security_tools", "员工权限修改操作", "forbidden", "critical", "low", True, True, False, False, False, True, False, True, True, "advanced", "senior", "security_review_required", "manual_admin_process", ["禁止自动改权限。"], "disabled", "必须人工审批。"),
    ("credential_management", "账号凭证管理", "finance_security_tools", "外部账号凭证管理", "forbidden", "critical", "low", True, True, False, False, False, True, False, True, True, "advanced", "senior", "security_review_required", "manual_admin_process", ["禁止返回或修改任何凭证。"], "disabled", "永久人工处理。"),
    ("account_credential_management", "账号凭证管理", "finance_security_tools", "账号登录资料管理", "forbidden", "critical", "low", True, True, False, False, False, True, False, True, True, "advanced", "senior", "security_review_required", "manual_admin_process", ["禁止自动读取或修改登录资料。"], "disabled", "永久人工处理。"),
]


EMPLOYEE_BLUEPRINTS = [
    ("tiantong", "天统：AI总指挥", "AI总指挥", ["gpt", "claude", "report_generation"], ["payment", "billing", "shell"], ["codex", "deploy_center"], ["copywriting"], ["test_runner"]),
    ("tiandao", "天道：AI产品经理中心", "AI产品经理中心", ["gpt", "claude", "copywriting", "report_generation"], ["deploy_center", "payment"], [], ["seo_geo_content"], ["market_analysis"]),
    ("tiangong", "天工：系统架构中心", "系统架构中心", ["gpt", "claude", "code_editor", "github"], ["payment", "ad_budget_modify"], ["github"], ["code_editor"], ["test_runner"]),
    ("tianwang", "天王：后端开发中心", "后端开发中心", ["codex", "code_editor", "github", "test_runner"], ["payment", "deploy_center"], ["github", "package_manager"], ["code_editor"], ["test_runner"]),
    ("tianyan_frontend", "天颜：前端联调优化", "前端联调优化", ["codex", "code_editor", "browser_view", "test_runner"], ["payment", "shell"], ["browser_click"], ["image_design"], ["test_runner"]),
    ("tianjian_test", "天检：测试验收中心", "测试验收中心", ["test_runner", "report_generation", "browser_view"], ["payment", "deploy_center"], [], ["report_generation"], ["test_runner"]),
    ("tianjian_audit", "天监：AI审计中心", "AI审计中心", ["github", "code_editor", "report_generation"], ["payment", "ad_campaign_modify"], ["github", "code_editor"], ["report_generation"], ["test_runner"]),
    ("tiandun_ops", "天盾：部署运维修复", "部署运维修复", ["deploy_center", "rollback", "report_generation"], ["payment", "billing"], ["deploy_center", "rollback"], [], []),
    ("tiandun_deploy", "天盾：Deploy Center", "部署中心", ["deploy_center", "rollback"], ["payment", "billing"], ["deploy_center", "rollback"], [], []),
    ("tianshang", "天商：商品中心", "商品中心", ["jd_data", "product_management", "order_view", "copywriting"], ["payment", "ad_budget_modify"], ["product_management", "order_view"], ["product_detail_page"], ["bestseller_analysis"]),
    ("tianchuang", "天创：设计中心", "设计中心", ["image_design", "image_editing", "image_generation"], ["payment", "deploy_center"], ["image_generation"], ["image_design"], ["image_editing"]),
    ("tianbo", "天播：视频中心", "视频中心", ["video_creation", "video_editing", "video_generation"], ["payment", "deploy_center"], ["video_creation", "video_generation"], ["douyin_script"], []),
    ("tiancai_data", "天采：数据采集平台", "数据采集平台", ["data_collection", "jd_data", "supplier_1688_search"], ["payment", "ad_budget_modify"], [], ["data_cleaning"], ["report_generation"]),
    ("tianshu", "天数：数据分析中心", "数据分析中心", ["data_cleaning", "report_generation", "metric_calculation", "market_analysis"], ["payment", "deploy_center"], [], ["bestseller_analysis"], ["report_generation"]),
    ("tiantou", "天投：广告投放中心", "广告投放中心", ["ad_data_view", "report_generation", "market_analysis"], ["payment", "billing"], ["ad_campaign_modify", "ad_budget_modify"], ["copywriting"], ["market_analysis"]),
    ("tianfu", "天服：客服中心", "客服中心", ["copywriting", "order_view", "internal_notification"], ["payment", "ad_budget_modify"], ["order_view"], ["email"], ["internal_notification"]),
    ("tianyu", "天誉：GEO/SEO品牌增长中心", "GEO/SEO品牌增长中心", ["seo_geo_content", "copywriting", "rerank", "embedding"], ["payment", "deploy_center"], [], ["seo_geo_content"], ["report_generation"]),
    ("tiancang", "天藏：知识资产中心", "知识资产中心", ["embedding", "rerank", "report_generation"], ["payment", "ad_campaign_modify"], [], ["copywriting"], ["report_generation"]),
    ("tianzhi", "天智：AI训练中心", "AI训练中心", ["gpt", "claude", "gemini", "report_generation"], ["payment", "deploy_center"], ["codex"], ["report_generation"], ["test_runner"]),
    ("tianlian", "天链：供应链找厂中心", "供应链找厂中心", ["supplier_1688_search", "supplier_analysis", "market_analysis"], ["payment", "billing"], [], ["supplier_analysis"], ["report_generation"]),
]


def build_categories() -> list[dict]:
    return [
        {
            "category_code": safe_text(code),
            "category_name": safe_text(name),
            "description": safe_text(description),
            "risk_level": safe_text(risk),
            "default_permission_level": safe_text(permission),
            "safety_notes": safe_text_list(notes),
        }
        for code, name, description, risk, permission, notes in CATEGORIES
    ]


def build_tools() -> list[dict]:
    return [ensure_tool_shape(row) for row in TOOLS]


def ensure_tool_shape(row: tuple) -> dict:
    (
        code,
        name,
        category,
        description,
        permission,
        risk,
        cost,
        confirm,
        can_read,
        can_draft,
        can_execute,
        can_auto,
        can_modify,
        can_spend,
        external,
        sensitive,
        model_level,
        maturity,
        audit,
        fallback,
        notes,
        status,
        suggestion,
    ) = row
    risk = safe_text(risk)
    if can_spend:
        risk = "critical"
    if can_modify and risk not in {"high", "critical"}:
        risk = "high"
    if sensitive and risk not in {"high", "critical"}:
        risk = "high"
    confirm = bool(confirm or risk == "critical")
    return {
        "tool_code": safe_text(code),
        "tool_name": safe_text(name),
        "tool_category": safe_text(category),
        "description": safe_text(description),
        "allowed_employees": employees_for_tool(safe_text(code)),
        "forbidden_employees": forbidden_employees_for_tool(safe_text(code)),
        "allowed_departments": departments_for_tool(safe_text(code)),
        "forbidden_departments": [],
        "permission_level": safe_text(permission) if permission in PERMISSION_LEVELS else "view_only",
        "risk_level": risk if risk in RISK_LEVELS else "medium",
        "cost_level": safe_text(cost),
        "requires_boss_confirmation": confirm,
        "can_read": bool(can_read),
        "can_generate_draft": bool(can_draft),
        "can_execute": False,
        "can_auto_execute": False,
        "can_modify_data": bool(can_modify),
        "can_spend_money": False,
        "can_access_external_account": bool(external),
        "can_access_sensitive_data": bool(sensitive),
        "required_model_level": safe_text(model_level),
        "required_employee_maturity": safe_text(maturity),
        "required_audit_level": safe_text(audit),
        "fallback_tool": safe_text(fallback),
        "safety_notes": safe_text_list(notes),
        "current_status": safe_text(status),
        "next_upgrade_suggestion": safe_text(suggestion),
    }


def build_employees() -> list[dict]:
    tools = build_tools()
    tool_codes = {row["tool_code"] for row in tools}
    rows = []
    for code, name, department, allowed, forbidden, high_risk, draft_only, candidates in EMPLOYEE_BLUEPRINTS:
        allowed_list = safe_text_list(allowed)
        forbidden_list = sorted(set(safe_text_list(forbidden)) | (tool_codes - set(allowed_list) - set(high_risk) - set(draft_only) - set(candidates)))
        high_list = safe_text_list(high_risk)
        confirm_list = sorted({tool["tool_code"] for tool in tools if tool["tool_code"] in set(allowed_list + high_list) and tool["requires_boss_confirmation"]})
        rows.append(
            {
                "employee_code": safe_text(code),
                "employee_name": safe_text(name),
                "department": safe_text(department),
                "allowed_tools": allowed_list,
                "forbidden_tools": forbidden_list,
                "high_risk_tools": high_list,
                "boss_confirm_required_tools": confirm_list,
                "view_only_tools": [tool for tool in allowed_list if tool_permission(tool) == "view_only"],
                "draft_only_tools": safe_text_list(draft_only),
                "automation_candidate_tools": safe_text_list(candidates),
                "missing_tool_configs": [],
                "safety_notes": ["第一阶段只读展示，不自动授权工具。"],
                "next_upgrade_suggestion": "后续接入审批链路前保持只读。",
            }
        )
    return rows


def tool_permission(tool_code: str) -> str:
    tool = next((row for row in build_tools() if row["tool_code"] == tool_code), None)
    return tool["permission_level"] if tool else "view_only"


def employees_for_tool(tool_code: str) -> list[str]:
    return [row[0] for row in EMPLOYEE_BLUEPRINTS if tool_code in set(row[3] + row[5] + row[6] + row[7])]


def forbidden_employees_for_tool(tool_code: str) -> list[str]:
    return [row[0] for row in EMPLOYEE_BLUEPRINTS if tool_code in set(row[4])]


def departments_for_tool(tool_code: str) -> list[str]:
    return sorted({row[2] for row in EMPLOYEE_BLUEPRINTS if tool_code in set(row[3] + row[5] + row[6] + row[7])})


def count_by(rows: list[dict], key: str) -> dict:
    result: dict[str, int] = {}
    for row in rows:
        value = safe_text(row.get(key), "unknown")
        result[value] = result.get(value, 0) + 1
    return result


@router.get("/overview")
def get_tool_permissions_overview(request: Request, db: Session = Depends(get_db)):
    require_tool_permission_user(request, db)
    tools = build_tools()
    employees = build_employees()
    return {
        "total_tools": len(tools),
        "total_categories": len(build_categories()),
        "high_risk_tools": sum(1 for row in tools if row["risk_level"] == "high"),
        "critical_tools": sum(1 for row in tools if row["risk_level"] == "critical"),
        "boss_confirm_required_count": sum(1 for row in tools if row["requires_boss_confirmation"]),
        "auto_execute_disabled_count": sum(1 for row in tools if not row["can_auto_execute"]),
        "automation_candidate_count": sum(1 for row in tools if row["permission_level"] == "automation_candidate"),
        "missing_config_count": sum(len(row["missing_tool_configs"]) for row in employees),
        "employees_with_tool_profile": len(employees),
        "category_summary": count_by(tools, "tool_category"),
        "risk_summary": count_by(tools, "risk_level"),
        "safety_summary": ["全部 API 只读", "全部工具 can_execute=false", "全部工具 can_auto_execute=false", "全部工具 can_spend_money=false"],
        "next_upgrade_suggestion": "后续进入真实工具调用前必须增加老板确认、审计和回滚链路。",
    }


@router.get("/tools")
def get_tool_permissions_tools(request: Request, db: Session = Depends(get_db)):
    require_tool_permission_user(request, db)
    return {"tools": build_tools()}


@router.get("/tools/{tool_code}")
def get_tool_permissions_tool(tool_code: str, request: Request, db: Session = Depends(get_db)):
    require_tool_permission_user(request, db)
    tool = next((row for row in build_tools() if row["tool_code"] == tool_code), None)
    if not tool:
        raise HTTPException(status_code=404, detail="tool permission not found")
    return tool


@router.get("/employees")
def get_tool_permissions_employees(request: Request, db: Session = Depends(get_db)):
    require_tool_permission_user(request, db)
    return {"employees": build_employees()}


@router.get("/employees/{employee_code}")
def get_tool_permissions_employee(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_tool_permission_user(request, db)
    employee = next((row for row in build_employees() if row["employee_code"] == employee_code), None)
    if not employee:
        raise HTTPException(status_code=404, detail="employee tool permission not found")
    return employee


@router.get("/categories")
def get_tool_permissions_categories(request: Request, db: Session = Depends(get_db)):
    require_tool_permission_user(request, db)
    return {"categories": build_categories()}


@router.get("/high-risk-tools")
def get_tool_permissions_high_risk_tools(request: Request, db: Session = Depends(get_db)):
    require_tool_permission_user(request, db)
    return {"tools": [row for row in build_tools() if row["risk_level"] in {"high", "critical"}]}


@router.get("/boss-confirm-required")
def get_tool_permissions_boss_confirm_required(request: Request, db: Session = Depends(get_db)):
    require_tool_permission_user(request, db)
    return {"tools": [row for row in build_tools() if row["requires_boss_confirmation"]]}


@router.get("/auto-execute-disabled")
def get_tool_permissions_auto_execute_disabled(request: Request, db: Session = Depends(get_db)):
    require_tool_permission_user(request, db)
    return {"tools": [row for row in build_tools() if not row["can_auto_execute"]]}


@router.get("/missing-configs")
def get_tool_permissions_missing_configs(request: Request, db: Session = Depends(get_db)):
    require_tool_permission_user(request, db)
    return {"missing_configs": [row for row in build_employees() if row["missing_tool_configs"]]}


@router.get("/automation-candidates")
def get_tool_permissions_automation_candidates(request: Request, db: Session = Depends(get_db)):
    require_tool_permission_user(request, db)
    return {"tools": [row for row in build_tools() if row["permission_level"] == "automation_candidate"]}
