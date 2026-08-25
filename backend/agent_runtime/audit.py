from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from ..models import AiEmployee, User
from .models import AgentExecution, AgentExecutionAudit


SENSITIVE_MARKERS = ("password", "secret", "token", "cookie", "private_key", "authorization", "bearer", "api_key", "api key")
SENSITIVE_RE = re.compile("|".join(re.escape(marker) for marker in SENSITIVE_MARKERS), re.IGNORECASE)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        return redact_url(value)
    if SENSITIVE_RE.search(value):
        return "[已脱敏]"
    return value


def redact_url(value: str) -> str:
    split = urlsplit(value)
    if not split.scheme or not split.netloc:
        return value
    query_items: list[tuple[str, str]] = []
    for key, item in parse_qsl(split.query, keep_blank_values=True):
        if SENSITIVE_RE.search(key):
            query_items.append((key, "[已脱敏]"))
        else:
            query_items.append((key, item))
    query = "&".join(f"{key}={value}" for key, value in query_items)
    return urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))


def sanitize_payload(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if SENSITIVE_RE.search(str(key)):
                sanitized["[已脱敏]"] = "[已脱敏]"
            else:
                sanitized[key] = sanitize_payload(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def payload_summary(value: Any, limit: int = 500) -> str | None:
    sanitized = sanitize_payload(value)
    if sanitized is None:
        return None
    if isinstance(sanitized, (dict, list)):
        text = json.dumps(sanitized, ensure_ascii=False, default=str)
    else:
        text = str(sanitized)
    return text[:limit]


def write_audit_event(
    db: Session,
    execution: AgentExecution,
    event_type: str,
    actor_type: str,
    actor_id: str | None = None,
    approval_status: str | None = None,
    approval_decision: str | None = None,
    risk_level: str | None = None,
    input_summary: str | None = None,
    output_summary: str | None = None,
    error_summary: str | None = None,
    executor_name: str | None = None,
    source_ip: str | None = None,
    sensitive_data_involved: bool = False,
) -> AgentExecutionAudit:
    audit = AgentExecutionAudit(
        execution_id=execution.execution_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        approval_status=approval_status,
        approval_decision=approval_decision,
        risk_level=risk_level or execution.risk_level,
        input_summary=payload_summary(input_summary),
        output_summary=payload_summary(output_summary),
        error_summary=payload_summary(error_summary),
        executor_name=executor_name,
        source_ip=source_ip,
        sensitive_data_involved=bool(sensitive_data_involved),
        trace_id=execution.trace_id,
    )
    db.add(audit)
    return audit


def execution_actor(user: User) -> str:
    return f"user:{user.username}"


def employee_actor(employee: AiEmployee | None) -> str:
    return f"employee:{employee.employee_code}" if employee else None
