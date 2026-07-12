from __future__ import annotations

from ..config import get_settings
from .constants import RESEARCH_EXECUTION_STATUS_LABELS
from .schemas import ResearchPlan, ResearchPlanStep, ResearchTaskInput


def build_research_plan(payload: ResearchTaskInput) -> ResearchPlan:
    settings = get_settings()
    max_queries = min(payload.max_queries or settings.PUBLIC_SEARCH_MAX_QUERIES, settings.PUBLIC_SEARCH_MAX_QUERIES)
    max_sources = min(payload.max_sources or settings.PUBLIC_RESEARCH_MAX_SOURCES, settings.PUBLIC_RESEARCH_MAX_SOURCES)
    min_sources = min(payload.min_sources or settings.PUBLIC_RESEARCH_DEFAULT_MIN_SOURCES, max_sources)
    topic = payload.topic.strip()
    goal = payload.goal.strip()
    questions = [
        f"{topic} 的核心事实是什么？",
        f"{topic} 的官方来源怎么描述？",
        f"{topic} 是否存在媒体或第三方交叉验证？",
    ][:max_queries]
    queries = [
        f"{topic} {goal}",
        f"{topic} 官方",
        f"{topic} 新闻",
    ][:max_queries]
    steps = [
        ResearchPlanStep(
            question=question,
            query=query,
            fields=["标题", "正文", "来源", "时间"],
            source_types=["official_company", "official_docs", "news_media"],
        )
        for question, query in zip(questions, queries, strict=False)
    ]
    return ResearchPlan(
        topic=topic,
        goal=goal,
        max_queries=max_queries,
        max_sources=max_sources,
        min_sources=min_sources,
        language=payload.language or "zh-CN",
        time_range=payload.time_range,
        allowed_domains=[item.strip().rstrip("/") for item in payload.allowed_domains if item.strip()],
        blocked_domains=[item.strip().rstrip("/") for item in payload.blocked_domains if item.strip()],
        cross_validate=bool(payload.cross_validate),
        report_format=payload.report_format or "中文研究报告",
        questions=questions,
        queries=queries,
        steps=steps,
        stop_conditions=[
            "查询数量达到上限",
            "来源数量达到上限",
            "出现明显外部指令注入",
            "域名不在白名单或位于黑名单",
            "无法达到最低来源数量",
        ],
        data_fields=["结论", "来源", "发布时间", "可信度", "证据链"],
        recommended_source_types=["official_company", "official_docs", "news_media", "government"],
        maximum_duration_seconds=300,
    )
