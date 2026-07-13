from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .identity import stable_research_id
from .constants import SOURCE_TYPE_LABELS
from .schemas import ResearchEvidenceRecord
from .source_ranker import RankedSource
from .sanitizer import sanitize_url
from .deduplicator import canonicalize_url


def build_evidence_records(execution_id: str, task_id: int | None, trace_id: str, sources: list[RankedSource]) -> list[ResearchEvidenceRecord]:
    records: list[ResearchEvidenceRecord] = []
    for index, source in enumerate(sources, start=1):
        canonical_url = canonicalize_url(source.result.url)
        source_id = stable_research_id(execution_id, "source", canonical_url)
        evidence_id = stable_research_id(execution_id, "evidence", source_id, canonical_url)
        raw_url = source.result.url
        redacted = sanitize_url(raw_url)
        content_hash = hashlib.sha256(f"{raw_url}|{source.result.title}|{source.result.summary}".encode("utf-8")).hexdigest()
        records.append(
            ResearchEvidenceRecord(
                evidence_id=evidence_id,
                source_id=source_id,
                claim_id=None,
                raw_url=raw_url,
                redacted_url=redacted,
                page_title=source.result.title,
                source_type=source.source_type,
                confidence_level=source.confidence_level,
                evidence_summary=source.result.summary,
                evidence_content_hash=content_hash,
                collected_at=datetime.now(timezone.utc),
                published_at=None,
                relation_type="support",
                validation_status="已交叉验证",
                trace_id=trace_id,
            )
        )
    return records
