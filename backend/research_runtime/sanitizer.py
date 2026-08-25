from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlsplit, urlunsplit


SENSITIVE_QUERY_KEYS = {"password", "passwd", "secret", "token", "cookie", "authorization", "api_key", "apikey", "session"}


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def content_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def sanitize_url(url: str) -> str:
    split = urlsplit(url)
    if not split.scheme or not split.netloc:
        return url
    query_items = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        lowered = key.lower()
        if any(marker in lowered for marker in SENSITIVE_QUERY_KEYS):
            query_items.append((key, "[已脱敏]"))
        else:
            query_items.append((key, value))
    query = "&".join(f"{key}={value}" for key, value in query_items)
    return urlunsplit((split.scheme, split.netloc, split.path, query, ""))


def excerpt(text: str, limit: int = 2000) -> str:
    value = normalize_whitespace(text)
    return value[:limit]
