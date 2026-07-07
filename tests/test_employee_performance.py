from __future__ import annotations

from sqlalchemy import event

from backend.employee_performance import build_ai_employee_business_board, build_employee_leaderboard, build_employee_performance_stats
from backend.models import TaskCenterTask
from backend.task_queue import ORCHESTRATOR_QUEUE_NAME


def seed_performance_tasks(test_db):
    db = test_db()
    try:
        db.add_all(
            [
                TaskCenterTask(
                    title="完成商品优化",
                    description="商品详情页优化",
                    status="completed",
                    assigned_ai_employee_code="tianwang",
                    assigned_ai_employee_name="天王：后端开发中心",
                ),
                TaskCenterTask(
                    title="广告预算异常复盘",
                    description="涉及广告预算风险",
                    status="failed",
                    assigned_ai_employee_code="tianwang",
                    assigned_ai_employee_name="天王：后端开发中心",
                ),
                TaskCenterTask(
                    title="运行后端任务",
                    description="常规任务",
                    status="running",
                    assigned_ai_employee_code="tiantong",
                    assigned_ai_employee_name="天统：AI总指挥",
                ),
                TaskCenterTask(
                    title="部署检查",
                    description="deploy health check",
                    status="assigned",
                    assigned_ai_employee_code="tiantong",
                    assigned_ai_employee_name="天统：AI总指挥",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()


def test_employee_performance_stats_include_counts_success_duration_failure_and_risk(test_db):
    seed_performance_tasks(test_db)
    db = test_db()
    try:
        stats = build_employee_performance_stats(db)
    finally:
        db.close()

    by_employee = {row["employee_code"]: row for row in stats}
    tianwang = by_employee["tianwang"]
    assert tianwang["completed_task_count"] == 1
    assert tianwang["failed_task_count"] == 1
    assert tianwang["success_rate"] == 0.5
    assert tianwang["risk_count"] == 1
    assert "average_duration_hours" in tianwang
    assert tianwang["estimated_cost"]["can_auto_spend_money"] is False
    assert tianwang["safety"]["can_auto_adjust_permission"] is False
    assert tianwang["safety"]["can_auto_modify_employee_config"] is False


def test_employee_leaderboard_returns_best_growth_and_risk_employee(test_db):
    seed_performance_tasks(test_db)
    db = test_db()
    try:
        stats = build_employee_performance_stats(db)
    finally:
        db.close()
    leaderboard = build_employee_leaderboard(stats)

    assert leaderboard["best_employee"]["employee_code"]
    assert leaderboard["growth_employee"]["employee_code"]
    assert leaderboard["risk_employee"]["risk_count"] >= 1
    assert leaderboard["ranking"]
    assert leaderboard["safety"]["can_auto_adjust_permission"] is False


def test_ai_employee_business_board_connects_growth_tianbrain_and_tiancang_without_queue(test_db):
    seed_performance_tasks(test_db)
    db = test_db()
    try:
        board = build_ai_employee_business_board(db)
    finally:
        db.close()

    assert board["board_name"] == "AI员工经营看板"
    assert board["current_running_employees"]
    assert board["today_tasks"] >= 4
    assert board["success_rate"] == 0.5
    assert board["cost"]["can_auto_spend_money"] is False
    assert {"Employee Growth Center", "TianBrain", "TianCang"} <= set(board["connected_centers"])
    assert board["growth_cards"]
    assert board["growth_cards"][0]["tianbrain_next_optimization"]
    assert board["growth_cards"][0]["tiancang_sop_suggestions"]
    assert all(card["can_auto_apply"] is False for card in board["growth_cards"])
    assert board["safety"]["can_auto_modify_employee_config"] is False

    redis_client = __import__("backend.database", fromlist=["get_redis"]).get_redis()
    assert redis_client.llen(ORCHESTRATOR_QUEUE_NAME) == 0


def test_ceo_dashboard_includes_ai_employee_business_board(client, owner_headers, test_db):
    seed_performance_tasks(test_db)
    response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)

    assert response.status_code == 200
    board = response.json()["ai_employee_business_board"]
    assert board["board_name"] == "AI员工经营看板"
    assert board["employee_performance"]
    assert board["leaderboard"]["best_employee"]
    assert board["safety"]["analysis_only"] is True
    assert board["safety"]["can_auto_adjust_permission"] is False


def test_employee_performance_does_not_write_database(client, owner_headers, test_db):
    seed_performance_tasks(test_db)
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
