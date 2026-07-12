from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from backend.config import get_settings

from .exceptions import BrowserPolicyError


ALLOWED_SCHEMES = {"https"}


@dataclass(slots=True)
class BrowserPolicy:
    allowed_domains: list[str]
    blocked_domains: list[str]
    block_private_networks: bool
    max_redirects: int
    default_timeout_seconds: int
    max_response_bytes: int
    user_agent: str
    allow_http: bool

    @classmethod
    def from_settings(cls) -> "BrowserPolicy":
        settings = get_settings()
        return cls(
            allowed_domains=[domain.lower().strip().rstrip(".") for domain in settings.BROWSER_ALLOWED_DOMAINS if domain.strip()],
            blocked_domains=[],
            block_private_networks=settings.BROWSER_BLOCK_PRIVATE_NETWORKS,
            max_redirects=max(0, int(settings.BROWSER_MAX_REDIRECTS)),
            default_timeout_seconds=max(1, int(settings.BROWSER_DEFAULT_TIMEOUT_SECONDS)),
            max_response_bytes=max(1, int(settings.BROWSER_MAX_RESPONSE_BYTES)),
            user_agent=str(settings.BROWSER_USER_AGENT or "TiantongAIReadonlyBrowser/1.0"),
            allow_http=bool(settings.BROWSER_ALLOW_HTTP),
        )


def normalize_url(url: str, *, allowed_domains: list[str] | None = None, blocked_domains: list[str] | None = None) -> str:
    split = urlsplit(url.strip())
    if not split.scheme or not split.netloc:
        raise BrowserPolicyError("必须提供完整 URL", "URL_NOT_ALLOWED")
    if split.username or split.password:
        raise BrowserPolicyError("URL 中不能包含用户名或密码", "URL_NOT_ALLOWED")
    scheme = split.scheme.lower()
    settings = get_settings()
    if scheme not in ALLOWED_SCHEMES and not (scheme == "http" and settings.BROWSER_ALLOW_HTTP):
        raise BrowserPolicyError("仅允许 https 访问", "URL_NOT_ALLOWED")
    host = (split.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise BrowserPolicyError("URL 主机不能为空", "URL_NOT_ALLOWED")
    if is_ip_literal(host):
        raise BrowserPolicyError("禁止访问 IP 形式地址", "DOMAIN_NOT_ALLOWED")
    policy = BrowserPolicy.from_settings()
    effective_allowed_domains = [domain.lower().strip().rstrip(".") for domain in (allowed_domains if allowed_domains is not None else policy.allowed_domains) if domain and str(domain).strip()]
    effective_blocked_domains = [domain.lower().strip().rstrip(".") for domain in (blocked_domains if blocked_domains is not None else policy.blocked_domains) if domain and str(domain).strip()]
    if effective_blocked_domains and is_blocked_domain(host, effective_blocked_domains):
        raise BrowserPolicyError("域名在黑名单中", "DOMAIN_NOT_ALLOWED")
    if not is_allowed_domain(host, effective_allowed_domains):
        raise BrowserPolicyError("域名不在白名单中", "DOMAIN_NOT_ALLOWED")
    if policy.block_private_networks:
        block_private_address(host)
    return urlunsplit((scheme, split.netloc, split.path or "/", split.query, ""))


def validate_redirect_target(url: str, *, allowed_domains: list[str] | None = None, blocked_domains: list[str] | None = None) -> str:
    return normalize_url(url, allowed_domains=allowed_domains, blocked_domains=blocked_domains)


def is_allowed_domain(host: str, allowed_domains: list[str]) -> bool:
    if not allowed_domains:
        return False
    for domain in allowed_domains:
        domain = domain.lower().strip().rstrip(".")
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def is_blocked_domain(host: str, blocked_domains: list[str]) -> bool:
    for domain in blocked_domains:
        domain = domain.lower().strip().rstrip(".")
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def block_private_address(host: str) -> None:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        addresses = resolve_host_ips(host)
        if not addresses:
            raise BrowserPolicyError("无法解析主机地址", "DOMAIN_NOT_ALLOWED")
        for addr in addresses:
            ip_obj = ipaddress.ip_address(addr)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast:
                raise BrowserPolicyError("禁止访问私有网络地址", "PRIVATE_NETWORK_BLOCKED")
        return
    raise BrowserPolicyError("禁止访问 IP 形式地址", "DOMAIN_NOT_ALLOWED")


def resolve_host_ips(host: str) -> list[str]:
    seen: list[str] = []
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BrowserPolicyError("域名解析失败", "DOMAIN_NOT_ALLOWED") from exc
    for _, _, _, _, sockaddr in infos:
        ip = sockaddr[0]
        if ip not in seen:
            seen.append(ip)
    return seen
