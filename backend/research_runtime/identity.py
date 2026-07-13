from __future__ import annotations

from uuid import UUID, uuid5


_RESEARCH_ID_NAMESPACE = UUID("c8c4c36f-4b8d-4e69-9f52-76a3f9aa3c7c")


def _normalize_component(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text.replace("\n", " ").replace("\r", " ")


def stable_research_id(execution_id: str, resource_type: str, *components: object) -> str:
    raw = "::".join([_normalize_component(execution_id), _normalize_component(resource_type), *(_normalize_component(component) for component in components)])
    return str(uuid5(_RESEARCH_ID_NAMESPACE, raw))
