from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.auth import hash_password
from backend.dispatch_models import EmployeeExecutionLog
from backend.models import Role, TaskCenterResult, TaskCenterTask, User
from backend.review_analyzer import generate_task_review
from backend.review_models import EmployeeScore, KnowledgeFeedback, TaskReview
from backend.score_calculator import calculate_employee_score
from tests.test_helpers import latest_alembic_head


def create_task_with_execution(test_db, status="completed", employee_code="tianshang", error_message=None):
    db = test_db()
    try:
        task = TaskCenterTask(
            title="分析近期爆款手表趋势",
            description="分析京东男表市场趋势，推荐适合开发的新产品方向。",
            status=status,
            priority="normal",
            source="task_center",
            assigned_ai_employee_code=employee_code,
            assigned_ai_employee_name="天商：商品运营中心",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        log = EmployeeExecutionLog(
            task_id=task.id,
            employee_code=employee_code,
            action="execution_completed" if status == "completed" else "execution_failed",
            result="ok" if status == "completed" else "failed",
            status=status,
            input_data='{"title":"分析近期爆款手表趋势"}',
            output_data='{"summary":"趋势分析完成"}' if status == "completed" else None,
            tool_used='["mock_executor"]',
            error_message=error_message,
        )
        db.add(log)
        if status == "completed":
            db.add(
                TaskCenterResult(
                    task_id=task.id,
                    ai_employee_code=employee_code,
                    ai_employee_name="天商：商品运营中心",
                    result_content="趋势分析完成",
                    attachments_json="[]",
                )
            )
        db.commit()
        return task.id
    finally:
        db.close()


def create_employee_login(test_db, username="tianshang", role="operator"):
    db = test_db()
    try:
        if not db.query(Role).filter(Role.code == role).first():
            db.add(Role(code=role, name=role, permissions=[]))
            db.commit()
        user = db.query(User).filter(User.username == username).first()
        if not user:
            user = User(
                username=username,
                password_hash=hash_password("password"),
                role=role,
                display_name=username,
                active=True,
            )
            db.add(user)
            db.commit()
        return username
    finally:
        db.close()


def login_headers(client, username: str):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_review_learning_tables_and_migration_head():
    assert {"task_reviews", "employee_scores", "knowledge_feedback"} <= set(TaskReview.metadata.tables)
    script = ScriptDirectory.from_config(Config(str(Path("alembic.ini"))))
    assert script.get_heads() == [latest_alembic_head()]


def test_reviews_routes_require_login_and_reject_viewer(client, viewer_headers):
    client.cookies.clear()
    assert client.get("/api/reviews/tasks").status_code == 401
    assert client.get("/api/reviews/tasks", headers=viewer_headers).status_code == 403
    assert client.get("/api/reviews/employees", headers=viewer_headers).status_code == 403


def test_owner_can_generate_review_score_and_feedback(client, owner_headers, test_db):
    task_id = create_task_with_execution(test_db, status="completed")
    response = client.post("/api/reviews/generate", headers=owner_headers, json={"task_id": task_id})
    assert response.status_code == 200
    data = response.json()
    assert data["review"]["task_id"] == task_id
    assert data["review"]["employee_code"] == "tianshang"
    assert data["review"]["success"] is True
    assert data["review"]["score"] > 0
    assert data["employee_score"]["task_count"] == 1
    assert data["knowledge_feedback"]["status"] == "draft"

    db = test_db()
    try:
        task = db.get(TaskCenterTask, task_id)
        assert task.status == "completed"
        assert db.query(TaskReview).filter(TaskReview.task_id == task_id).count() == 1
        assert db.query(EmployeeScore).filter(EmployeeScore.employee_code == "tianshang").count() == 1
        assert db.query(KnowledgeFeedback).filter(KnowledgeFeedback.source_task == task_id).count() == 1
    finally:
        db.close()


def test_failed_review_redacts_sensitive_error(client, owner_headers, test_db):
    task_id = create_task_with_execution(test_db, status="failed", error_message="token leaked in worker payload")
    response = client.post("/api/reviews/generate", headers=owner_headers, json={"task_id": task_id})
    assert response.status_code == 200
    payload = response.json()
    assert payload["review"]["success"] is False
    assert payload["review"]["problem_reason"] == "[REDACTED]"
    assert "token" not in str(payload).lower()


def test_employee_can_only_view_own_reviews(client, test_db):
    create_employee_login(test_db, username="tianshang", role="operator")
    task_id = create_task_with_execution(test_db, status="completed", employee_code="tianshang")
    db = test_db()
    try:
        review = generate_task_review(db, task_id)
        calculate_employee_score(db, review.employee_code)
    finally:
        db.close()

    headers = login_headers(client, "tianshang")
    own = client.get("/api/reviews/employee/tianshang", headers=headers)
    assert own.status_code == 200
    assert own.json()["reviews"]

    other = client.get("/api/reviews/employee/tianwang", headers=headers)
    assert other.status_code == 403

    all_scores = client.get("/api/reviews/employees", headers=headers)
    assert all_scores.status_code == 403


def test_owner_can_list_reviews_and_employee_scores(client, owner_headers, test_db):
    task_id = create_task_with_execution(test_db, status="completed")
    assert client.post("/api/reviews/generate", headers=owner_headers, json={"task_id": task_id}).status_code == 200

    reviews = client.get("/api/reviews/tasks", headers=owner_headers)
    assert reviews.status_code == 200
    assert reviews.json()["reviews"][0]["task_id"] == task_id

    employees = client.get("/api/reviews/employees", headers=owner_headers)
    assert employees.status_code == 200
    assert employees.json()["employees"][0]["employee_code"] == "tianshang"


def test_generate_review_for_missing_task_returns_404(client, owner_headers):
    response = client.post("/api/reviews/generate", headers=owner_headers, json={"task_id": 999999})
    assert response.status_code == 404
