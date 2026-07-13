from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from ..agent_runtime.models import AgentExecution
from ..models import TaskCenterTask
from .deduplicator import canonicalize_url
from .identity import stable_research_id
from .models import ResearchClaim, ResearchEvidence, ResearchExecution, ResearchQuery, ResearchSource
from .planner import build_research_plan
from .schemas import ResearchTaskInput
from .search_executor import execute_research_workflow
from .source_ranker import classify_source, score_source


def run_research_execution(payload: dict[str, object], *, trace_id: str, browser_reader) -> dict[str, object]:
    return execute_research_workflow(payload, trace_id=trace_id, browser_reader=browser_reader)


def _upsert_row(db: Session, model, identity: str, defaults: dict[str, object]):
    pk_name = model.__mapper__.primary_key[0].key
    row = db.get(model, identity)
    if row is None:
        row = model(**{pk_name: identity, **defaults})
        db.add(row)
        return row
    for key, value in defaults.items():
        setattr(row, key, value)
    return row


def _build_identity_maps(execution_id: str, plan, output_payload: dict[str, object]) -> dict[str, dict[str, str]]:
    queries = list(plan.queries[: plan.max_queries])
    source_rows = list(output_payload.get("sources") or [])
    evidence_rows = list(output_payload.get("evidence") or [])
    claims = list(output_payload.get("core_conclusions") or [])
    query_id_map = {query_text: stable_research_id(execution_id, "query", index, query_text) for index, query_text in enumerate(queries, start=1)}
    source_id_map: dict[str, str] = {}
    claim_id_map: dict[str, str] = {}
    evidence_id_map: dict[str, str] = {}
    for index, row in enumerate(source_rows, start=1):
        url = str(row.get("url") or row.get("source_url") or "")
        title = str(row.get("title") or "")
        source_id_map[url] = stable_research_id(execution_id, "source", url, title, index)
    for index, claim_text in enumerate(claims, start=1):
        claim_id_map[claim_text] = stable_research_id(execution_id, "claim", index, claim_text)
    for index, row in enumerate(evidence_rows, start=1):
        raw_url = str(row.get("raw_url") or row.get("redacted_url") or "")
        source_id = str(row.get("source_id") or source_id_map.get(raw_url) or stable_research_id(execution_id, "source", raw_url, raw_url, index))
        evidence_id_map[raw_url or f"evidence-{index}"] = stable_research_id(execution_id, "evidence", source_id, raw_url, index)
    return {
        "query_id_map": query_id_map,
        "source_id_map": source_id_map,
        "claim_id_map": claim_id_map,
        "evidence_id_map": evidence_id_map,
    }


def persist_research_result(db: Session, execution: AgentExecution, input_payload: dict[str, object], output_payload: dict[str, object]) -> None:
    request = ResearchTaskInput.model_validate(input_payload)
    plan = build_research_plan(request)
    identity_maps = _build_identity_maps(execution.execution_id, plan, output_payload)
    record = db.get(ResearchExecution, execution.execution_id)
    if not record:
        record = ResearchExecution(
            execution_id=execution.execution_id,
            task_id=execution.task_id,
            employee_id=execution.employee_id,
            capability_id=execution.capability_id,
            status=execution.status,
            risk_level=execution.risk_level,
            approval_status=execution.approval_status,
            executor_type=execution.executor_type,
            research_topic=plan.topic,
            research_goal=plan.goal,
            plan_json=json.dumps({"plan": plan.model_dump(), "identity_maps": identity_maps}, ensure_ascii=False),
            trace_id=execution.trace_id,
            created_by_id=execution.created_by_id,
            started_at=execution.started_at,
            finished_at=execution.finished_at,
            duration_ms=execution.duration_ms,
        )
        db.add(record)
    record.status = execution.status
    record.risk_level = execution.risk_level
    record.approval_status = execution.approval_status
    record.executor_type = execution.executor_type
    record.research_topic = plan.topic
    record.research_goal = plan.goal
    record.plan_json = json.dumps(
        {
            "plan": output_payload.get("plan") or plan.model_dump(),
            "identity_maps": identity_maps,
            "output_summary": {
                "query_count": int(output_payload.get("query_count") or 0),
                "source_count": int(output_payload.get("source_count") or 0),
                "duplicate_count": int(output_payload.get("duplicate_count") or 0),
            },
        },
        ensure_ascii=False,
    )
    record.query_count = int(output_payload.get("query_count") or 0)
    record.source_count = int(output_payload.get("source_count") or 0)
    record.valid_source_count = int(output_payload.get("source_count") or 0)
    record.duplicate_count = int(output_payload.get("duplicate_count") or 0)
    record.conclusion_count = len(output_payload.get("core_conclusions") or [])
    record.conflict_count = len(output_payload.get("conflicts") or [])
    record.uncertainty_count = len(output_payload.get("uncertainties") or [])
    record.report_title = str(output_payload.get("report_title") or "公开信息研究报告")
    record.report_content = str(output_payload.get("report_content") or "")
    record.report_hash = str(output_payload.get("report_hash") or "")
    record.error_code = execution.error_code
    record.error_message = execution.error_message
    record.trace_id = execution.trace_id
    record.started_at = execution.started_at
    record.finished_at = execution.finished_at
    record.duration_ms = execution.duration_ms
    db.flush()

    queries = list(plan.queries[: plan.max_queries])
    for index, query_text in enumerate(queries, start=1):
        query_id = identity_maps["query_id_map"][query_text]
        query_row = _upsert_row(
            db,
            ResearchQuery,
            query_id,
            {
                "execution_id": execution.execution_id,
                "query_text": query_text,
                "language": plan.language,
                "time_range": plan.time_range,
                "provider_name": str(output_payload.get("query_plan", {}).get("provider") or "mock"),
                "allow_domains_json": json.dumps(plan.allowed_domains, ensure_ascii=False),
                "blocked_domains_json": json.dumps(plan.blocked_domains, ensure_ascii=False),
                "result_count": int(output_payload.get("source_count") or 0),
                "status": "collected",
            },
        )
        query_row.execution_id = execution.execution_id

    source_rows = output_payload.get("sources") or []
    sources_by_url: dict[str, dict[str, object]] = {}
    for row in source_rows:
        url = str(row.get("url") or row.get("source_url") or "")
        if not url:
            continue
        sources_by_url[url] = row
    for idx, row in enumerate(sources_by_url.values(), start=1):
        url = str(row.get("url"))
        source_domain = _extract_domain(url)
        tmp_source = _SearchSourceLike(
            source_domain=source_domain,
            title=str(row.get("title") or ""),
            summary=str(row.get("confidence_reason") or ""),
            url=url,
            published_at=None,
            search_rank=idx,
            provider="mock",
            query="",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        classified = classify_source(tmp_source)
        ranked = score_source(tmp_source, classified)
        source_id = identity_maps["source_id_map"].get(url) or str(row.get("source_id") or stable_research_id(execution.execution_id, "source", url, row.get("title") or "", idx))
        source_row = _upsert_row(
            db,
            ResearchSource,
            source_id,
            {
                "execution_id": execution.execution_id,
                "query_id": identity_maps["query_id_map"].get(queries[0]) if queries else None,
                "source_url": url,
                "normalized_url": canonicalize_url(url),
                "redacted_url": str(row.get("redacted_url") or url),
                "title": str(row.get("title") or ""),
                "source_domain": source_domain,
                "source_type": str(row.get("source_type") or classified),
                "confidence_level": str(row.get("confidence_level") or ranked.confidence_level),
                "confidence_score": int(row.get("confidence_score") or ranked.confidence_score),
                "confidence_reason": str(row.get("confidence_reason") or ranked.confidence_reason),
                "publication_date": None,
                "retrieved_at": datetime.now(timezone.utc),
                "content_hash": str(row.get("content_hash") or ""),
                "summary": str(row.get("summary") or ""),
                "content_excerpt": str(row.get("summary") or ""),
                "is_primary": bool(row.get("is_primary", True)),
                "duplicate_of_source_id": row.get("duplicate_of_source_id"),
                "provider_name": str(row.get("provider_name") or row.get("provider") or "mock"),
                "validation_status": "已交叉验证",
            },
        )
        source_row.execution_id = execution.execution_id

    claims = output_payload.get("core_conclusions") or []
    for idx, claim_text in enumerate(claims, start=1):
        claim_id = identity_maps["claim_id_map"].get(str(claim_text)) or stable_research_id(execution.execution_id, "claim", idx, claim_text)
        claim_row = _upsert_row(
            db,
            ResearchClaim,
            claim_id,
            {
                "execution_id": execution.execution_id,
                "claim_text": str(claim_text),
                "claim_status": "verified",
                "validation_status": "已交叉验证" if len(source_rows) >= plan.min_sources else "单一来源",
                "confidence_level": "高" if len(source_rows) >= plan.min_sources else "低",
                "confidence_score": 80 if len(source_rows) >= plan.min_sources else 45,
                "support_source_count": len(source_rows),
                "conflict_source_count": len(output_payload.get("conflicts") or []),
                "support_source_ids_json": json.dumps([identity_maps["source_id_map"].get(str(row.get("url") or row.get("source_url") or "")) or str(row.get("source_id") or row.get("url")) for row in source_rows], ensure_ascii=False),
                "conflict_source_ids_json": json.dumps([], ensure_ascii=False),
                "evidence_count": len(source_rows),
            },
        )
        claim_row.execution_id = execution.execution_id

    evidence_rows = output_payload.get("evidence") or []
    for idx, row in enumerate(evidence_rows, start=1):
        raw_url = str(row.get("raw_url") or row.get("redacted_url") or "")
        source_id = str(row.get("source_id") or identity_maps["source_id_map"].get(raw_url) or stable_research_id(execution.execution_id, "source", raw_url, row.get("page_title") or "", idx))
        evidence_id = str(row.get("evidence_id") or identity_maps["evidence_id_map"].get(raw_url) or stable_research_id(execution.execution_id, "evidence", source_id, raw_url, idx))
        claim_text = str(claims[0]) if claims else ""
        claim_id = identity_maps["claim_id_map"].get(claim_text) if claim_text else None
        evidence_row = _upsert_row(
            db,
            ResearchEvidence,
            evidence_id,
            {
                "execution_id": execution.execution_id,
                "task_id": execution.task_id,
                "source_id": source_id,
                "claim_id": claim_id,
                "raw_url": raw_url,
                "redacted_url": str(row.get("redacted_url") or row.get("raw_url") or ""),
                "page_title": str(row.get("page_title") or ""),
                "source_type": str(row.get("source_type") or "unknown"),
                "confidence_level": str(row.get("confidence_level") or "无法判断"),
                "citation_summary": str(row.get("evidence_summary") or ""),
                "evidence_content_hash": str(row.get("evidence_content_hash") or ""),
                "collected_at": row.get("collected_at") if isinstance(row.get("collected_at"), datetime) else datetime.now(timezone.utc),
                "published_at": row.get("published_at") if isinstance(row.get("published_at"), datetime) else None,
                "relation_type": str(row.get("relation_type") or "support"),
                "validation_status": str(row.get("validation_status") or "已交叉验证"),
                "trace_id": str(row.get("trace_id") or execution.trace_id),
            },
        )
        evidence_row.execution_id = execution.execution_id

    task = db.get(TaskCenterTask, execution.task_id) if execution.task_id else None
    if task and output_payload.get("report_content"):
        note = f"[V2 Research] {record.report_title or '公开信息研究报告'}: {output_payload['report_hash']}"
        task.summary = ((task.summary or "") + ("\n" if task.summary else "") + note).strip()
        task.split_plan = task.split_plan or json.dumps(plan.model_dump(), ensure_ascii=False)
    db.flush()


def _extract_domain(url: str) -> str:
    if "//" not in url:
        return ""
    return url.split("//", 1)[1].split("/", 1)[0]


class _SearchSourceLike:
    def __init__(
        self,
        *,
        source_domain: str,
        title: str,
        summary: str,
        url: str,
        published_at,
        search_rank: int,
        provider: str,
        query: str,
        fetched_at: str,
    ) -> None:
        self.source_domain = source_domain
        self.title = title
        self.summary = summary
        self.url = url
        self.published_at = published_at
        self.search_rank = search_rank
        self.provider = provider
        self.query = query
        self.fetched_at = fetched_at
