from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from .source_ranker import RankedSource


@dataclass(slots=True)
class DeduplicatedSourceGroup:
    primary: RankedSource
    duplicates: list[RankedSource]
    reason: str


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url)
    cleaned_path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), cleaned_path, "", ""))


def deduplicate_sources(sources: list[RankedSource]) -> list[DeduplicatedSourceGroup]:
    groups: dict[str, DeduplicatedSourceGroup] = {}
    for item in sources:
        key = f"{canonicalize_url(item.result.url)}::{item.result.title.strip().lower()}::{item.result.summary.strip().lower()}"
        if key not in groups:
            groups[key] = DeduplicatedSourceGroup(primary=item, duplicates=[], reason="主来源保留")
            continue
        groups[key].duplicates.append(item)
        groups[key].reason = "相同 URL 或高度相似标题/摘要"
    return list(groups.values())
