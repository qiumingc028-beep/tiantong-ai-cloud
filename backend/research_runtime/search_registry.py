from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from ..config import get_settings
from .exceptions import SearchProviderUnavailable
from .schemas import SearchResult


class SearchProvider(Protocol):
    name: str

    def validate_query(self, query: str, *, allowed_domains: list[str], blocked_domains: list[str]) -> None: ...

    def search(
        self,
        *,
        query: str,
        language: str,
        time_range: str | None,
        source_count: int,
        allowed_domains: list[str],
        blocked_domains: list[str],
        safe_search: bool,
        trace_id: str | None,
    ) -> list[SearchResult]: ...

    def cancel(self, trace_id: str | None) -> dict[str, object]: ...

    def health_check(self) -> dict[str, object]: ...

    def get_metadata(self) -> dict[str, object]: ...


@dataclass(slots=True)
class MockSearchProvider:
    name: str = "MockSearchProvider"

    def validate_query(self, query: str, *, allowed_domains: list[str], blocked_domains: list[str]) -> None:
        if not query.strip():
            raise ValueError("查询词不能为空")

    def search(
        self,
        *,
        query: str,
        language: str,
        time_range: str | None,
        source_count: int,
        allowed_domains: list[str],
        blocked_domains: list[str],
        safe_search: bool,
        trace_id: str | None,
    ) -> list[SearchResult]:
        self.validate_query(query, allowed_domains=allowed_domains, blocked_domains=blocked_domains)
        now = datetime.now(timezone.utc).isoformat()
        catalog = [
            ("https://docs.python.org/3/", "Python 官方文档"),
            ("https://fastapi.tiangolo.com/", "FastAPI 官方文档"),
            ("https://www.sqlalchemy.org/", "SQLAlchemy 官方网站"),
            ("https://docs.pydantic.dev/", "Pydantic 官方文档"),
            ("https://pypi.org/", "Python Package Index"),
            ("https://www.reuters.com/", "Reuters 新闻"),
        ]
        results: list[SearchResult] = []
        for index, (url, title) in enumerate(catalog[: max(1, source_count)], start=1):
            domain = url.split("//", 1)[1].split("/", 1)[0]
            if allowed_domains and not any(domain == item or domain.endswith(f".{item}") for item in allowed_domains):
                continue
            if any(domain == item or domain.endswith(f".{item}") for item in blocked_domains):
                continue
            results.append(
                SearchResult(
                    title=f"{title}：{query}",
                    url=url,
                    summary=f"{query} 的公开来源候选：{title}",
                    source_domain=domain,
                    published_at=None,
                    search_rank=index,
                    provider=self.name,
                    query=query,
                    fetched_at=now,
                )
            )
        return results

    def cancel(self, trace_id: str | None) -> dict[str, object]:
        return {"cancelled": True, "trace_id": trace_id, "provider": self.name}

    def health_check(self) -> dict[str, object]:
        return {"ok": True, "provider": self.name, "status": "ready"}

    def get_metadata(self) -> dict[str, object]:
        return {"name": self.name, "supports_real_search": False, "provider_type": "mock"}


@dataclass(slots=True)
class ControlledPublicSearchProvider:
    name: str = "ControlledPublicSearchProvider"

    def validate_query(self, query: str, *, allowed_domains: list[str], blocked_domains: list[str]) -> None:
        if not query.strip():
            raise ValueError("查询词不能为空")

    def search(
        self,
        *,
        query: str,
        language: str,
        time_range: str | None,
        source_count: int,
        allowed_domains: list[str],
        blocked_domains: list[str],
        safe_search: bool,
        trace_id: str | None,
    ) -> list[SearchResult]:
        settings = get_settings()
        if not settings.PUBLIC_SEARCH_ENABLED:
            raise SearchProviderUnavailable("真实搜索能力已关闭")
        raise SearchProviderUnavailable("受控公开搜索适配器尚未启用")

    def cancel(self, trace_id: str | None) -> dict[str, object]:
        return {"cancelled": True, "trace_id": trace_id, "provider": self.name}

    def health_check(self) -> dict[str, object]:
        settings = get_settings()
        return {
            "ok": bool(settings.PUBLIC_SEARCH_ENABLED),
            "provider": self.name,
            "status": "ready" if settings.PUBLIC_SEARCH_ENABLED else "disabled",
        }

    def get_metadata(self) -> dict[str, object]:
        return {"name": self.name, "supports_real_search": True, "provider_type": "controlled_public"}


PROVIDERS = {
    "mock": MockSearchProvider(),
    "controlled": ControlledPublicSearchProvider(),
    "public": ControlledPublicSearchProvider(),
}


def resolve_search_provider() -> SearchProvider:
    settings = get_settings()
    key = settings.PUBLIC_SEARCH_PROVIDER or "mock"
    provider = PROVIDERS.get(key)
    if provider:
        return provider
    if not settings.PUBLIC_SEARCH_ENABLED:
        return PROVIDERS["mock"]
    raise SearchProviderUnavailable(f"未配置支持的搜索提供者：{key}")
