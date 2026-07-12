from __future__ import annotations

import json
import time
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from backend.config import get_settings

from ...audit import payload_summary
from ...executor_types import ExecutorContext, ExecutorResult
from .exceptions import BrowserExecutorError, BrowserExtractionError, BrowserFetchError, BrowserPolicyError
from .extractor import extract_structured_fields, extract_title, extract_visible_text, parse_html_document
from .policy import BrowserPolicy, normalize_url, validate_redirect_target
from .sanitizer import content_hash, excerpt, sanitize_url
from .schemas import FetchedDocument


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


class ReadonlyHttpBrowserExecutor:
    executor_type = "browser"
    name = "ReadonlyHttpBrowserExecutor"

    def validate(self, context: ExecutorContext) -> None:
        if context.executor_type != "browser":
            raise BrowserPolicyError("浏览器执行器仅支持 browser 类型", "URL_NOT_ALLOWED")
        settings = get_settings()
        if not settings.BROWSER_READONLY_ENABLED and not settings.BROWSER_CONTROL_ENABLED:
            raise BrowserPolicyError("浏览器只读执行器未启用", "BROWSER_DISABLED")
        request_url = str(context.input_payload.get("url") or context.input_payload.get("target_url") or "").strip()
        normalize_url(request_url)

    def execute(self, context: ExecutorContext) -> ExecutorResult:
        self.validate(context)
        policy = BrowserPolicy.from_settings()
        started_at = datetime.now(timezone.utc)
        start_clock = time.perf_counter()
        request_url = str(context.input_payload.get("url") or context.input_payload.get("target_url") or "").strip()
        request_url = normalize_url(request_url)
        allow_redirects = bool(context.input_payload.get("allow_redirects", True))
        method = str(context.input_payload.get("method") or "GET").strip().upper()
        if method not in {"GET", "HEAD"}:
            raise BrowserPolicyError("只读浏览器仅允许 GET 或 HEAD", "URL_NOT_ALLOWED")
        timeout_seconds = int(context.input_payload.get("timeout_seconds") or context.timeout_seconds or policy.default_timeout_seconds)
        timeout_seconds = max(1, min(timeout_seconds, policy.default_timeout_seconds))
        max_response_bytes = int(context.input_payload.get("max_response_bytes") or policy.max_response_bytes)
        max_response_bytes = max(1, min(max_response_bytes, policy.max_response_bytes))

        try:
            fetched = fetch_document(
                request_url=request_url,
                policy=policy,
                allow_redirects=allow_redirects,
                method=method,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
                user_agent=policy.user_agent,
            )
            content_type = fetched.content_type.lower()
            decoded = decode_body(fetched.body, fetched.content_type)
            source_domain = urlparse(fetched.final_url).hostname or ""
            structured_fields: dict[str, Any] = {}
            page_title: str | None = None
            extracted_text: str | None = None
            if "json" in content_type:
                try:
                    parsed_json = json.loads(decoded)
                except Exception as exc:
                    raise BrowserExtractionError("JSON 内容解析失败", "PARSE_ERROR") from exc
                structured_fields = extract_structured_fields_from_json(parsed_json, context.input_payload)
                extracted_text = excerpt(json.dumps(parsed_json, ensure_ascii=False), 4000)
            elif "html" in content_type or "xhtml" in content_type:
                document = parse_html_document(decoded)
                page_title = extract_title(document)
                extracted_text = extract_visible_text(document, limit=4000)
                structured_fields = extract_structured_fields(document, decoded, fetched.content_type, context.input_payload)
            elif content_type.startswith("text/") or content_type == "application/xml":
                extracted_text = excerpt(decoded, 4000)
                structured_fields = extract_structured_fields_from_plain_text(decoded, context.input_payload)
            else:
                raise BrowserFetchError("不支持的内容类型", "UNSUPPORTED_CONTENT_TYPE", http_status=fetched.status_code)

            resolved_title = page_title
            if not resolved_title and ("html" in content_type or "xhtml" in content_type):
                resolved_title = extract_title(parse_html_document(decoded))
            output = {
                "requested_url": sanitize_url(request_url),
                "final_url": sanitize_url(fetched.final_url),
                "page_title": resolved_title,
                "status_code": fetched.status_code,
                "content_type": fetched.content_type,
                "extracted_text": extracted_text,
                "structured_fields": structured_fields,
                "sources": [
                    {
                        "url": sanitize_url(fetched.final_url),
                        "title": page_title,
                        "collected_at": fetched.fetched_at.isoformat(),
                        "content_hash": content_hash(fetched.body),
                    }
                ],
                "collected_at": fetched.fetched_at.isoformat(),
                "content_hash": content_hash(fetched.body),
                "duration_ms": max(1, int((time.perf_counter() - start_clock) * 1000)),
                "redirect_chain": fetched.redirect_chain,
                "domain": source_domain,
            }
            return ExecutorResult(
                success=True,
                output=output,
                error_code=None,
                error_message=None,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                duration_ms=max(1, int((time.perf_counter() - start_clock) * 1000)),
                metadata={
                    "executor": self.name,
                    "payload_summary": payload_summary(context.input_payload),
                    "policy": {
                        "allowed_domains": policy.allowed_domains,
                        "max_redirects": policy.max_redirects,
                        "block_private_networks": policy.block_private_networks,
                    },
                },
            )
        except BrowserExecutorError as exc:
            finished_at = datetime.now(timezone.utc)
            duration = max(1, int((time.perf_counter() - start_clock) * 1000))
            return ExecutorResult(
                success=False,
                output={
                    "requested_url": sanitize_url(request_url),
                    "error_code": exc.code,
                    "error_message": str(exc),
                },
                error_code=exc.code,
                error_message=str(exc),
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration,
                metadata={
                    "executor": self.name,
                    "payload_summary": payload_summary(context.input_payload),
                },
                retryable=exc.retryable,
            )
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            duration = max(1, int((time.perf_counter() - start_clock) * 1000))
            return ExecutorResult(
                success=False,
                output={"requested_url": sanitize_url(request_url), "error_message": "执行失败"},
                error_code="EXECUTION_FAILED",
                error_message="执行失败",
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration,
                metadata={"executor": self.name, "payload_summary": payload_summary(context.input_payload)},
                retryable=False,
            )

    def cancel(self, context: ExecutorContext) -> dict[str, Any]:
        return {"cancelled": True, "executor": self.name, "execution_id": context.execution_id}

    def health_check(self) -> dict[str, Any]:
        settings = get_settings()
        ready = bool(settings.BROWSER_READONLY_ENABLED)
        return {
            "ok": ready,
            "executor": self.name,
            "status": "ready" if ready else "disabled",
            "browser_readonly_enabled": settings.BROWSER_READONLY_ENABLED,
            "browser_control_enabled": settings.BROWSER_CONTROL_ENABLED,
            "allowed_domains": settings.BROWSER_ALLOWED_DOMAINS,
        }

    def get_metadata(self) -> dict[str, Any]:
        return {
            "executor_type": self.executor_type,
            "name": self.name,
            "supports_real_world": True,
            "mode": "readonly_http",
        }


def decode_body(body: bytes, content_type: str) -> str:
    charset = "utf-8"
    lower = content_type.lower()
    if "charset=" in lower:
        charset = lower.split("charset=", 1)[1].split(";", 1)[0].strip().strip('"').strip("'") or "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def fetch_document(
    *,
    request_url: str,
    policy: BrowserPolicy,
    allow_redirects: bool,
    method: str,
    timeout_seconds: int,
    max_response_bytes: int,
    user_agent: str,
) -> FetchedDocument:
    current_url = request_url
    redirect_chain: list[str] = []
    opener = urllib.request.build_opener(_NoRedirectHandler())
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.1",
    }
    for _ in range(policy.max_redirects + 1):
        validate_request_url(current_url, policy)
        request = urllib.request.Request(current_url, headers=headers, method=method)
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                status_code = int(getattr(response, "status", response.getcode()))
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                body = response.read(max_response_bytes + 1)
                if len(body) > max_response_bytes:
                    raise BrowserFetchError("响应体超出限制", "RESPONSE_TOO_LARGE", http_status=status_code)
                final_url = sanitize_url(response.geturl() or current_url)
                return FetchedDocument(
                    requested_url=request_url,
                    final_url=final_url,
                    status_code=status_code,
                    content_type=content_type,
                    body=body,
                    headers={key: value for key, value in response.headers.items()},
                    redirect_chain=redirect_chain,
                    fetched_at=datetime.now(timezone.utc),
                )
        except urllib.error.HTTPError as exc:
            status_code = int(getattr(exc, "code", 0) or 0)
            content_type = exc.headers.get("Content-Type", "application/octet-stream") if exc.headers else "application/octet-stream"
            if 300 <= status_code < 400:
                if not allow_redirects:
                    raise BrowserFetchError("重定向已禁止", "REDIRECT_BLOCKED", http_status=status_code)
                location = exc.headers.get("Location") if exc.headers else None
                if not location:
                    raise BrowserFetchError("重定向缺少目标地址", "REDIRECT_BLOCKED", http_status=status_code)
                next_url = validate_redirect_target(urljoin(current_url, location))
                redirect_chain.append(sanitize_url(next_url))
                current_url = next_url
                continue
            body = exc.read(max_response_bytes + 1) if hasattr(exc, "read") else b""
            if len(body) > max_response_bytes:
                raise BrowserFetchError("响应体超出限制", "RESPONSE_TOO_LARGE", http_status=status_code)
            retryable = status_code in {502, 503, 504}
            raise BrowserFetchError(f"HTTP 错误 {status_code}", "HTTP_ERROR", http_status=status_code, retryable=retryable)
        except (TimeoutError, socket.timeout) as exc:
            raise BrowserFetchError("请求超时", "REQUEST_TIMEOUT", retryable=True) from exc
        except urllib.error.URLError as exc:
            raise BrowserFetchError("请求失败", "HTTP_ERROR", retryable=True) from exc
    raise BrowserFetchError("重定向次数超限", "REDIRECT_BLOCKED", retryable=False)


def validate_request_url(url: str, policy: BrowserPolicy) -> None:
    normalized = normalize_url(url)
    if policy.block_private_networks:
        # normalize_url already checks private addresses and domain whitelist.
        return
    if not normalized:
        raise BrowserPolicyError("URL 无效", "URL_NOT_ALLOWED")


def extract_structured_fields_from_json(parsed_json: Any, payload: dict[str, Any]) -> dict[str, Any]:
    from .extractor import parse_field_specs, extract_json_path

    specs = parse_field_specs(payload)
    if not specs:
        return {}
    result: dict[str, Any] = {}
    for field in specs:
        path = field.json_path or field.selector or field.name
        value = extract_json_path(parsed_json, path)
        if isinstance(value, str):
            result[field.name] = excerpt(value, 1000)
        else:
            result[field.name] = value
    return result


def extract_structured_fields_from_plain_text(source_text: str, payload: dict[str, Any]) -> dict[str, Any]:
    from .extractor import parse_field_specs

    specs = parse_field_specs(payload)
    if not specs:
        return {}
    return {field.name: excerpt(source_text, 1000) for field in specs}
