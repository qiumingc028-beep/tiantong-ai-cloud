from __future__ import annotations

import base64
import json


def test_preflight_lists_missing_controlled_material_without_values(monkeypatch):
    from ops.r297_evidence_preflight import inspect_controlled_material

    for name in (
        "R297_PAGE_EVENT_RECEIVER_PRIVATE_KEY_PATH",
        "R297_OBSERVER_PRIVATE_KEY_PATH",
        "R297_WINDOWS_RUNNER_PRIVATE_KEY_PATH",
        "R297_OBSERVER_DATABASE_URL",
        "R297_EVIDENCE_NONCE_LEDGER",
        "R297_WINDOWS_CANARY_BACKEND_HTTPS_URL",
        "R297_WINDOWS_CANARY_PAIRING_ISSUER_BEARER",
        "R297_WINDOWS_CANARY_SERVER_CERTIFICATE_BASE64",
    ):
        monkeypatch.delenv(name, raising=False)

    results = [
        inspect_controlled_material(environment="acceptance", role=role)
        for role in ("page_event_receiver", "authenticated_observer", "windows_runner", "verifier")
    ]
    rendered = json.dumps(results, sort_keys=True)
    missing = {item for result in results for item in result["missing"]}

    assert all(result["result"] == "BLOCK" for result in results)
    assert missing >= {
        "PAGE_EVENT_RECEIVER_PRIVATE_KEY", "OBSERVER_PRIVATE_KEY",
        "WINDOWS_RUNNER_PRIVATE_KEY", "READ_ONLY_DATABASE_URL", "NONCE_LEDGER",
        "TRUST_MANIFEST", "TRUST_MANIFEST_SIDECAR", "PAGEHIDE_BINDING",
        "PAGEHIDE_BINDING_SIDECAR", "BACKEND_HTTPS_URL",
        "PAIRING_ISSUER_AUTHORIZATION", "BACKEND_CERTIFICATE",
    }
    assert "postgresql://" not in rendered
    assert "Bearer " not in rendered


def test_preflight_never_accepts_test_only_material_for_acceptance(monkeypatch, tmp_path):
    from ops.r297_evidence_preflight import inspect_controlled_material

    test_key = tmp_path / "test-key.json"
    test_key.write_text('{"environment":"test"}\n', encoding="utf-8")
    test_key.chmod(0o600)
    for name in (
        "R297_PAGE_EVENT_RECEIVER_PRIVATE_KEY_PATH",
        "R297_OBSERVER_PRIVATE_KEY_PATH",
        "R297_WINDOWS_RUNNER_PRIVATE_KEY_PATH",
    ):
        monkeypatch.setenv(name, str(test_key))
    monkeypatch.setenv("R297_OBSERVER_DATABASE_URL", "postgresql://redacted")
    monkeypatch.setenv("R297_WINDOWS_CANARY_BACKEND_HTTPS_URL", "https://controlled.invalid")
    monkeypatch.setenv("R297_WINDOWS_CANARY_PAIRING_ISSUER_BEARER", "not-printed")
    monkeypatch.setenv(
        "R297_WINDOWS_CANARY_SERVER_CERTIFICATE_BASE64",
        base64.b64encode(b"certificate").decode(),
    )

    result = inspect_controlled_material(environment="acceptance", role="windows_runner")

    assert result["result"] == "BLOCK"
    assert "TEST_ONLY_PRIVATE_KEY" in result["invalid"]


def test_preflight_rejects_cross_role_private_keys(monkeypatch, tmp_path):
    from ops.r297_evidence_preflight import inspect_controlled_material

    key = tmp_path / "key.pem"
    key.write_text("not-a-secret-test-marker\n", encoding="utf-8")
    key.chmod(0o600)
    monkeypatch.setenv("R297_PAGE_EVENT_RECEIVER_PRIVATE_KEY_PATH", str(key))
    monkeypatch.setenv("R297_OBSERVER_PRIVATE_KEY_PATH", str(key))

    result = inspect_controlled_material(environment="acceptance", role="page_event_receiver")

    assert result["result"] == "BLOCK"
    assert "CROSS_ROLE_PRIVATE_KEY" in result["invalid"]


def test_windows_private_key_accepts_readonly_file_without_unix_owner_semantics(tmp_path):
    from ops.r297_evidence_preflight import _private_key_status

    key = tmp_path / "key.pem"
    key.write_text("not-a-secret-test-marker\n", encoding="utf-8")
    key.chmod(0o444)

    assert _private_key_status(str(key), windows=True) is None
