from __future__ import annotations


SENSITIVE_MARKERS = [
    "password_hash",
    "password=",
    "token=",
    "secret=",
    "api key=",
    "authorization:",
    "bearer ",
    "private_key",
    "database_url=",
    "redis_url=",
    "jwt_secret=",
    "access_token=",
    "refresh_token=",
]

FORBIDDEN_ACTIONS = [
    "auto_write_docs",
    "git_commit",
    "git_push",
    "deploy",
    "external_api_call",
]


def redact_sensitive_text(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if any(marker in lowered for marker in SENSITIVE_MARKERS):
        return "[REDACTED: sensitive content removed]"
    return text[:4000]


def clean_list(values: list[str]) -> list[str]:
    return [redact_sensitive_text(item) for item in values if redact_sensitive_text(item)]


def safety_payload() -> dict:
    return {
        "readonly": True,
        "draft_only": True,
        "auto_write_disabled": True,
        "git_commit_disabled": True,
        "deploy_disabled": True,
        "external_api_disabled": True,
        "sensitive_fields_filtered": True,
        "forbidden_actions": list(FORBIDDEN_ACTIONS),
    }
