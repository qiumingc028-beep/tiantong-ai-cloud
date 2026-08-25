from __future__ import annotations

from datetime import datetime, timezone

from ..config import get_settings
from .deduplicator import deduplicate_sources
from .planner import build_research_plan
from .prompt_guard import scan_browser_output
from .query_builder import build_queries
from .report_builder import build_report
from .schemas import ResearchTaskInput
from .search_registry import resolve_search_provider
from .source_ranker import RankedSource, classify_source, score_source
from .verifier import cross_validate


def execute_research_workflow(payload: dict[str, object], *, trace_id: str, browser_reader) -> dict[str, object]:
    request = ResearchTaskInput.model_validate(payload)
    plan = build_research_plan(request)
    provider = resolve_search_provider()
    queries = build_queries(plan)
    settings = get_settings()
    all_results = []
    for query in queries:
        results = provider.search(
            query=query,
            language=plan.language,
            time_range=plan.time_range,
            source_count=max(1, min(plan.max_sources, settings.PUBLIC_SEARCH_MAX_RESULTS_PER_QUERY)),
            allowed_domains=plan.allowed_domains,
            blocked_domains=plan.blocked_domains,
            safe_search=True,
            trace_id=trace_id,
        )
        all_results.extend(results)
    ranked = [score_source(item, classify_source(item)) for item in all_results]
    deduped = deduplicate_sources(ranked)
    unique_ranked = [group.primary for group in deduped][: plan.max_sources]
    reports = []
    security_events: list[str] = []
    for ranked_source in unique_ranked:
        browser_output = browser_reader(ranked_source.result.url, trace_id=trace_id, allowed_domains=plan.allowed_domains, blocked_domains=plan.blocked_domains)
        reports.append(browser_output)
        security_events.extend(scan_browser_output(browser_output))
    claims, conflicts = cross_validate(deduped, minimum_sources=plan.min_sources)
    uncertainties = []
    if len(deduped) < plan.min_sources:
        uncertainties.append("候选来源数量不足，结论置信度有限")
    if security_events:
        uncertainties.append("检测到疑似外部内容指令注入，已按数据处理未执行外部指令")
    output = build_report(
        topic=plan.topic,
        goal=plan.goal,
        queries=queries,
        sources=unique_ranked,
        claims=claims,
        conflicts=conflicts,
        uncertainties=uncertainties,
        security_events=security_events,
        trace_id=trace_id,
    )
    payload = dict(output)
    payload["browser_reads"] = reports
    payload["plan"] = plan.model_dump()
    payload["source_count"] = len(unique_ranked)
    payload["duplicate_count"] = sum(len(group.duplicates) for group in deduped)
    payload["query_count"] = len(queries)
    payload["collected_at"] = datetime.now(timezone.utc).isoformat()
    payload["security_events"] = security_events
    payload["external_content_instruction_detected"] = bool(security_events)
    return payload
