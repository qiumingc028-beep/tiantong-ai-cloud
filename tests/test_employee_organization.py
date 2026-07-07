from __future__ import annotations

from sqlalchemy import event

from backend.employee_organization import (
    build_department_system,
    build_employee_organization_center,
    build_employee_relationships,
    build_organization_permission_matrix,
)
from backend.models import AiEmployee, TaskCenterTask
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


def seed_organization_employees(test_db):
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
                    employee_code="tiance_strategy",
                    employee_name="天策：策略分析中心",
                    legion="经营策略军团",
                    duty="策略分析",
                    status="active",
                    task_types='["strategy"]',
                    default_permissions="[]",
                    is_legacy=False,
                    sort_order=50,
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
        db.add(
            TaskCenterTask(
                title="商品优化任务",
                status="assigned",
                assigned_ai_employee_code="tianshang",
                assigned_ai_employee_name="天商：商品中心",
            )
        )
        db.commit()
    finally:
        db.close()


def test_department_system_contains_department_leader_and_employee_list(test_db):
    seed_organization_employees(test_db)
    db = test_db()
    try:
        departments = build_department_system(db)
    finally:
        db.close()

    by_department = {row["department"]: row for row in departments}
    assert by_department["研发交付军团"]["leader_employee_code"] == "tiantong"
    assert by_department["数据资产军团"]["leader_employee_code"] == "tianshu"
    assert by_department["电商经营军团"]["employees"][0]["employee_code"] == "tianshang"
    assert by_department["电商经营军团"]["active_task_count"] == 1
    assert by_department["电商经营军团"]["safety"]["can_auto_change_leader"] is False


def test_employee_relationships_include_manager_subordinates_and_collaborators(test_db):
    seed_organization_employees(test_db)
    db = test_db()
    try:
        relationships = build_employee_relationships(db)
    finally:
        db.close()

    by_employee = {row["employee_code"]: row for row in relationships}
    assert by_employee["tiantong"]["is_top_dispatcher"] is True
    assert by_employee["tianshu"]["manager_employee_code"] == "tiantong"
    assert any(row["employee_code"] == "tiance_strategy" for row in by_employee["tianshu"]["collaboration_employees"])
    assert by_employee["tianshang"]["manager_employee_code"] == "tiantong"
    assert by_employee["tianshang"]["safety"]["can_auto_change_manager"] is False


def test_organization_permissions_enforce_roles_and_tian_shen_gate(test_db):
    seed_organization_employees(test_db)
    db = test_db()
    try:
        permissions = build_organization_permission_matrix(db)
    finally:
        db.close()

    by_employee = {row["employee_code"]: row for row in permissions}
    assert by_employee["tiantong"]["organization_role"] == "top_dispatcher"
    assert by_employee["tiantong"]["can_dispatch_company_wide"] is True
    assert by_employee["tianshu"]["organization_role"] == "department_leader"
    assert by_employee["tianshu"]["can_assign_task"] is True
    assert by_employee["tianshang"]["organization_role"] == "department_leader"
    assert by_employee["tianshang"]["can_change_permission"] is False
    assert by_employee["tianshang"]["permission_change_gate"]["center"] == "TianShen"
    assert by_employee["tianshang"]["permission_change_gate"]["decision"] in {"YELLOW", "RED"}
    assert by_employee["tianshang"]["permission_change_gate"]["allowed"] is False
    assert by_employee["tianshang"]["safety"]["can_auto_expand_permission"] is False


def test_employee_organization_center_connects_capability_workspace_performance_without_queue(test_db):
    seed_organization_employees(test_db)
    db = test_db()
    try:
        center = build_employee_organization_center(db)
    finally:
        db.close()

    assert center["center"] == "AI Employee Organization Center"
    assert center["summary"]["department_count"] >= 3
    assert center["summary"]["top_dispatcher"] == "tiantong"
    assert center["capability_connection"]["source"] == "Employee Capability Center"
    assert center["workspace_connection"]["source"] == "Employee Workspace"
    assert center["performance_connection"]["source"] == "Employee Performance Center"
    assert center["performance_connection"]["board"]["board_name"] == "AI员工经营看板"
    assert center["safety"]["permission_change_requires_tian_shen"] is True
    assert center["safety"]["can_auto_expand_permission"] is False
    assert center["safety"]["can_auto_modify_employee_config"] is False

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def test_ceo_dashboard_includes_ai_employee_organization_board(client, owner_headers, test_db):
    seed_organization_employees(test_db)
    response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)

    assert response.status_code == 200
    board = response.json()["ai_employee_organization_board"]
    assert board["center"] == "AI Employee Organization Center"
    assert board["departments"]
    assert board["employee_relationships"]
    assert board["organization_permissions"]
    assert board["safety"]["can_auto_change_organization"] is False


def test_employee_organization_center_does_not_write_database(client, owner_headers, test_db):
    seed_organization_employees(test_db)
    db = test_db()
    engine = db.get_bind()
    statements = []

    def capture_write(_conn, _cursor, statement, _parameters, _context, _executemany):
        verb = statement.strip().split(maxsplit=1)[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"}:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_write)
    try:
        response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)
        assert response.status_code == 200
        assert statements == []
    finally:
        event.remove(engine, "before_cursor_execute", capture_write)
        db.close()
