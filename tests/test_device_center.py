from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.device_center.authentication import make_request_signature

from device_agents.macos_observer import MacObserverConfig, MacReadonlyObserverAgent, StaticScreenCaptureProvider, StaticWindowProvider
from device_agents.macos_observer.window_provider import WindowSnapshot


CENTER_PAGE = Path("frontend/device-center.html")
OBSERVER_PAGE = Path("frontend/desktop-observer.html")


def enable_device_flags(monkeypatch, *, device_center: bool = True, agent: bool = True, observer: bool = True, capture: bool = True, vision: bool = True):
    settings = SimpleNamespace(
        DEVICE_CENTER_ENABLED=device_center,
        MAC_DEVICE_AGENT_ENABLED=agent,
        MAC_READONLY_OBSERVER_ENABLED=observer,
        MAC_WINDOW_ENUMERATION_ENABLED=True,
        MAC_SCREEN_CAPTURE_ENABLED=capture,
        LOCAL_VISION_PROVIDER_ENABLED=vision,
        EXTERNAL_VISION_PROVIDER_ENABLED=False,
        SKILLS_ENGINE_ENABLED=True,
        SKILL_INSTALLATION_ENABLED=True,
        SKILL_INVOCATION_ENABLED=True,
        THIRD_PARTY_SKILLS_ENABLED=False,
        UNSIGNED_SKILLS_ENABLED=False,
        AUTO_SKILL_UPDATE_ENABLED=False,
        SKILL_MARKETPLACE_ENABLED=False,
    )
    monkeypatch.setattr("backend.device_center.permissions.get_settings", lambda: settings)
    monkeypatch.setattr("backend.device_center.service.get_settings", lambda: settings)
    monkeypatch.setattr("backend.config.get_settings", lambda: settings)
    return settings


def register_mac_device(client, owner_headers):
    token_response = client.post(
        "/api/v2/devices/register-token",
        headers=owner_headers,
        json={
            "device_type": "Mac 测试设备",
            "environment_type": "test",
            "allowed_capabilities": ["screen_recording", "window_enumeration"],
            "expires_in_minutes": 15,
        },
    )
    assert token_response.status_code == 200
    token = token_response.json()["token"]["registration_token"]

    device_code = "mac-test-001"
    certificate_fingerprint = "cert-fingerprint-mac-test-001"
    nonce = "nonce-mac-register-001"
    timestamp = "2026-07-12T12:00:00Z"
    signature = make_request_signature(
        certificate_fingerprint,
        device_code,
        nonce,
        timestamp,
        path="/api/v2/devices/register",
    )

    register_response = client.post(
        "/api/v2/devices/register",
        json={
            "registration_token": token,
            "device_code": device_code,
            "chinese_name": "Mac 测试设备一号",
            "device_type": "Mac 测试设备",
            "operating_system": "macOS 15",
            "architecture": "arm64",
            "agent_version": "1.0.0",
            "trust_level": "测试",
            "environment_type": "test",
            "owner_employee_code": "tianjian_test",
            "certificate_fingerprint": certificate_fingerprint,
            "public_key_fingerprint": "public-key-mac-test-001",
            "nonce": nonce,
            "timestamp": timestamp,
            "signature": signature,
            "capabilities": ["screen_recording", "window_enumeration"],
        },
    )
    assert register_response.status_code == 200
    device = register_response.json()["device"]
    return device, register_response.json()["credential_fingerprint"]


def test_device_center_pages_exist_and_are_served(client):
    assert CENTER_PAGE.exists()
    assert OBSERVER_PAGE.exists()

    center = client.get("/device-center.html")
    observer = client.get("/desktop-observer.html")

    assert center.status_code == 200
    assert observer.status_code == 200
    assert "测试设备中心" in center.text
    assert "桌面观察" in observer.text


def test_device_center_flow_and_replay_protection(client, owner_headers, monkeypatch):
    enable_device_flags(monkeypatch)
    device, credential_fingerprint = register_mac_device(client, owner_headers)
    device_id = device["device_id"]

    assert device["status"] == "等待批准"
    assert device["enabled"] is False

    approve = client.post(
        f"/api/v2/devices/{device_id}/approve",
        headers=owner_headers,
        json={"trust_level": "高", "environment_type": "test", "reason": "批准测试设备"},
    )
    assert approve.status_code == 200

    heartbeat_nonce = "heartbeat-nonce-001"
    heartbeat_timestamp = "2026-07-12T12:05:00Z"
    heartbeat_signature = make_request_signature(
        credential_fingerprint,
        device["device_code"],
        heartbeat_nonce,
        heartbeat_timestamp,
        path=f"/api/v2/devices/{device_id}/heartbeat",
    )
    heartbeat = client.post(
        f"/api/v2/devices/{device_id}/heartbeat",
        json={
            "nonce": heartbeat_nonce,
            "timestamp": heartbeat_timestamp,
            "signature": heartbeat_signature,
            "last_ip_hash": "hash-ip-001",
            "agent_version": "1.0.1",
            "capabilities": ["screen_recording", "window_enumeration"],
        },
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["device"]["status"] == "在线"

    replay = client.post(
        f"/api/v2/devices/{device_id}/heartbeat",
        json={
            "nonce": heartbeat_nonce,
            "timestamp": heartbeat_timestamp,
            "signature": heartbeat_signature,
        },
    )
    assert replay.status_code == 409

    observation = client.post(
        f"/api/v2/devices/{device_id}/observations",
        headers=owner_headers,
        json={
            "device_id": device_id,
            "task_id": 1,
            "employee_id": 1,
            "skill_id": 1,
            "computer_session_id": None,
            "observation_goal": "检查测试设备窗口状态",
            "allowed_applications": ["Chrome", "VS Code", "Safari"],
            "allowed_windows": [".*测试.*"],
            "max_screenshots": 2,
            "expires_in_minutes": 20,
            "trace_id": "trace-device-obs-001",
            "windows": [
                {
                    "application_name": "Chrome",
                    "bundle_id": "com.google.Chrome",
                    "window_title": "天统 AI 测试页面",
                    "frontmost": True,
                    "screenshot_allowed": True,
                    "suggested_next_step": "继续只读观察",
                }
            ],
            "screen_state": "页面状态正常",
            "suggested_next_step": "继续只读观察",
        },
    )
    assert observation.status_code == 200
    payload = observation.json()
    assert payload["observation"]["status"] == "执行中"
    assert payload["events"]

    windows = client.get(f"/api/v2/devices/{device_id}/windows", headers=owner_headers)
    assert windows.status_code == 200
    assert windows.json()["items"]

    list_observations = client.get("/api/v2/device-observations", headers=owner_headers, params={"device_id": device_id})
    assert list_observations.status_code == 200
    assert list_observations.json()["items"]

    revoke = client.post(
        f"/api/v2/devices/{device_id}/revoke",
        headers=owner_headers,
        json={"reason": "撤销测试设备"},
    )
    assert revoke.status_code == 200

    offline_heartbeat = client.post(
        f"/api/v2/devices/{device_id}/heartbeat",
        json={
            "nonce": "heartbeat-nonce-002",
            "timestamp": "2026-07-12T12:06:00Z",
            "signature": make_request_signature(
                credential_fingerprint,
                device["device_code"],
                "heartbeat-nonce-002",
                "2026-07-12T12:06:00Z",
                path=f"/api/v2/devices/{device_id}/heartbeat",
            ),
        },
    )
    assert offline_heartbeat.status_code == 403


def test_device_center_sensitive_window_blocking(client, owner_headers, monkeypatch):
    enable_device_flags(monkeypatch)
    device, _ = register_mac_device(client, owner_headers)
    device_id = device["device_id"]
    client.post(f"/api/v2/devices/{device_id}/approve", headers=owner_headers, json={"reason": "批准用于阻断测试"})
    client.post(
        f"/api/v2/devices/{device_id}/heartbeat",
        json={
            "nonce": "heartbeat-nonce-sensitive",
            "timestamp": "2026-07-12T12:10:00Z",
            "signature": make_request_signature(
                "cert-fingerprint-mac-test-001",
                device["device_code"],
                "heartbeat-nonce-sensitive",
                "2026-07-12T12:10:00Z",
                path=f"/api/v2/devices/{device_id}/heartbeat",
            ),
        },
    )

    observation = client.post(
        f"/api/v2/devices/{device_id}/observations",
        headers=owner_headers,
        json={
            "device_id": device_id,
            "observation_goal": "检测敏感窗口阻断",
            "allowed_applications": ["Chrome"],
            "allowed_windows": [".*"],
            "windows": [
                {
                    "application_name": "钥匙串",
                    "bundle_id": "com.apple.KeychainAccess",
                    "window_title": "密码管理器",
                    "frontmost": True,
                    "screenshot_allowed": True,
                }
            ],
            "screen_state": "可能存在敏感窗口",
            "trace_id": "trace-device-sensitive-001",
        },
    )
    assert observation.status_code == 200
    data = observation.json()
    assert data["observation"]["status"] == "敏感内容阻断"
    assert data["observation"]["stop_reason"] == "检测到敏感窗口"
    assert data["events"][0]["screenshot_reference"] is None
    assert "SENSITIVE_WINDOW_BLOCKED" in data["events"][0]["risk_flags"]


def test_macos_observer_agent_blocks_sensitive_windows():
    agent = MacReadonlyObserverAgent(
        MacObserverConfig(
            device_code="mac-test-001",
            device_name="Mac 测试设备一号",
            allowed_applications=["Chrome", "VS Code"],
            allowed_window_patterns=[".*测试.*"],
            max_screenshots=2,
            capture_enabled=True,
            window_enumeration_enabled=True,
            vision_provider_enabled=False,
        ),
        window_provider=StaticWindowProvider(
            [
                WindowSnapshot(application_name="Chrome", bundle_id="com.google.Chrome", window_title="天统 AI 测试页面 - 只读观察", frontmost=True),
                WindowSnapshot(application_name="钥匙串", bundle_id="com.apple.KeychainAccess", window_title="密码管理器", frontmost=False),
            ]
        ),
        screen_capture_provider=StaticScreenCaptureProvider(),
    )

    result = agent.observe()
    assert result["summary"]["sensitive_window_detected"] is True
    assert result["summary"]["can_continue"] is False
    assert result["summary"]["suggested_next_step"] == "请求人工处理敏感窗口"
    assert result["permissions"] == ["屏幕录制"]
    assert result["windows"][1]["blocked"] is True
    assert result["screenshots"]


def test_device_center_health_and_seeded_capability(client, owner_headers, test_db, monkeypatch, alpha_enabled):
    from backend.agent_runtime.constants import DEFAULT_CAPABILITIES
    from backend.agent_runtime.models import AgentCapability, AgentExecution, AgentExecutionAudit
    from backend.agent_runtime.permission import get_settings as get_agent_runtime_settings
    from backend.device_center.models import (
        Device,
        DeviceCredential,
        DeviceObservationEvent,
        DeviceObservationSession,
        DeviceRegistrationToken,
        DeviceSecurityEvent,
    )
    from backend.models import TaskCenterResult, TaskCenterTask

    def registry_state():
        db = test_db()
        try:
            rows = db.query(AgentCapability).all()
            return {
                row.capability_id: (
                    row.capability_name,
                    row.capability_type,
                    row.executor_type,
                    row.risk_level,
                    row.enabled,
                    row.readonly,
                    row.requires_boss_approval,
                    row.requires_security_audit,
                    row.timeout_seconds,
                    row.max_retries,
                    row.version,
                )
                for row in rows
            }
        finally:
            db.close()

    def business_state():
        db = test_db()
        try:
            return tuple(
                db.query(model).count()
                for model in (
                    Device,
                    DeviceRegistrationToken,
                    DeviceCredential,
                    DeviceObservationSession,
                    DeviceObservationEvent,
                    DeviceSecurityEvent,
                    AgentExecution,
                    AgentExecutionAudit,
                    TaskCenterTask,
                    TaskCenterResult,
                )
            )
        finally:
            db.close()

    external_device_actions = []

    def reject_external_device_action(*args, **kwargs):
        external_device_actions.append((args, kwargs))
        raise AssertionError("health and capability listing must not execute a device action")

    monkeypatch.setattr(MacReadonlyObserverAgent, "observe", reject_external_device_action)
    enable_device_flags(monkeypatch)
    runtime_settings = get_agent_runtime_settings()
    assert runtime_settings.AGENT_RUNTIME_ENABLED is True
    assert runtime_settings.REAL_EXECUTOR_ENABLED is False
    before_registry = registry_state()
    before_ids = set(before_registry)
    before_business = business_state()

    health = client.get("/api/v2/device-center/health", headers=owner_headers)
    assert health.status_code == 200
    payload = health.json()
    assert payload["status"] == "healthy"
    assert payload["ok"] is True
    assert payload["feature_flags"] == {
        "DEVICE_CENTER_ENABLED": True,
        "MAC_DEVICE_AGENT_ENABLED": True,
        "MAC_READONLY_OBSERVER_ENABLED": True,
        "MAC_WINDOW_ENUMERATION_ENABLED": True,
        "MAC_SCREEN_CAPTURE_ENABLED": True,
        "LOCAL_VISION_PROVIDER_ENABLED": True,
        "EXTERNAL_VISION_PROVIDER_ENABLED": False,
    }
    assert payload["summary"] == {
        "devices": 0,
        "online": 0,
        "observations": 0,
        "events": 0,
        "security_events": 0,
    }
    assert payload["defaults"] == {
        "allowed_applications": [
            "VS Code",
            "Chrome",
            "Safari",
            "纯文本测试编辑器",
            "天统 AI 测试页面",
            "隔离演示应用",
        ],
        "blocked_applications": [
            "Terminal",
            "iTerm",
            "系统设置",
            "钥匙串",
            "密码管理器",
            "邮件",
            "微信",
            "企业微信",
            "钉钉",
            "飞书",
            "银行",
            "支付",
            "App Store",
            "Docker Desktop",
            "SSH",
            "远程桌面",
        ],
        "allowed_windows": [
            ".*测试.*",
            ".*隔离.*",
            ".*天统.*",
            ".*VS Code.*",
            ".*Chrome.*",
            ".*Safari.*",
        ],
        "blocked_windows": [
            ".*密码.*",
            ".*Password.*",
            ".*验证码.*",
            ".*OTP.*",
            ".*Token.*",
            ".*Secret.*",
            ".*私钥.*",
            ".*Keychain.*",
            ".*钥匙串.*",
            ".*付款.*",
            ".*银行卡.*",
            ".*身份证.*",
            ".*登录凭据.*",
            ".*恢复密钥.*",
            ".*Terminal.*",
            ".*iTerm.*",
        ],
    }

    skills = client.get("/api/v2/skills", headers=owner_headers)
    assert skills.status_code == 200
    assert skills.json()["readonly"] is True
    skill_items = skills.json()["skills"]
    window_check = next(item for item in skill_items if item["skill_code"] == "computer.macos.window_check")
    assert window_check["chinese_description"] == "仅对授权的 Mac 测试设备进行只读观察，不允许点击、输入或 Shell 操作。"
    assert window_check["capability_codes"] == ["computer.macos.observe", "computer.sandbox.observe"]
    version = window_check["current_version"]
    assert version["required_permissions"] == ["skills.read"]
    assert version["required_capabilities"] == ["computer.macos.observe", "computer.sandbox.observe"]
    assert version["required_feature_flags"] == [
        "DEVICE_CENTER_ENABLED",
        "MAC_DEVICE_AGENT_ENABLED",
        "MAC_READONLY_OBSERVER_ENABLED",
        "MAC_WINDOW_ENUMERATION_ENABLED",
        "MAC_SCREEN_CAPTURE_ENABLED",
    ]
    manifest = version["manifest"]
    assert manifest["allowed_employee_codes"] == ["tianjian_test", "tiancai_data"]
    assert manifest["network_access"] is False
    assert manifest["filesystem_access"] is False
    assert manifest["browser_access"] is False
    assert manifest["computer_access"] is False
    assert manifest["mobile_access"] is False
    assert manifest["shell_access"] is False

    capabilities = client.get("/api/v2/capabilities", headers=owner_headers)
    assert capabilities.status_code == 200
    capability_items = capabilities.json()["items"]
    capability = next(item for item in capability_items if item["capability_id"] == "computer.macos.observe")
    assert capability["capability_name"] == "Mac 测试设备只读观察"
    assert capability["capability_type"] == "电脑操作"
    assert capability["executor_type"] == "desktop"
    assert capability["risk_level"] == "low"
    assert capability["enabled"] is False
    assert capability["readonly"] is True
    assert capability["requires_boss_approval"] is False
    assert capability["requires_security_audit"] is True
    assert capability["timeout_seconds"] == 30
    assert capability["max_retries"] == 0
    assert capability["allowed_employee_codes"] == ["tianjian_test", "tiancai_data"]

    after_first_registry = registry_state()
    after_first_ids = set(after_first_registry)
    builtin_ids = {str(row["capability_id"]) for row in DEFAULT_CAPABILITIES}
    expected_missing_ids = builtin_ids - before_ids
    assert builtin_ids <= after_first_ids
    assert after_first_ids - before_ids == expected_missing_ids
    assert len(after_first_registry) - len(before_registry) == len(expected_missing_ids)
    assert {capability_id: after_first_registry[capability_id] for capability_id in before_ids} == before_registry
    db = test_db()
    try:
        assert (
            db.query(AgentCapability)
            .filter(AgentCapability.capability_id == "computer.macos.observe")
            .count()
            == 1
        )
    finally:
        db.close()
    assert after_first_registry["computer.macos.observe"] == (
        "Mac 测试设备只读观察",
        "电脑操作",
        "desktop",
        "low",
        False,
        True,
        False,
        True,
        30,
        0,
        "1.0.0",
    )
    assert business_state() == before_business
    assert external_device_actions == []

    second_listing = client.get("/api/v2/capabilities", headers=owner_headers)
    assert second_listing.status_code == 200
    assert second_listing.json() == capabilities.json()
    after_second_registry = registry_state()
    assert after_second_registry == after_first_registry
    db = test_db()
    try:
        assert (
            db.query(AgentCapability)
            .filter(AgentCapability.capability_id == "computer.macos.observe")
            .count()
            == 1
        )
    finally:
        db.close()
    assert business_state() == before_business
    assert external_device_actions == []
    assert get_agent_runtime_settings().AGENT_RUNTIME_ENABLED is True
