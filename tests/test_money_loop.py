def test_money_loop_requires_auth(client):
    response = client.post("/api/money/loop/start", json={"seed": {"topic": "AI赚钱"}, "cycles": 1})
    assert response.status_code == 401


def test_money_loop_start_runs_bounded_cycles_and_writes_results(client, owner_headers):
    response = client.post(
        "/api/money/loop/start",
        headers=owner_headers,
        json={
            "seed": {
                "topic": "夏季爆品",
                "keyword": "防晒衣",
                "sku": "SKU-MONEY",
                "stock": 80,
                "current_price": 99,
                "views": 2000,
                "likes": 160,
                "comments": 20,
                "shares": 10,
            },
            "cycles": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert len(body["status"]["results"]) == 2
    assert len(body["task_ids"]) == 2
    first = body["status"]["results"][0]
    assert first["trend"]["heat_level"] == "high"
    assert first["content"]["engine"] == "content"
    assert first["publish_result"]["external_publish"] is False
    assert first["product_binding"]["auto_bind"] is True
    assert first["metrics"]["external_collection"] is False
    assert first["feedback"]["reusable_as_input"] is True
    assert first["external_actions"] == []


def test_money_loop_status_and_stop(client, owner_headers):
    start = client.post("/api/money/loop/start", headers=owner_headers, json={"seed": {"topic": "状态测试"}, "cycles": 1})
    assert start.status_code == 200

    status_response = client.get("/api/money/loop/status", headers=owner_headers)
    assert status_response.status_code == 200
    assert status_response.json()["status"]["running"] is True
    assert status_response.json()["status"]["external_execution"] is False

    stop_response = client.post("/api/money/loop/stop", headers=owner_headers)
    assert stop_response.status_code == 200
    assert stop_response.json()["status"]["running"] is False


def test_money_optimize_updates_strategy_and_writes_result(client, owner_headers):
    response = client.post(
        "/api/money/optimize",
        headers=owner_headers,
        json={"feedback": {"direction": "improve_hook_and_offer", "metrics": {"revenue": 80}}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["external_execution"] is False
    assert body["result"]["strategy"]["content_type"] == "xiaohongshu"
    assert body["task_id"]


def test_money_loop_accepts_api_key(client, monkeypatch, owner_headers, test_db):
    from uuid import uuid4

    from backend.brain_orchestrator.planner import resolve_graph_ownership
    from backend.models import TaskCenterAuditLog, TaskCenterResult, TaskCenterTask, User
    from backend.task_center_ownership import TASK_OWNERSHIP_FIELDS, bind_task_ownership

    def database_state():
        db = test_db()
        try:
            return {
                model.__tablename__: tuple(
                    tuple(getattr(row, column.name) for column in model.__table__.columns)
                    for row in db.query(model).order_by(*model.__table__.primary_key.columns).all()
                )
                for model in (User, TaskCenterTask, TaskCenterResult, TaskCenterAuditLog)
            }
        finally:
            db.close()

    api_key = uuid4().hex
    monkeypatch.setenv("AUTOMATION_API_KEY", api_key)
    api_key_headers = {"X-API-Key": api_key}
    request_payload = {"seed": {"topic": "API Key 闭环", "views": 1000, "likes": 60}, "cycles": 1}
    client.cookies.clear()

    db = test_db()
    try:
        boss = db.query(User).filter(User.username == "boss").one()
        foreign_task = TaskCenterTask(
            title="Foreign money-loop sentinel",
            status="completed",
            source="sprint18_dual_engine",
            assigned_ai_employee_code="foreign_money_loop",
            assigned_ai_employee_name="foreign_money_loop",
            created_by_id=boss.id,
            updated_by_id=boss.id,
        )
        bind_task_ownership(db, foreign_task, user=boss)
        db.add(foreign_task)
        db.flush()
        foreign_result = TaskCenterResult(
            task_id=foreign_task.id,
            ai_employee_code="foreign_money_loop",
            ai_employee_name="foreign_money_loop",
            result_content='{"foreign_money_loop": true}',
            attachments_json="[]",
            submitted_by_id=boss.id,
        )
        db.add(foreign_result)
        db.commit()
        foreign_task_id = foreign_task.id
        foreign_result_id = foreign_result.id
        foreign_task_before = tuple(
            getattr(foreign_task, column.name) for column in TaskCenterTask.__table__.columns
        )
        foreign_result_before = tuple(
            getattr(foreign_result, column.name) for column in TaskCenterResult.__table__.columns
        )
    finally:
        db.close()

    before_api_key_only = database_state()
    api_key_only = client.post(
        "/api/money/loop/start",
        headers=api_key_headers,
        json=request_payload,
    )
    assert api_key_only.status_code == 401
    assert set(api_key_only.json()) == {"detail"}
    assert "Foreign money-loop sentinel" not in api_key_only.text
    assert "foreign_money_loop" not in api_key_only.text
    assert not any(api_key in value for value in (api_key_only.text,))
    assert database_state() == before_api_key_only

    owner_before = database_state()
    owner_response = client.post(
        "/api/money/loop/start",
        headers={**owner_headers, **api_key_headers},
        json=request_payload,
    )

    assert owner_response.status_code == 200
    body = owner_response.json()
    assert body["ok"] is True
    assert len(body["task_ids"]) == len(body["status"]["results"]) == 1
    assert body["status"]["results"][0]["publish_result"]["status"] == "published_mock"
    assert "Foreign money-loop sentinel" not in owner_response.text
    assert "foreign_money_loop" not in owner_response.text

    db = test_db()
    try:
        owner = db.query(User).filter(User.username == "owner").one()
        owner_scope = resolve_graph_ownership(db, owner)
        task = db.get(TaskCenterTask, body["task_ids"][0])
        assert task is not None
        assert tuple(getattr(task, field) for field in TASK_OWNERSHIP_FIELDS) == (
            owner_scope.tenant_id,
            owner_scope.company_id,
            owner_scope.requester_id,
            owner_scope.store_scope_key,
            owner_scope.ownership_scope_key,
        )
        assert task.source == "sprint18_dual_engine"
        assert task.created_by_id == task.updated_by_id == owner.id
        results = db.query(TaskCenterResult).filter(TaskCenterResult.task_id == task.id).all()
        assert len(results) == 1
        assert results[0].submitted_by_id == owner.id
        audits = db.query(TaskCenterAuditLog).filter(TaskCenterAuditLog.task_id == task.id).all()
        assert audits == []
        assert not any(
            api_key in str(value)
            for value in (
                owner_response.text,
                task.title,
                task.description,
                task.split_plan,
                task.summary,
                results[0].result_content,
                results[0].attachments_json,
            )
        )
        foreign_task_after = db.get(TaskCenterTask, foreign_task_id)
        foreign_result_after = db.get(TaskCenterResult, foreign_result_id)
        assert foreign_task_after.requester_id != task.requester_id
        assert tuple(
            getattr(foreign_task_after, column.name) for column in TaskCenterTask.__table__.columns
        ) == foreign_task_before
        assert tuple(
            getattr(foreign_result_after, column.name) for column in TaskCenterResult.__table__.columns
        ) == foreign_result_before
    finally:
        db.close()

    owner_after = database_state()
    assert len(owner_after["task_center_tasks"]) == len(owner_before["task_center_tasks"]) + 1
    assert len(owner_after["task_center_results"]) == len(owner_before["task_center_results"]) + 1
    assert owner_after["task_center_audit_logs"] == owner_before["task_center_audit_logs"]
    assert owner_after["users"] == owner_before["users"]
