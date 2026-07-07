from __future__ import annotations

from sqlalchemy import event

from backend.employee_command_dashboard import build_employee_command_dashboard, build_employee_detail
from backend.models import AiEmployee, TaskCenterTask
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


def seed_command_dashboard_data(test_db):
    db = test_db()
    try:
        db.add_all(
            [
                AiEmployee(
                    employee_code="tianshu",
                    employee_name="天数：数据分析中心",
                    legion="数据资产军团",
                    duty="数据分析",
                    status="active",
                    task_types='["data_analysis"]',
                    default_permissions="[]",
                    is_legacy=False,
                    sort_order=40,
                ),
                AiEmployee(
                    employee_code="tianshang",
                    employee_name="天商：商品中心",
                    legion="电商经营军团",
                    duty="商品优化",
                    status="active",
                    task_types='["ecommerce"]',
                    default_permissions="[]",
                    is_legacy=False,
                    sort_order=60,
                ),
            ]
        )
        db.add_all(
            [
                TaskCenterTask(
                    title="执行数据分析",
                    description="常规数据分析",
                    status="running",
                    assigned_ai_employee_code="tianshu",
                    assigned_ai_employee_name="天数：数据分析中心",
                ),
                TaskCenterTask(
                    title="完成商品优化",
                    description="商品页面优化",
                    status="completed",
                    assigned_ai_employee_code="tianshang",
                    assigned_ai_employee_name="天商：商品中心",
                ),
                TaskCenterTask(
                    title="广告预算异常",
                    description="广告预算和投放策略需要审批",
                    status="failed",
                    assigned_ai_employee_code="tianshang",
                    assigned_ai_employee_name="天商：商品中心",
                ),
                TaskCenterTask(
                    title="等待老板审批",
                    description="权限变更预览",
                    status="created",
                    assigned_ai_employee_code="tiantong",
                    assigned_ai_employee_name="天统：AI总指挥",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()


def test_employee_command_dashboard_overview_counts_online_running_success_risk_and_approval(test_db):
    seed_command_dashboard_data(test_db)
    db = test_db()
    try:
        dashboard = build_employee_command_dashboard(db)
    finally:
        db.close()

    overview = dashboard["overview"]
    assert dashboard["center"] == "AI Employee Command Dashboard"
    assert overview["total_ai_employees"] >= 4
    assert overview["online_employees"] >= 4
    assert overview["executing_task_count"] == 1
    assert overview["success_rate"] == 0.5
    assert overview["risk_count"] >= 2
    assert overview["pending_approval_tasks"] >= 2
    assert overview["can_auto_execute_task"] is False
    assert overview["can_auto_modify_permission"] is False


def test_employee_command_dashboard_organization_view_contains_core_tree_and_capability_tags(test_db):
    seed_command_dashboard_data(test_db)
    db = test_db()
    try:
        dashboard = build_employee_command_dashboard(db)
    finally:
        db.close()

    organization = dashboard["organization_view"]
    assert organization["root"]["employee_code"] == "tiantong"
    child_codes = {row["employee_code"] for row in organization["root"]["children"]}
    assert {"tiangong", "tianwang", "tianyan_frontend", "tianjian_test", "tiandun_ops", "tianjian_audit", "tiancai_data", "tiancang"} <= child_codes
    assert any("天工（架构）" in row for row in organization["tree_text"])
    assert organization["supports"] == ["查看上下级", "查看负责人", "查看能力标签"]
    assert organization["safety"]["can_auto_change_manager"] is False
    assert organization["safety"]["can_auto_create_employee"] is False


def test_employee_command_dashboard_detail_shows_identity_skill_tasks_learning_and_level(test_db):
    seed_command_dashboard_data(test_db)
    db = test_db()
    try:
        detail = build_employee_detail(db, "tianshang")
    finally:
        db.close()

    assert detail["identity"]["employee_code"] == "tianshang"
    assert "ecommerce_operation" in detail["skills"]
    assert detail["completed_tasks"] == 1
    assert detail["success_rate"] == 0.5
    assert detail["failure_records"] and detail["failure_records"] != ["暂无失败记录"]
    assert detail["learning_records"]["tianbrain_next_optimization"]
    assert detail["learning_records"]["tiancang_sop_suggestions"]
    assert detail["current_capability_level"] == "risk_control_required"
    assert detail["safety"]["readonly_detail"] is True
    assert detail["safety"]["can_auto_modify_permission"] is False
    assert detail["safety"]["can_auto_execute_task"] is False


def test_employee_command_dashboard_api_requires_login(client, test_db):
    seed_command_dashboard_data(test_db)
    assert client.get("/api/ceo-dashboard/employee-command-dashboard").status_code == 401


def test_employee_command_dashboard_api_rejects_low_permission(client, viewer_headers, test_db):
    seed_command_dashboard_data(test_db)
    assert client.get("/api/ceo-dashboard/employee-command-dashboard", headers=viewer_headers).status_code == 403


def test_employee_command_dashboard_api_allows_owner(client, owner_headers, test_db):
    seed_command_dashboard_data(test_db)
    response = client.get("/api/ceo-dashboard/employee-command-dashboard", headers=owner_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["overview"]["total_ai_employees"] >= 4
    assert body["tianshen_connection"]["can_auto_approve"] is False
    assert body["tianbrain_connection"]["optimization_mode"] == "suggestion_only"


def test_employee_command_dashboard_detail_api_and_404(client, owner_headers, test_db):
    seed_command_dashboard_data(test_db)
    response = client.get("/api/ceo-dashboard/employee-command-dashboard/employees/tianshang", headers=owner_headers)
    assert response.status_code == 200
    assert response.json()["identity"]["employee_code"] == "tianshang"

    missing = client.get("/api/ceo-dashboard/employee-command-dashboard/employees/not_exists", headers=owner_headers)
    assert missing.status_code == 404


def test_ceo_dashboard_summary_includes_employee_command_dashboard(client, owner_headers, test_db):
    seed_command_dashboard_data(test_db)
    response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)

    assert response.status_code == 200
    dashboard = response.json()["ai_employee_command_dashboard"]
    assert dashboard["center"] == "AI Employee Command Dashboard"
    assert dashboard["organization_view"]["root"]["employee_code"] == "tiantong"
    assert dashboard["safety"]["readonly"] is True


def test_employee_command_dashboard_is_readonly_and_does_not_queue_or_write(client, owner_headers, test_db):
    seed_command_dashboard_data(test_db)
    db = test_db()
    engine = db.get_bind()
    statements = []

    def capture_write(_conn, _cursor, statement, _parameters, _context, _executemany):
        verb = statement.strip().split(maxsplit=1)[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"}:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_write)
    try:
        response = client.get("/api/ceo-dashboard/employee-command-dashboard", headers=owner_headers)
        assert response.status_code == 200
        assert statements == []
    finally:
        event.remove(engine, "before_cursor_execute", capture_write)
        db.close()

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0
