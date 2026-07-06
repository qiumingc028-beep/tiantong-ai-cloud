#!/usr/bin/env python3
"""
Production-facing API acceptance check for Tiantong AI Cloud.

The script uses public HTTP endpoints only. It does not connect to the
database directly and does not enqueue collection jobs.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any, Optional

import httpx


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


class ApiChecker:
    def __init__(self, base_url: str, username: str, password: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout, follow_redirects=True)
        self.token: Optional[str] = None
        self.results: list[CheckResult] = []

    def close(self) -> None:
        self.client.close()

    def record(self, name: str, ok: bool, detail: str) -> None:
        self.results.append(CheckResult(name=name, ok=ok, detail=detail))

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        if self.token:
            headers = {"Authorization": f"Bearer {self.token}", **headers}
        return self.client.request(method, path, headers=headers, **kwargs)

    def check_health(self) -> None:
        name = "服务器、数据库、Redis健康检查 /api/health"
        try:
            response = self.client.get("/api/health")
            data = response.json()
            problems = []
            if response.status_code != 200:
                problems.append(f"HTTP {response.status_code}")
            if data.get("status") != "running":
                problems.append(f"status={data.get('status')!r}")
            if data.get("database") is not True:
                problems.append(f"database={data.get('database')!r}")
            if data.get("redis") is not True:
                problems.append(f"redis={data.get('redis')!r}")
            if problems:
                self.record(name, False, "; ".join(problems))
            else:
                self.record(name, True, "status=running, database=true, redis=true")
        except Exception as exc:
            self.record(name, False, f"{type(exc).__name__}: {exc}")

    def check_login(self) -> None:
        name = "登录接口 POST /api/login"
        try:
            response = self.client.post(
                "/api/login",
                json={"username": self.username, "password": self.password},
            )
            data = response.json()
            token = data.get("token")
            if response.status_code == 200 and data.get("ok") is True and token:
                self.token = str(token)
                user = data.get("user") or {}
                self.record(name, True, f"登录成功，用户={user.get('username', self.username)}")
            else:
                self.record(name, False, f"HTTP {response.status_code}, response={short(data)}")
        except Exception as exc:
            self.record(name, False, f"{type(exc).__name__}: {exc}")

    def check_json_get(self, name: str, path: str, expect_type: type | tuple[type, ...] = dict) -> None:
        try:
            response = self.request("GET", path)
            data = response.json()
            if response.status_code != 200:
                self.record(name, False, f"HTTP {response.status_code}, response={short(data)}")
                return
            if not isinstance(data, expect_type):
                self.record(name, False, f"返回类型不符合预期: {type(data).__name__}")
                return
            self.record(name, True, f"HTTP 200, 返回类型={type(data).__name__}")
        except Exception as exc:
            self.record(name, False, f"{type(exc).__name__}: {exc}")

    def check_page(self, name: str, path: str) -> None:
        try:
            response = self.client.get(path)
            content_type = response.headers.get("content-type", "")
            if response.status_code == 200 and "html" in content_type.lower():
                self.record(name, True, f"HTTP 200, content-type={content_type}")
            else:
                self.record(name, False, f"HTTP {response.status_code}, content-type={content_type}")
        except Exception as exc:
            self.record(name, False, f"{type(exc).__name__}: {exc}")

    def check_openapi_route(self, name: str, path: str, method: str) -> None:
        try:
            response = self.client.get("/openapi.json")
            data = response.json()
            methods = data.get("paths", {}).get(path, {})
            if response.status_code == 200 and method.lower() in methods:
                self.record(name, True, f"OpenAPI存在 {method.upper()} {path}")
            else:
                self.record(name, False, f"OpenAPI未发现 {method.upper()} {path}")
        except Exception as exc:
            self.record(name, False, f"{type(exc).__name__}: {exc}")

    def run(self) -> int:
        self.check_health()
        self.check_login()
        self.check_json_get("当前用户 GET /api/me", "/api/me")
        self.check_json_get("老板驾驶舱接口 GET /api/dashboard", "/api/dashboard")
        self.check_json_get("店铺列表 GET /api/stores", "/api/stores", list)
        self.check_json_get("京东指标汇总 GET /api/jd/metrics/summary", "/api/jd/metrics/summary")
        self.check_page("老板驾驶舱页面 /control.html", "/control.html")
        self.check_page("京东60店数据中心页面 /jd-dashboard.html", "/jd-dashboard.html")
        self.check_page("今日数据录入页面 /metrics.html", "/metrics.html")
        self.check_page("Excel导入页面 /import.html", "/import.html")
        self.check_openapi_route("京东商智单店采集接口存在", "/api/jd/sync/store/{store_id}", "post")
        self.check_openapi_route("京准通广告批量采集接口存在", "/api/jd/sync/all", "post")
        return self.print_summary()

    def print_summary(self) -> int:
        print(f"API base: {self.base_url}")
        print("")
        failed = 0
        for result in self.results:
            mark = "PASS" if result.ok else "FAIL"
            print(f"[{mark}] {result.name}")
            print(f"       {result.detail}")
            if not result.ok:
                failed += 1
        print("")
        if failed:
            print(f"验收失败：{failed} 项未通过。")
            return 1
        print("验收通过：所有检查项均正常。")
        return 0


def short(value: Any, limit: int = 300) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + "..."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tiantong AI Cloud API acceptance check")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--username", default="owner", help="Login username")
    parser.add_argument("--password", default="password", help="Login password")
    parser.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checker = ApiChecker(args.base_url, args.username, args.password, args.timeout)
    try:
        return checker.run()
    finally:
        checker.close()


if __name__ == "__main__":
    sys.exit(main())
