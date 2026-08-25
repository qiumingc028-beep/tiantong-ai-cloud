from __future__ import annotations

KNOWLEDGE_TYPES = [
    "研究报告",
    "标准作业流程",
    "运营经验",
    "商品知识",
    "客服知识",
    "市场知识",
    "财务规则",
    "法务规则",
    "安全规则",
    "技术文档",
    "部署文档",
    "Prompt 模板",
    "培训资料",
    "其他",
]

KNOWLEDGE_STATUSES = [
    "草稿",
    "待审核",
    "审核中",
    "已驳回",
    "已批准",
    "已发布",
    "已归档",
    "已废弃",
]

KNOWLEDGE_VISIBILITIES = ["仅自己", "部门可见", "组织可见", "公开"]

KNOWLEDGE_RISK_LEVELS = ["低风险", "中风险", "高风险", "极高风险"]

KNOWLEDGE_SOURCE_KINDS = [
    "Research Execution",
    "Research Report",
    "Research Source",
    "Research Evidence",
    "Task Center Task",
    "Agent Execution",
    "人工上传来源",
    "内部已有知识",
]

KNOWLEDGE_TAG_GROUPS = ["分类", "部门", "业务", "风险", "来源"]

ALLOWED_SUBMITTER_EMPLOYEE_CODES = {"tiancai_data", "tiancai"}
ALLOWED_REVIEWER_EMPLOYEE_CODES = {"tiancang"}
ALLOWED_PUBLISHER_EMPLOYEE_CODES = {"tiancang"}
ALLOWED_ARCHIVER_EMPLOYEE_CODES = {"tiancang"}

FEATURE_FLAGS = {
    "KNOWLEDGE_CENTER_ENABLED": False,
    "KNOWLEDGE_SUBMISSION_ENABLED": False,
    "KNOWLEDGE_PUBLISH_ENABLED": False,
    "KNOWLEDGE_LOCAL_SEARCH_ENABLED": False,
    "KNOWLEDGE_VECTOR_SEARCH_ENABLED": False,
}

DEFAULT_CATEGORY_SUGGESTIONS = {
    "研究报告": "研究报告",
    "SOP": "标准作业流程",
    "Prompt": "Prompt 模板",
    "Bug": "技术文档",
    "客服": "客服知识",
    "财务": "财务规则",
    "法务": "法务规则",
    "安全": "安全规则",
    "技术": "技术文档",
}

DEFAULT_TAGS = {
    "研究报告": ["研究", "证据链"],
    "标准作业流程": ["SOP", "流程"],
    "运营经验": ["运营", "经验"],
    "商品知识": ["商品", "运营"],
    "客服知识": ["客服", "服务"],
    "市场知识": ["市场", "研究"],
    "财务规则": ["财务", "规则"],
    "法务规则": ["法务", "规则"],
    "安全规则": ["安全", "规则"],
    "技术文档": ["技术", "文档"],
    "部署文档": ["部署", "运维"],
    "Prompt 模板": ["Prompt", "模板"],
    "培训资料": ["培训", "学习"],
    "其他": ["知识"],
}
