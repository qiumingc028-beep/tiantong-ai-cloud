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


def test_device_center_health_and_seeded_capability(client, owner_headers, monkeypatch):
    enable_device_flags(monkeypatch)
    health = client.get("/api/v2/device-center/health", headers=owner_headers)
    assert health.status_code == 200
    payload = health.json()
    assert payload["status"] == "healthy"
    assert payload["feature_flags"]["DEVICE_CENTER_ENABLED"] is True
    assert payload["feature_flags"]["EXTERNAL_VISION_PROVIDER_ENABLED"] is False

    skills = client.get("/api/v2/skills", headers=owner_headers)
    assert skills.status_code == 200
    skill_items = skills.json()["skills"]
    assert any(item["skill_code"] == "computer.macos.window_check" for item in skill_items)

    capabilities = client.get("/api/v2/capabilities", headers=owner_headers)
    assert capabilities.status_code == 200
    capability_items = capabilities.json()["items"]
    assert any(item["capability_id"] == "computer.macos.observe" for item in capability_items)
