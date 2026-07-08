from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.auth import hash_password
from backend.dispatch_models import EmployeeExecutionLog
from backend.evolution_models import EmployeeGrowth, ReviewAnalysis, RiskEvent, SkillSuggestion
from backend.models import Role, TaskCenterTask, User
from backend.review_models import EmployeeScore, TaskReview


def create_user(test_db, username: str, role: str):
    db = test_db()
    try:
        if not db.query(Role).filter(Role.code == role).first():
            db.add(Role(code=role, name=role, permissions=[]))
            db.commit()
        user = db.query(User).filter(User.username == username).first()
        if not user:
            user = User(username=username, password_hash=hash_password("password"), role=role, display_name=username, active=True)
            db.add(user)
            db.commit()
    finally:
        db.close()


def login_headers(client, username: str):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def create_review_fixture(test_db, employee_code="tianshang", task_status="completed", review_success=True, high_risk=False):
    db = test_db()
    try:
        task = TaskCenterTask(
            title="部署生产环境" if high_risk else "分析手表市场趋势",
            description="docker deploy production" if high_risk else "分析京东男表趋势并输出建议。",
            status=task_status,
            priority="high" if high_risk else "normal",
            source="task_center",
            assigned_ai_employee_code=employee_code,
            assigned_ai_employee_name=employee_code,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        db.add(
            EmployeeExecutionLog(
                task_id=task.id,
                employee_code=employee_code,
                action="execution_completed" if review_success else "execution_failed",
                result="ok" if review_success else "failed",
                status="completed" if review_success else "failed",
                input_data="market trend input",
                output_data="market trend output" if review_success else None,
                tool_used='["mock_executor"]',
                error_message=None if review_success else "analysis failed",
            )
        )
        db.add(
            TaskReview(
                task_id=task.id,
                employee_code=employee_code,
                success=review_success,
                score=92 if review_success else 35,
                problem_reason="结果与任务目标基本一致。" if review_success else "分析失败",
                improvement="沉淀成功路径。" if review_success else "补充失败处理 SOP。",
            )
        )
        db.add(
            EmployeeScore(
                employee_code=employee_code,
                task_count=1,
                success_rate=100 if review_success else 0,
                average_score=92 if review_success else 35,
                skill_growth=85 if review_success else 20,
            )
        )
        db.commit()
        return task.id
    finally:
        db.close()


def test_employee_evolution_migration_head_and_tables():
    tables = set(EmployeeGrowth.metadata.tables)
    assert {"employee_growth", "review_analysis", "skill_suggestions", "risk_events"} <= tables
    script = ScriptDirectory.from_config(Config(str(Path("alembic.ini"))))
    assert script.get_heads() == ["0020_sprint21_tool_router"]


def test_employee_evolution_routes_require_login_and_reject_viewer(client, viewer_headers):
    client.cookies.clear()
    assert client.get("/api/employee-evolution/growth").status_code == 401
    assert client.get("/api/employee-evolution/profile/tianshang", headers=viewer_headers).status_code == 403
    assert client.post("/api/employee-evolution/analyze", headers=viewer_headers, json={"employee_code": "tianshang"}).status_code == 403
    assert client.get("/api/employee-evolution/risk-events", headers=viewer_headers).status_code == 403


def test_owner_can_analyze_and_view_employee_evolution(client, owner_headers, test_db):
    task_id = create_review_fixture(test_db, employee_code="tianshang")
    response = client.post(
        "/api/employee-evolution/analyze",
        headers=owner_headers,
        json={"task_id": task_id, "employee_code": "tianshang"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["employee_growth"]["employee_code"] == "tianshang"
    assert data["employee_growth"]["score"] > 0
    assert data["review_analysis"][0]["analysis_type"] == "success"
    assert data["skill_suggestions"][0]["status"] == "draft"

    profile = client.get("/api/employee-evolution/profile/tianshang", headers=owner_headers)
    assert profile.status_code == 200
    assert profile.json()["employee_growth"]["employee_code"] == "tianshang"

    growth = client.get("/api/employee-evolution/growth", headers=owner_headers)
    assert growth.status_code == 200
    assert growth.json()["growth"][0]["employee_code"] == "tianshang"


def test_ai_employee_can_only_view_own_evolution(client, test_db):
    create_user(test_db, "tianshang", "operator")
    create_user(test_db, "tianwang", "operator")
    create_review_fixture(test_db, employee_code="tianshang")
    create_review_fixture(test_db, employee_code="tianwang")
    headers = login_headers(client, "tianshang")

    own = client.post("/api/employee-evolution/analyze", headers=headers, json={"employee_code": "tianshang"})
    assert own.status_code == 200
    assert client.get("/api/employee-evolution/profile/tianshang", headers=headers).status_code == 200
    assert client.get("/api/employee-evolution/profile/tianwang", headers=headers).status_code == 403
    growth = client.get("/api/employee-evolution/growth", headers=headers)
    assert growth.status_code == 200
    assert {row["employee_code"] for row in growth.json()["growth"]} == {"tianshang"}


def test_high_risk_analysis_requires_boss_confirmation_and_security_audit(client, owner_headers, test_db):
    task_id = create_review_fixture(test_db, employee_code="tianshang", high_risk=True)
    blocked = client.post("/api/employee-evolution/analyze", headers=owner_headers, json={"task_id": task_id})
    assert blocked.status_code == 403

    boss_only = client.post(
        "/api/employee-evolution/analyze",
        headers=owner_headers,
        json={"task_id": task_id, "boss_confirmed": True, "security_audited": False},
    )
    assert boss_only.status_code == 403

    allowed = client.post(
        "/api/employee-evolution/analyze",
        headers=owner_headers,
        json={"task_id": task_id, "boss_confirmed": True, "security_audited": True},
    )
    assert allowed.status_code == 200


def test_risk_events_and_audit_user_access(client, owner_headers, test_db):
    create_user(test_db, "tianjian_audit", "tianjian_audit")
    task_id = create_review_fixture(test_db, employee_code="tianshang", review_success=False)
    assert client.post("/api/employee-evolution/analyze", headers=owner_headers, json={"task_id": task_id}).status_code == 200

    audit_headers = login_headers(client, "tianjian_audit")
    response = client.get("/api/employee-evolution/risk-events", headers=audit_headers)
    assert response.status_code == 200
    assert response.json()["risk_events"]


def test_employee_evolution_does_not_modify_task_status_or_leak_sensitive_fields(client, owner_headers, test_db):
    task_id = create_review_fixture(test_db, employee_code="tianshang", task_status="completed", review_success=False)
    db = test_db()
    try:
        log = db.query(EmployeeExecutionLog).filter(EmployeeExecutionLog.task_id == task_id).first()
        log.error_message = "token leaked in upstream payload"
        db.commit()
    finally:
        db.close()

    response = client.post("/api/employee-evolution/analyze", headers=owner_headers, json={"task_id": task_id})
    assert response.status_code == 200
    payload = response.json()
    assert "token" not in str(payload).lower()
    assert "password_hash" not in str(payload)
    assert "secret" not in str(payload).lower()

    db = test_db()
    try:
        task = db.get(TaskCenterTask, task_id)
        assert task.status == "completed"
    finally:
        db.close()
