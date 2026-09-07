"""Fixed credential destinations and deployment session identity."""
import os
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler

RUNTIME_BASE = "http://jd-browser-runtime:8787/internal/jd-browser"


def runtime_base(variable: str) -> str:
    candidate = os.getenv(variable, RUNTIME_BASE).rstrip("/")
    production = os.getenv("APP_ENV", "").strip().lower() == "production"
    controlled = os.getenv("R297_CONTROLLED_CANARY") == "1"
    if production and controlled:
        raise ValueError("production canary forbidden")
    if candidate == RUNTIME_BASE:
        return candidate
    parsed = urlsplit(candidate)
    if (not controlled or production or parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.port is None or parsed.path != "/internal/jd-browser"
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("invalid Runtime destination")
    return candidate


def session_namespace(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,31}", value):
        raise ValueError("invalid session namespace")
    if os.getenv("APP_ENV", "").strip().lower() == "production" and not re.fullmatch(r"r297-[0-9a-f]{24}", value):
        raise ValueError("deployment-specific namespace required")
    return value


class NoCredentialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
