from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class BrowserFieldSpec:
    name: str
    selector: str | None = None
    attribute: str | None = None
    json_path: str | None = None
    kind: str = "text"
    multiple: bool = False

    @classmethod
    def from_value(cls, value: Any) -> "BrowserFieldSpec":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(name=value, selector=value)
        if not isinstance(value, dict):
            raise TypeError("browser field spec must be a dict or string")
        name = str(value.get("name") or value.get("field") or value.get("key") or "").strip()
        if not name:
            raise ValueError("browser field spec requires a name")
        selector = value.get("selector") or value.get("css_selector")
        json_path = value.get("json_path") or value.get("path")
        return cls(
            name=name,
            selector=str(selector).strip() if selector else None,
            attribute=str(value.get("attribute")).strip() if value.get("attribute") else None,
            json_path=str(json_path).strip() if json_path else None,
            kind=str(value.get("kind") or value.get("type") or "text").strip().lower() or "text",
            multiple=bool(value.get("multiple") or value.get("all")),
        )


@dataclass(slots=True)
class FetchedDocument:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    body: bytes
    headers: dict[str, str]
    redirect_chain: list[str]
    fetched_at: datetime


@dataclass(slots=True)
class HtmlNode:
    tag: str
    attrs: dict[str, str]
    children: list["HtmlNode | str"]


@dataclass(slots=True)
class HtmlDocument:
    root: HtmlNode
    title: str | None = None
