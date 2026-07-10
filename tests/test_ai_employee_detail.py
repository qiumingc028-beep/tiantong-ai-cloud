from backend.models import TaskCenterAuditLog, TaskCenterResult, TaskCenterReview, TaskCenterTask
from pathlib import Path


DETAIL_PAGE = Path("frontend/ai-employee-detail.html")


def read_detail_page() -> str:
    return DETAIL_PAGE.read_text(encoding="utf-8")


def test_ai_employee_detail_returns_aggregated_readonly_profile(client, owner_headers, test_db):
    db = test_db()
    try:
        task = TaskCenterTask(
            title="Employee detail aggregation task",
            description="Should not be returned by detail API",
            status="completed",
            priority="normal",
            source="test",
            assigned_ai_employee_code="tianwang",
            assigned_ai_employee_name="天王：后端开发中心",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        db.add(
            TaskCenterResult(
                task_id=task.id,
                ai_employee_code="tianwang",
                ai_employee_name="天王：后端开发中心",
                result_content="Done",
            )
        )
        db.add(
            TaskCenterReview(
                task_id=task.id,
                review_type="acceptance",
                review_status="accepted",
                comment="Accepted",
            )
        )
        db.add(
            TaskCenterAuditLog(
                task_id=task.id,
                action="detail_test",
                from_status="running",
                to_status="completed",
                detail="contains token and password and must be redacted",
            )
        )
        db.commit()
        task_id = task.id
    finally:
        db.close()

    response = client.get("/api/ai-employees/tianwang/detail", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["readonly"] is True
    assert data["employee"]["employee_code"] == "tianwang"
    assert data["department"] == "研发交付军团"
    assert data["role"] == "后端 API、数据库模型、迁移、权限和测试"
    assert data["current_task"] is None
    assert data["skills"] == [
        {
            "skill_code": "backend",
            "skill_name": "backend",
            "source": "ai_employees.task_types",
            "enabled": True,
        }
    ]
    assert data["executable_task_types"] == ["backend"]
    assert data["permission_scope"]["default_permissions"] == ["task_center.execute"]
    assert data["permission_scope"]["can_auto_execute"] is False
    assert data["permission_scope"]["requires_boss_confirm_for_high_risk"] is True
    assert data["success_rate"]["total_tasks"] == 1
    assert data["success_rate"]["success_tasks"] == 1
    assert data["success_rate"]["failed_tasks"] == 0
    assert data["success_rate"]["success_rate"] == 1
    assert data["historical_tasks"][0]["task_id"] == task_id
    assert data["recent_tasks"][0]["task_id"] == task_id
    assert data["recent_tasks"][0]["has_result"] is True
    assert data["recent_tasks"][0]["review_count"] == 1
    assert "description" not in data["recent_tasks"][0]
    assert data["recent_error"] is None
    assert data["recent_logs"][0]["message"] == "[redacted]"
    assert data["safety"]["does_not_trigger_execution"] is True
    assert data["safety"]["external_api_called"] is False
    assert data["safety"]["execution_engine_modified"] is False
    assert data["safety"]["task_center_core_modified"] is False
    assert data["safety"]["high_risk_requires"] == {"boss_confirm": True, "security_audited": True}
    assert data["safety"]["dangerous_action_entrypoints_hidden"] is True
    assert "task_center_tasks" in data["data_sources"]


def test_ai_employee_detail_exposes_current_task_and_recent_error(client, owner_headers, test_db):
    db = test_db()
    try:
        running_task = TaskCenterTask(
            title="Current running task",
            status="running",
            priority="high",
            source="test",
            assigned_ai_employee_code="tianwang",
            assigned_ai_employee_name="天王：后端开发中心",
        )
        failed_task = TaskCenterTask(
            title="Recent failed task",
            status="failed",
            priority="normal",
            source="test",
            assigned_ai_employee_code="tianwang",
            assigned_ai_employee_name="天王：后端开发中心",
        )
        db.add_all([running_task, failed_task])
        db.commit()
        running_id = running_task.id
        failed_id = failed_task.id
    finally:
        db.close()

    response = client.get("/api/ai-employees/tianwang/detail", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["current_task"]["task_id"] == running_id
    assert data["current_task"]["status"] == "running"
    assert data["recent_error"]["task_id"] == failed_id
    assert data["recent_error"]["status"] == "failed"
    assert data["current_status"]["runtime_status"] == "error"
    assert {task["task_id"] for task in data["historical_tasks"]} == {running_id, failed_id}


def test_ai_employee_detail_404_for_missing_employee(client, owner_headers):
    response = client.get("/api/ai-employees/not_exists/detail", headers=owner_headers)

    assert response.status_code == 404


def test_ai_employee_detail_requires_registry_permission(client, viewer_headers):
    response = client.get("/api/ai-employees/tianwang/detail", headers=viewer_headers)

    assert response.status_code == 403


def test_ai_employee_detail_requires_login(client):
    response = client.get("/api/ai-employees/tianwang/detail")

    assert response.status_code == 401


def test_ai_employee_detail_filters_sensitive_fields(client, owner_headers):
    response = client.get("/api/ai-employees/tianwang/detail", headers=owner_headers)

    assert response.status_code == 200
    text = response.text.lower()
    forbidden = ["password_hash", "secret", "api key", "authorization", "bearer", "private_key"]
    for word in forbidden:
        assert word not in text


def test_ai_employee_detail_v2_page_structure_exists():
    html = read_detail_page()

    for text in [
        "AI员工详情",
        "员工第一眼信息",
        "AI员工",
        "部门",
        "当前状态",
        "成长分",
        "老板关心的员工信息",
        "返回AI员工中心",
        "我的身份：",
        "我负责：",
        "今天完成：",
        "我正在学习：",
        "我的成长：",
        "我的成长记录",
        "最近变化：",
        "现在几分",
        "上升趋势",
        "成长原因",
        "经验记录",
        "做过什么",
        "解决什么问题",
        "积累什么经验",
        "我正在学习的能力",
        "熟练程度",
        "什么时候会的",
        "用过几次",
        "做成比例",
    ]:
        assert text in html


def test_ai_employee_detail_v2_empty_states_and_security_controls():
    html = read_detail_page()

    for text in ["暂无数据", "只看不操作", "老板确认", "安全记录", "readonly=true", "boss_confirm=true", "security_audited=true"]:
        assert text in html

    forbidden = [
        "employee_id",
        "数据库字段",
        "技术日志",
        "API信息",
        "数据库信息",
        "Skill",
        "Memory",
        "Timeline",
        "启动员工",
        "自动运行",
        "修改权限",
        "自动升级",
        "执行任务",
        "立即执行",
        "开始任务",
        "升级员工",
        "授权员工",
        "修改员工",
        "自动授权",
        "/api/execution",
        "/api/brain/start",
        "/ai-execution.html",
        "OpenClaw",
        "n8n",
    ]
    for text in forbidden:
        assert text not in html
