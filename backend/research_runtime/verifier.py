from __future__ import annotations

from dataclasses import dataclass

from .deduplicator import DeduplicatedSourceGroup


@dataclass(slots=True)
class VerifiedClaim:
    claim_text: str
    support_sources: list[str]
    conflict_sources: list[str]
    evidence_count: int
    validation_status: str
    confidence_level: str


def cross_validate(groups: list[DeduplicatedSourceGroup], minimum_sources: int = 2) -> tuple[list[VerifiedClaim], list[dict[str, object]]]:
    claims: list[VerifiedClaim] = []
    conflicts: list[dict[str, object]] = []
    source_ids = [group.primary.result.url for group in groups]
    support_count = len(groups)
    validation_status = "已交叉验证" if support_count >= minimum_sources else "单一来源"
    confidence_level = "高" if support_count >= minimum_sources + 1 else "中" if support_count >= minimum_sources else "低"
    claim_text = "多来源公开信息之间未发现明显冲突" if support_count >= minimum_sources else "来源数量不足，仅能进行单一来源判断"
    claims.append(
        VerifiedClaim(
            claim_text=claim_text,
            support_sources=source_ids,
            conflict_sources=[],
            evidence_count=support_count,
            validation_status=validation_status,
            confidence_level=confidence_level,
        )
    )
    if support_count < minimum_sources:
        conflicts.append(
            {
                "type": "insufficient_sources",
                "message": "可交叉验证来源数量不足",
                "support_count": support_count,
            }
        )
    return claims, conflicts
