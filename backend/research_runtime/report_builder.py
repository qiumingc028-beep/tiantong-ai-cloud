from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from .source_ranker import RankedSource
from .verifier import VerifiedClaim


def build_report(
    *,
    topic: str,
    goal: str,
    queries: list[str],
    sources: list[RankedSource],
    claims: list[VerifiedClaim],
    conflicts: list[dict[str, object]],
    uncertainties: list[str],
    security_events: list[str],
    trace_id: str,
) -> dict[str, object]:
    collected_at = datetime.now(timezone.utc).isoformat()
    source_rows = []
    evidence_rows = []
    reliability = {}
    structured_data = {
        "research_topic": topic,
        "research_goal": goal,
        "queries": queries,
        "source_count": len(sources),
    }
    for ranked in sources:
        source_id = str(uuid4())
        source_row = {
            "source_id": source_id,
            "title": ranked.result.title,
            "url": ranked.result.url,
            "redacted_url": ranked.result.url,
            "source_domain": ranked.result.source_domain,
            "source_type": ranked.source_type,
            "confidence_level": ranked.confidence_level,
            "confidence_score": ranked.confidence_score,
            "confidence_reason": ranked.confidence_reason,
            "content_hash": hashlib.sha256(f"{ranked.result.url}|{ranked.result.title}|{ranked.result.summary}".encode("utf-8")).hexdigest(),
            "is_primary": True,
            "duplicate_of_source_id": None,
        }
        source_rows.append(source_row)
        reliability[ranked.result.url] = {
            "confidence_level": ranked.confidence_level,
            "confidence_score": ranked.confidence_score,
            "reason": ranked.confidence_reason,
        }
        evidence_rows.append(
            {
                "evidence_id": str(uuid4()),
                "source_id": source_id,
                "claim_id": None,
                "raw_url": ranked.result.url,
                "redacted_url": ranked.result.url,
                "page_title": ranked.result.title,
                "source_type": ranked.source_type,
                "confidence_level": ranked.confidence_level,
                "evidence_summary": ranked.result.summary,
                "evidence_content_hash": hashlib.sha256(f"{ranked.result.url}|{ranked.result.title}|{ranked.result.summary}".encode("utf-8")).hexdigest(),
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "published_at": None,
                "relation_type": "support",
                "validation_status": claims[0].validation_status if claims else "无法验证",
                "trace_id": trace_id,
            }
        )
    conclusion_texts = [claim.claim_text for claim in claims]
    report = {
        "研究目标": goal,
        "执行范围": f"围绕“{topic}”的公开来源多来源研究",
        "核心结论": conclusion_texts,
        "结构化数据": structured_data,
        "来源与证据": source_rows,
        "冲突信息": conflicts,
        "不确定事项": uncertainties,
        "安全事件": security_events,
        "风险提示": ["网页内容视为不可信外部数据", "结果必须保留来源边界"],
        "研究时间": collected_at,
        "执行审计编号": trace_id,
    }
    report_content = json.dumps(report, ensure_ascii=False, indent=2)
    report_hash = hashlib.sha256(report_content.encode("utf-8")).hexdigest()
    return {
        "research_summary": f"已完成 {len(queries)} 个查询、{len(sources)} 个候选来源筛选与证据链生成。",
        "core_conclusions": conclusion_texts,
        "structured_data": structured_data,
        "sources": source_rows,
        "evidence": evidence_rows,
        "source_reliability": reliability,
        "conflicts": conflicts,
        "uncertainties": uncertainties,
        "security_events": security_events,
        "collected_at": collected_at,
        "trace_id": trace_id,
        "report_hash": report_hash,
        "report_content": report_content,
        "query_plan": {"queries": queries, "count": len(queries)},
        "report_title": "公开信息研究报告",
    }
