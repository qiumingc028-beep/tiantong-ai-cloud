from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.models import AiEmployee, TaskCenterTask, User
from backend.device_center.models import Device
from backend.agent_runtime.executors.computer.models import ComputerAction, ComputerSession
from backend.agent_runtime.workflows.computer.models import ComputerWorkflow, ComputerWorkflowCheckpoint, ComputerWorkflowRecovery, ComputerWorkflowStep, ComputerWorkflowVerification
from backend.observability.constants import DEVICE_HEALTH_GRADES, INCIDENT_SEVERITIES, INCIDENT_STATUSES, QUALITY_GRADES, RISK_GRADES
from backend.observability.models import AlertRule, CircuitBreaker, SecurityIncident
from backend.observability.service import collect_all, find_or_create_breaker, maybe_auto_pause, trigger_breaker


def _enable_observability_flags(monkeypatch):
    settings = SimpleNamespace(
        EXECUTION_OBSERVABILITY_ENABLED=True,
        DEVICE_METRICS_ENABLED=True,
        EXECUTION_QUALITY_SCORING_ENABLED=True,
        EXECUTION_RISK_SCORING_ENABLED=True,
        ANOMALY_DETECTION_ENABLED=True,
        SECURITY_INCIDENT_CENTER_ENABLED=True,
        ALERT_RULES_ENABLED=True,
        AUTOMATIC_PAUSE_ENABLED=True,
        CIRCUIT_BREAKER_ENABLED=True,
        EXECUTION_REPLAY_ENABLED=True,
        EMPLOYEE_PERFORMANCE_METRICS_ENABLED=True,
    )
    monkeypatch.setattr("backend.observability.permissions.get_settings", lambda: settings)
    monkeypatch.setattr("backend.observability.service.get_settings", lambda: settings)
    monkeypatch.setattr("backend.config.get_settings", lambda: settings)
    return settings


def _create_sample_observability_data(test_db):
    db = test_db()
    try:
        employee = db.query(AiEmployee).filter(AiEmployee.employee_code == "tianjian_test").one_or_none()
        if employee is None:
            employee = AiEmployee(
                employee_code="tianjian_test",
                employee_name="天检：测试验收中心",
                legion="研发交付军团",
                duty="测试验收、缺陷复核与回归验证",
                status="active",
                task_types=json.dumps(["test", "acceptance"], ensure_ascii=False),
                default_permissions=json.dumps(["task_center.review"], ensure_ascii=False),
                is_legacy=False,
                sort_order=50,
            )
            db.add(employee)
            db.flush()
        task = TaskCenterTask(title="安全运营测试任务", description="用于观测中心回归", status="created", priority="normal", source="boss", assigned_ai_employee_code=employee.employee_code, assigned_ai_employee_name=employee.employee_name)
        device = Device(
            device_id="device-observability-1",
            device_code="mac-obs-001",
            chinese_name="观测测试设备",
            device_type="Mac 测试设备",
            operating_system="macOS 15",
            architecture="arm64",
            agent_version="2.0.0",
            status="在线",
            trust_level="测试",
            environment_type="test",
            owner_id=employee.id,
            registered_by=None,
            approved_by=None,
            last_seen_at=datetime.now(timezone.utc),
            last_ip_hash="ip-hash-obs-1",
            certificate_fingerprint="cert-fingerprint-obs-1",
            capabilities_json=json.dumps(["screen_recording"], ensure_ascii=False),
            enabled=True,
        )
        session = ComputerSession(
            session_id="session-observability-1",
            execution_id=None,
            task_id=task.id,
            employee_id=employee.id,
            skill_id=None,
            executor_type="mock",
            environment_type="test",
            status="执行中",
            risk_level="高风险",
            approval_status="已批准",
            allowed_applications_json=json.dumps(["天统测试页面"], ensure_ascii=False),
            allowed_windows_json=json.dumps([".*测试.*"], ensure_ascii=False),
            started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            ended_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            takeover_status="未接管",
            last_screenshot_at=datetime.now(timezone.utc) - timedelta(minutes=2),
            trace_id="trace-session-observability-1",
        )
        workflow = ComputerWorkflow(
            workflow_id="workflow-observability-1",
            task_id=task.id,
            employee_id=employee.id,
            skill_id=None,
            device_id=device.device_id,
            session_id=session.session_id,
            goal="验证安全运营中心监控与评分",
            status="执行中",
            risk_level="极高风险",
            approval_status="已批准",
            total_steps=2,
            current_step=2,
            max_steps=5,
            checkpoint_count=1,
            execution_budget_json=json.dumps({"max_steps": 5}, ensure_ascii=False),
            started_at=datetime.now(timezone.utc) - timedelta(minutes=4),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
            finished_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            stop_reason=None,
            trace_id="trace-workflow-observability-1",
        )
        step1 = ComputerWorkflowStep(
            step_id="workflow-observability-step-1",
            workflow_id=workflow.workflow_id,
            sequence_number=1,
            action_type="查看屏幕",
            target_application="天统测试页面",
            target_bundle_id="com.tiantong.test",
            target_window="测试工作流页面",
            target_control="",
            input_summary="",
            expected_result="观察页面状态",
            risk_level="低风险",
            approval_required=False,
            checkpoint_required=False,
            status="已完成",
            action_id="action-observability-1",
            verification_id="verification-observability-1",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=4),
            finished_at=datetime.now(timezone.utc) - timedelta(minutes=3),
            trace_id="trace-step-1",
        )
        step2 = ComputerWorkflowStep(
            step_id="workflow-observability-step-2",
            workflow_id=workflow.workflow_id,
            sequence_number=2,
            action_type="单击",
            target_application="天统测试页面",
            target_bundle_id="com.tiantong.test",
            target_window="测试工作流页面",
            target_control="普通按钮",
            input_summary="测试按钮",
            expected_result="单击按钮成功",
            risk_level="中低风险",
            approval_required=True,
            checkpoint_required=True,
            status="已失败",
            action_id="action-observability-2",
            verification_id="verification-observability-2",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=3),
            finished_at=datetime.now(timezone.utc) - timedelta(minutes=2),
            error_code="BUTTON_NOT_FOUND",
            error_message="按钮未找到",
            trace_id="trace-step-2",
        )
        checkpoint = ComputerWorkflowCheckpoint(
            checkpoint_id="workflow-observability-checkpoint-1",
            workflow_id=workflow.workflow_id,
            step_id=step2.step_id,
            checkpoint_type="输入前确认",
            reason="需要确认按钮可见",
            screenshot_reference="s3://internal/replay/workflow-observability-1/before.png",
            state_summary="页面正常",
            risk_level="中低风险",
            approval_status="已批准",
            approved_by=1,
            approved_at=datetime.now(timezone.utc) - timedelta(minutes=3),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=7),
            trace_id="trace-checkpoint-1",
        )
        verification1 = ComputerWorkflowVerification(
            verification_id="verification-observability-1",
            workflow_id=workflow.workflow_id,
            step_id=step1.step_id,
            verification_status="结果符合预期",
            before_screenshot_reference="before-1",
            after_screenshot_reference="after-1",
            state_summary="页面状态正常",
            result_summary="完成观察",
            trace_id="trace-verification-1",
        )
        verification2 = ComputerWorkflowVerification(
            verification_id="verification-observability-2",
            workflow_id=workflow.workflow_id,
            step_id=step2.step_id,
            verification_status="结果不符合",
            before_screenshot_reference="before-2",
            after_screenshot_reference="after-2",
            state_summary="页面变化异常",
            result_summary="按钮单击失败",
            trace_id="trace-verification-2",
        )
        recovery = ComputerWorkflowRecovery(
            recovery_id="workflow-observability-recovery-1",
            workflow_id=workflow.workflow_id,
            step_id=step2.step_id,
            recovery_type="人工接管",
            status="已完成",
            reason="验证失败后人工确认",
            result_summary="暂停等待复核",
            trace_id="trace-recovery-1",
            finished_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        action1 = ComputerAction(
            action_id="computer-action-observability-1",
            session_id=session.session_id,
            sequence_number=1,
            action_type="查看屏幕",
            target_application="天统测试页面",
            target_window="测试会话窗口",
            target_description="观察页面状态",
            input_summary="",
            coordinates_json=None,
            risk_level="低风险",
            approval_required=False,
            approval_status="无需审批",
            screenshot_before="before-session-1",
            screenshot_after="after-session-1",
            result="观察成功",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            finished_at=datetime.now(timezone.utc) - timedelta(minutes=4),
            duration_ms=6000,
            trace_id="trace-action-1",
        )
        action2 = ComputerAction(
            action_id="computer-action-observability-2",
            session_id=session.session_id,
            sequence_number=2,
            action_type="单击",
            target_application="天统测试页面",
            target_window="测试会话窗口",
            target_description="测试按钮",
            input_summary="按钮单击",
            coordinates_json=None,
            risk_level="中低风险",
            approval_required=True,
            approval_status="已批准",
            screenshot_before="before-session-2",
            screenshot_after="after-session-2",
            result="验证失败",
            error_code="VERIFY_FAILED",
            error_message="执行结果不符合预期",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=3),
            finished_at=datetime.now(timezone.utc) - timedelta(minutes=2),
            duration_ms=12000,
            trace_id="trace-action-2",
        )
        incident = SecurityIncident(
            incident_id="incident-observability-1",
            incident_code="INC-OBS-001",
            incident_type="告警规则触发",
            severity="高",
            status="新发现",
            device_id=device.device_id,
            employee_id=employee.id,
            task_id=task.id,
            execution_id=workflow.workflow_id,
            session_id=session.session_id,
            workflow_id=workflow.workflow_id,
            action_id=action2.action_id,
            title="执行验证失败",
            description="用于安全事件确认与解决",
            detected_by="rule",
            evidence_references_json=json.dumps(["metric:max_risk_score"], ensure_ascii=False),
            risk_score=92,
            automatic_action="暂停工作流",
            trace_id="trace-incident-1",
        )
        breaker = CircuitBreaker(
            breaker_id="breaker-observability-1",
            breaker_scope="workflow",
            breaker_key=workflow.workflow_id,
            status="已熔断",
            reason="连续验证失败",
            trigger_count=1,
            risk_score=95,
            triggered_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            manual_reset_required=True,
            trace_id="trace-breaker-1",
        )
        db.add_all([task, device, session, workflow, step1, step2, checkpoint, verification1, verification2, recovery, action1, action2, incident, breaker])
        db.commit()
        collect_all(db)
        return {
            "task_id": task.id,
            "device_id": device.device_id,
            "session_id": session.session_id,
            "workflow_id": workflow.workflow_id,
            "incident_id": incident.incident_id,
            "breaker_id": breaker.breaker_id,
        }
    finally:
        db.close()


def test_observability_pages_and_default_flags(client):
    for page in ["security-ops-center.html", "device-monitoring.html", "execution-quality.html", "security-incidents.html"]:
        response = client.get(f"/{page}")
        assert response.status_code == 200
        assert "中文" not in response.text or "安全" in response.text or "设备" in response.text


def test_observability_overview_device_and_execution_views(client, owner_headers, monkeypatch, test_db):
    _enable_observability_flags(monkeypatch)
    payload = _create_sample_observability_data(test_db)

    overview = client.get("/api/v2/observability/overview", headers=owner_headers)
    assert overview.status_code == 200
    body = overview.json()
    assert body["running_workflows"] >= 1
    assert body["max_risk_score"] >= 90

    devices = client.get("/api/v2/observability/devices", headers=owner_headers)
    assert devices.status_code == 200
    assert devices.json()["items"]

    device_detail = client.get(f"/api/v2/observability/devices/{payload['device_id']}", headers=owner_headers)
    assert device_detail.status_code == 200
    assert device_detail.json()["device"]["chinese_name"] == "观测测试设备"

    executions = client.get("/api/v2/observability/executions", headers=owner_headers)
    assert executions.status_code == 200
    assert executions.json()["items"]

    execution_detail = client.get(f"/api/v2/observability/executions/{payload['workflow_id']}", headers=owner_headers)
    assert execution_detail.status_code == 200
    assert execution_detail.json()["execution"]["execution_id"] == payload["workflow_id"]

    workflow_detail = client.get(f"/api/v2/observability/workflows/{payload['workflow_id']}", headers=owner_headers)
    assert workflow_detail.status_code == 200
    assert workflow_detail.json()["workflow"]["workflow_id"] == payload["workflow_id"]

    quality = client.get("/api/v2/observability/quality-scores", headers=owner_headers)
    assert quality.status_code == 200
    item = quality.json()["items"][0]
    assert item["grade"] in QUALITY_GRADES
    assert item["explanation"]

    risk = client.get("/api/v2/observability/risk-scores", headers=owner_headers)
    assert risk.status_code == 200
    item = risk.json()["items"][0]
    assert item["grade"] in RISK_GRADES
    assert item["explanation"]

    replay = client.get(f"/api/v2/execution-replays/{payload['workflow_id']}", headers=owner_headers)
    assert replay.status_code == 200
    assert replay.json()["available"] is True


def test_observability_security_incidents_alert_rules_and_breaker(client, admin_headers, owner_headers, monkeypatch, test_db):
    _enable_observability_flags(monkeypatch)
    payload = _create_sample_observability_data(test_db)

    incidents = client.get("/api/v2/security/incidents", headers=owner_headers)
    assert incidents.status_code == 200
    assert incidents.json()["items"]

    incident = client.get(f"/api/v2/security/incidents/{payload['incident_id']}", headers=owner_headers)
    assert incident.status_code == 200
    assert incident.json()["incident_code"] == "INC-OBS-001"

    ack = client.post(
        f"/api/v2/security/incidents/{payload['incident_id']}/acknowledge",
        headers=admin_headers,
        json={"comment": "已收到告警"},
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "处理中"

    resolve = client.post(
        f"/api/v2/security/incidents/{payload['incident_id']}/resolve",
        headers=admin_headers,
        json={"resolution_summary": "已完成人工复核"},
    )
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "已解决"

    alert_rules = client.get("/api/v2/security/alert-rules", headers=owner_headers)
    assert alert_rules.status_code == 200
    alert_items = alert_rules.json()["items"]
    assert alert_items

    patch_rule = client.patch(
        f"/api/v2/security/alert-rules/{alert_items[0]['rule_id']}",
        headers=admin_headers,
        json={"threshold": "2"},
    )
    assert patch_rule.status_code == 200
    assert patch_rule.json()["threshold"] == "2"

    create_rule = client.post(
        "/api/v2/security/alert-rules",
        headers=admin_headers,
        json={
            "中文名称": "测试告警规则",
            "rule_code": "test_rule_observability",
            "metric_name": "risk_score",
            "condition": "gte",
            "threshold": "80",
            "duration_seconds": 60,
            "severity": "中",
            "action": "仅记录",
            "enabled": True,
            "environment": "test",
        },
    )
    assert create_rule.status_code == 200
    assert create_rule.json()["rule_code"] == "test_rule_observability"

    breaker = client.post(
        f"/api/v2/security/circuit-breakers/{payload['breaker_id']}/reset",
        headers=admin_headers,
    )
    assert breaker.status_code == 200
    assert breaker.json()["status"] == "正常"

    db = test_db()
    try:
        workflow = db.get(ComputerWorkflow, payload["workflow_id"])
        assert workflow is not None
        maybe_auto_pause(db, {"max_risk_score": 95})
        db.refresh(workflow)
        assert workflow.status == "已暂停"
    finally:
        db.close()


def test_observability_collect_all_and_feature_flags(monkeypatch, test_db):
    settings = _enable_observability_flags(monkeypatch)
    assert settings.EXECUTION_OBSERVABILITY_ENABLED is True
    db = test_db()
    try:
        result = collect_all(db)
        assert "device_metrics" in result
        assert "quality_scores" in result
        assert "risk_scores" in result
    finally:
        db.close()


def test_observability_constants_are_chinese():
    assert "优秀" in QUALITY_GRADES
    assert "健康" in DEVICE_HEALTH_GRADES
    assert "新发现" in INCIDENT_STATUSES
    assert "高" in INCIDENT_SEVERITIES
    assert "极高" in RISK_GRADES
