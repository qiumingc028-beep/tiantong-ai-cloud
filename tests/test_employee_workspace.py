from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import event

from backend.auth import hash_password
from backend.deploy_models import DeployRecord
from backend.models import AiEmployee, TaskCenterAuditLog, TaskCenterTask, User
from backend.orchestrator_models import OrchestratorAnalysisRecord, OrchestratorTaskLink
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


API_PATH = "/api/employee-workspace/overview"
HOME_PATH = "/api/employee-workspace/employees/{employee_code}/home"
SENSITIVE_KEYS = {
    "input_excerpt",
    "prompt_draft",
    "raw_text",
    "token",
    "cookie",
    "password",
    "api_key",
    "database_url",
    "redis_url",
    "bearer",
    "authorization",
    "secret",
}


def auth_headers(client, username: str):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_employee_workspace_requires_login(client):
    response = client.get(API_PATH)
    assert response.status_code == 401


def test_employee_workspace_rejects_low_privilege_users(client):
    for username in ["operator", "customer_service", "designer", "editor", "viewer"]:
        response = client.get(API_PATH, headers=auth_headers(client, username))
        assert response.status_code == 403


def test_employee_workspace_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        response = client.get(API_PATH, headers=headers)
        assert response.status_code == 200


def test_employee_workspace_response_shape(client, owner_headers):
    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert {
        "summary",
        "employees",
        "blockers",
        "pending_reviews",
        "pending_audits",
        "pending_deploys",
        "recent_actions",
    } <= set(data)
    assert {
        "total_employees",
        "standby_count",
        "running_count",
        "reviewing_count",
        "completed_count",
        "blocked_count",
        "current_sprint",
        "today_tasks",
        "pending_boss_confirmations",
        "pending_test_reviews",
        "pending_audits",
        "pending_deploys",
    } <= set(data["summary"])


def test_employee_workspace_employee_without_task_is_standby(client, owner_headers):
    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    rows = {row["employee_code"]: row for row in response.json()["employees"]}
    assert rows["tiantong"]["status"] == "standby"
    assert rows["tiantong"]["current_task"] is None
    assert rows["tiantong"]["task_id"] is None
    assert rows["tiantong"]["next_suggestion"] == "等待任务"


def test_employee_workspace_maps_task_and_orchestrator_data(client, owner_headers, test_db):
    db = test_db()
    try:
        task = TaskCenterTask(
            title="Implement workspace API",
            status="result_submitted",
            priority="high",
            assigned_ai_employee_code="tianwang",
            assigned_ai_employee_name="天王：后端开发中心",
        )
        db.add(task)
        db.flush()
        db.add(
            OrchestratorAnalysisRecord(
                input_excerpt="password=hidden raw text",
                input_hash="a" * 64,
                detected_employee_code="tianwang",
                detected_employee_name="天王：后端开发中心",
                detected_sprint="Sprint 7",
                detected_stage="backend",
                completion_status="completed",
                recommended_codex="tianwang",
                recommended_action="交给天检验收",
                safety_flags_json=json.dumps(["manual_review"]),
                prompt_draft="secret prompt should not be returned",
            )
        )
        db.add(TaskCenterAuditLog(task_id=task.id, action="result_submitted", to_status="result_submitted"))
        db.commit()
        task_id = task.id
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    rows = {row["employee_code"]: row for row in data["employees"]}
    tianwang = rows["tianwang"]
    assert tianwang["status"] == "reviewing"
    assert tianwang["task_id"] == task_id
    assert tianwang["sprint"] == "Sprint 7"
    assert tianwang["stage"] == "backend"
    assert tianwang["review_status"] == "pending"
    assert tianwang["recent_orchestrator_source"]["analysis_id"]
    assert data["summary"]["pending_test_reviews"] == 1
    assert data["pending_reviews"][0]["task_id"] == task_id
    assert data["recent_actions"]


@pytest.mark.parametrize(
    ("task_status", "workspace_status", "progress", "has_blocker", "blocker_reason", "next_suggestion"),
    [
        ("created", "standby", 0, False, None, "等待老板确认或分配"),
        ("pending", "standby", 0, False, None, "等待处理"),
        ("assigned", "standby", 0, False, None, "等待开始任务"),
        ("in_progress", "running", 50, False, None, "继续执行任务"),
        ("submitted", "reviewing", 75, False, None, "等待天检验收"),
        ("reviewing", "reviewing", 75, False, None, "验收中"),
        ("audited", "completed", 100, False, None, "等待最终确认"),
        ("completed", "completed", 100, False, None, "任务已完成"),
        ("summarized", "completed", 100, False, None, "任务已完成"),
        ("result_submitted", "reviewing", 75, False, None, "等待天检验收"),
        ("accepted", "completed", 100, False, None, "任务已完成"),
        ("rejected", "blocked", 20, True, "任务被驳回", "需要修复后重新提交"),
        ("failed", "blocked", 20, True, "任务失败", "需要排查失败原因"),
        ("blocked", "blocked", 20, True, "任务阻塞", "需要处理阻塞原因"),
        ("unknown_status", "standby", 0, False, None, "等待处理"),
    ],
)
def test_employee_workspace_maps_task_statuses_without_mutating_tasks(
    client,
    owner_headers,
    test_db,
    task_status,
    workspace_status,
    progress,
    has_blocker,
    blocker_reason,
    next_suggestion,
):
    employee_code = f"status_{task_status}"
    db = test_db()
    try:
        db.add(
            AiEmployee(
                employee_code=employee_code,
                employee_name=f"Status {task_status}",
                legion="测试军团",
                duty="状态映射测试",
                status="active",
                task_types='["test"]',
                default_permissions="[]",
                is_legacy=False,
                sort_order=500,
            )
        )
        task = TaskCenterTask(
            title=f"{task_status} task",
            status=task_status,
            assigned_ai_employee_code=employee_code,
            assigned_ai_employee_name=f"Status {task_status}",
        )
        db.add(task)
        db.commit()
        task_id = task.id
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    rows = {row["employee_code"]: row for row in response.json()["employees"]}
    row = rows[employee_code]
    assert row["status"] == workspace_status
    assert row["progress_percent"] == progress
    assert row["has_blocker"] is has_blocker
    assert row["blocker_reason"] == blocker_reason
    assert row["next_suggestion"] == next_suggestion

    db = test_db()
    try:
        assert db.get(TaskCenterTask, task_id).status == task_status
    finally:
        db.close()


def test_employee_workspace_handles_empty_sources(client, owner_headers, test_db):
    db = test_db()
    try:
        db.query(OrchestratorTaskLink).delete()
        db.query(OrchestratorAnalysisRecord).delete()
        db.query(TaskCenterAuditLog).delete()
        db.query(TaskCenterTask).delete()
        db.query(DeployRecord).delete()
        db.query(AiEmployee).delete()
        db.commit()
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_employees"] == 0
    assert data["employees"] == []
    assert data["blockers"] == []
    assert data["pending_reviews"] == []
    assert data["pending_audits"] == []
    assert data["pending_deploys"] == []
    assert data["recent_actions"] == []


def test_employee_workspace_reports_blockers_audits_and_deploys(client, owner_headers, test_db):
    db = test_db()
    try:
        rejected = TaskCenterTask(
            title="Needs fix",
            status="rejected",
            assigned_ai_employee_code="tianwang",
            assigned_ai_employee_name="天王：后端开发中心",
        )
        accepted = TaskCenterTask(title="Wait audit", status="accepted")
        db.add_all([rejected, accepted])
        db.add(DeployRecord(deploy_version="Sprint 7", operator="tiandun", status="pending"))
        db.commit()
        rejected_id = rejected.id
        accepted_id = accepted.id
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["blocked_count"] >= 1
    assert data["summary"]["pending_audits"] == 1
    assert data["summary"]["pending_deploys"] == 1
    assert any(item["task_id"] == rejected_id for item in data["blockers"])
    assert data["pending_audits"][0]["task_id"] == accepted_id
    assert data["pending_deploys"][0]["status"] == "pending"


def test_employee_workspace_does_not_return_sensitive_fields(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add(
            OrchestratorAnalysisRecord(
                input_excerpt="raw_text cookie password secret",
                input_hash="b" * 64,
                detected_employee_code="tianwang",
                detected_employee_name="天王：后端开发中心",
                prompt_draft="Bearer token Authorization DATABASE_URL REDIS_URL API key",
                recommended_codex="tianwang",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    assert_sensitive_keys_absent(response.json())


def test_employee_workspace_is_read_only(client, owner_headers, test_db):
    db = test_db()
    engine = db.get_bind()
    statements = []

    def capture_write(_conn, _cursor, statement, _parameters, _context, _executemany):
        verb = statement.strip().split(maxsplit=1)[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"}:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_write)
    try:
        response = client.get(API_PATH, headers=owner_headers)
        assert response.status_code == 200
        assert statements == []
    finally:
        event.remove(engine, "before_cursor_execute", capture_write)
        db.close()


def test_employee_workspace_does_not_add_alembic_migration():
    versions = {path.name for path in Path("alembic/versions").glob("*.py")}
    assert "0011_orchestrator_task_links.py" in versions
    assert "0012_employee_workspace.py" not in versions


def test_employee_workspace_home_shows_identity_capabilities_tasks_and_growth(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add(
            AiEmployee(
                employee_code="tianshang",
                employee_name="天商：商品运营中心",
                legion="电商运营军团",
                duty="商品运营、商品分析与运营动作",
                status="active",
                task_types='["product_ops"]',
                default_permissions='["task_center.execute"]',
                is_legacy=False,
                sort_order=180,
            )
        )
        db.add_all(
            [
                TaskCenterTask(
                    title="优化京东60店商品详情页转化",
                    status="assigned",
                    assigned_ai_employee_code="tianshang",
                    assigned_ai_employee_name="天商：商品运营中心",
                ),
                TaskCenterTask(
                    title="商品卖点复盘",
                    status="completed",
                    assigned_ai_employee_code="tianshang",
                    assigned_ai_employee_name="天商：商品运营中心",
                ),
                TaskCenterTask(
                    title="商品价格方案失败",
                    status="failed",
                    assigned_ai_employee_code="tianshang",
                    assigned_ai_employee_name="天商：商品运营中心",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get(HOME_PATH.format(employee_code="tianshang"), headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    home = data["employee_home"]
    assert home["identity"]["employee_code"] == "tianshang"
    assert "product_optimization" in home["capability_tags"]
    assert "ecommerce_operation" in home["skill_list"]
    assert home["current_task"]["title"] == "优化京东60店商品详情页转化"
    assert len(home["history_completed_tasks"]) == 1
    assert data["task_center_linkage"]["pending_tasks"]
    assert data["task_center_linkage"]["failed_tasks"][0]["failure_reason"] == "任务失败"
    assert data["growth"]["success_rate"] == 0.5
    assert data["growth"]["can_auto_expand_permission"] is False
    assert data["safety"]["authorized_tasks_only"] is True


def test_employee_workspace_home_marks_high_risk_task_for_tian_shen(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add(
            AiEmployee(
                employee_code="tiantou",
                employee_name="天投：广告投放中心",
                legion="增长投放军团",
                duty="投放策略、预算建议和关键词分析",
                status="active",
                task_types='["ad_analysis"]',
                default_permissions='["task_center.execute"]',
                is_legacy=False,
                sort_order=190,
            )
        )
        db.add(
            TaskCenterTask(
                title="检查京东60店广告预算异常",
                description="涉及广告预算和投放风险，只允许审批后处理。",
                status="assigned",
                assigned_ai_employee_code="tiantou",
                assigned_ai_employee_name="天投：广告投放中心",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(HOME_PATH.format(employee_code="tiantou"), headers=owner_headers)

    assert response.status_code == 200
    task = response.json()["task_center_linkage"]["pending_tasks"][0]
    assert task["requires_tian_shen"] is True
    assert task["can_execute_without_approval"] is False
    assert response.json()["growth"]["requires_tian_shen_for_high_risk_skill"] is True


def test_employee_workspace_home_allows_employee_to_view_only_self(client, test_db):
    db = test_db()
    try:
        db.add(
            User(
                username="tianshang",
                password_hash=hash_password("password"),
                role="viewer",
                display_name="天商员工账号",
                active=True,
            )
        )
        db.commit()
    finally:
        db.close()
    headers = auth_headers(client, "tianshang")

    own = client.get(HOME_PATH.format(employee_code="tianshang"), headers=headers)
    other = client.get(HOME_PATH.format(employee_code="tiantong"), headers=headers)

    assert own.status_code == 200
    assert other.status_code == 403


def test_employee_workspace_home_is_read_only_and_does_not_queue(client, owner_headers):
    response = client.get(HOME_PATH.format(employee_code="tiantong"), headers=owner_headers)

    assert response.status_code == 200
    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def assert_sensitive_keys_absent(value):
    if isinstance(value, dict):
        for key, child in value.items():
            assert key.lower() not in SENSITIVE_KEYS
            assert_sensitive_keys_absent(child)
    elif isinstance(value, list):
        for child in value:
            assert_sensitive_keys_absent(child)
