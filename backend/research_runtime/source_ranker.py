from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .constants import SOURCE_TYPE_LABELS
from .schemas import SearchResult


@dataclass(slots=True)
class RankedSource:
    result: SearchResult
    source_type: str
    confidence_level: str
    confidence_score: int
    confidence_reason: str


def classify_source(result: SearchResult) -> str:
    domain = result.source_domain.lower()
    if domain.endswith(".gov") or ".gov." in domain:
        return "government"
    if "docs." in domain or domain.endswith("docs.python.org") or "documentation" in result.title.lower():
        return "official_docs"
    if domain.endswith(".edu") or "arxiv.org" in domain or "scholar" in domain:
        return "academic"
    if "reuters.com" in domain or "bloomberg.com" in domain or "news" in domain:
        return "news_media"
    if "github.com" in domain and "docs" not in result.title.lower():
        return "official_company"
    if "blog" in domain or "medium.com" in domain or "substack" in domain:
        return "forum_blog"
    if any(key in domain for key in ("jd.com", "taobao.com", "tmall.com", "1688.com")):
        return "ecommerce_public"
    return "unknown"


def score_source(result: SearchResult, source_type: str | None = None) -> RankedSource:
    source_type = source_type or classify_source(result)
    score = 40
    reason_parts = [SOURCE_TYPE_LABELS.get(source_type, source_type)]
    if source_type in {"government", "official_docs", "official_company"}:
        score += 35
        confidence_level = "高"
    elif source_type in {"academic", "news_media", "professional_db"}:
        score += 20
        confidence_level = "中"
    elif source_type in {"ecommerce_public", "social_media", "forum_blog"}:
        score += 5
        confidence_level = "低"
    else:
        confidence_level = "无法判断"
    if result.published_at:
        score += 10
        reason_parts.append("包含发布时间")
    if result.summary:
        score += 5
    score = min(100, score)
    if score >= 80:
        confidence_level = "高"
    elif score >= 60 and confidence_level == "无法判断":
        confidence_level = "中"
    elif score < 50:
        confidence_level = "低"
    return RankedSource(
        result=result,
        source_type=source_type,
        confidence_level=confidence_level,
        confidence_score=score,
        confidence_reason="；".join(reason_parts),
    )
