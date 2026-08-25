from __future__ import annotations

from typing import Final


RESEARCH_EXECUTION_STATUS_LABELS: Final[dict[str, str]] = {
    "draft": "草稿",
    "planned": "已规划",
    "searching": "搜索中",
    "collecting": "采集中",
    "deduplicating": "去重中",
    "verifying": "交叉验证中",
    "reporting": "报告生成中",
    "success": "执行成功",
    "failed": "执行失败",
    "cancelled": "已取消",
    "timeout": "已超时",
    "resource_limited": "达到资源上限",
}

SOURCE_TYPE_LABELS: Final[dict[str, str]] = {
    "government": "政府或监管机构",
    "official_company": "官方企业网站",
    "official_docs": "官方产品文档",
    "academic": "学术论文",
    "industry_association": "行业协会",
    "news_media": "主流新闻媒体",
    "professional_db": "专业数据库",
    "ecommerce_public": "电商平台公开页面",
    "social_media": "社交媒体",
    "forum_blog": "论坛和个人博客",
    "unknown": "未知来源",
}

SOURCE_CONFIDENCE_LABELS: Final[tuple[str, ...]] = ("高", "中", "低", "无法判断")

EXTERNAL_CONTENT_INSTRUCTION_DETECTED = "EXTERNAL_CONTENT_INSTRUCTION_DETECTED"
