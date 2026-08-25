from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(secret\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(token\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(cookie\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(password\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(private[_-]?key[\s:]*)(-----BEGIN[^-]+-----.*?-----END[^-]+-----)", re.S),
]

INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (all|previous|above) instructions"),
    re.compile(r"(?i)system prompt"),
    re.compile(r"(?i)please act as"),
    re.compile(r"(?i)developer message"),
    re.compile(r"(?i)override (the )?instructions"),
    re.compile(r"(?i)执行以下命令"),
    re.compile(r"(?i)忽略(之前|以上).*?指令"),
]


def redact_sensitive_text(value: str | None) -> str:
    text = value or ""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]" if match.lastindex and match.lastindex >= 1 else "[REDACTED]", text)
    return text


def redact_url(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return raw
    if not parsed.scheme or not parsed.netloc:
        return raw
    query = [(key, "[REDACTED]" if key.lower() in {"token", "secret", "password", "cookie", "auth", "authorization", "api_key", "apikey"} else val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), ""))


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def stable_text_hash(value: str | None) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def detect_prompt_injection(text: str | None) -> bool:
    sample = text or ""
    return any(pattern.search(sample) for pattern in INJECTION_PATTERNS)


def strip_html_like_noise(text: str | None) -> str:
    raw = text or ""
    raw = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style.*?>.*?</style>", " ", raw)
    raw = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", raw)
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    return normalize_text(raw)
