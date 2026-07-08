from __future__ import annotations

from backend.brain_execution.models import BrainExecutionContext, BrainExecutionRun, BrainWorkerStatus
from backend.brain_execution.planner import approve_run, create_plan
from backend.brain_execution.queue import enqueue_execution, get_queue_status
from backend.brain_execution.state_machine import ExecutionState, transition_run
from backend.brain_execution.worker import process_next_execution
from backend.brain_tool_router.models import BrainExecutionLog


def create_approved_execution(db, goal: str = "分析近期爆款手表趋势") -> int:
    plan = create_plan(db, goal, created_by="owner")
    execution_id = plan["execution_id"]
    approved = approve_run(
        db,
        execution_id,
        approve_user="owner",
        decision="approved",
        reason="test approval",
        boss_confirm=True,
        security_audited=True,
    )
    assert approved["status"] == "APPROVED"
    return execution_id


def queue_execution(db, execution_id: int, **queue_kwargs):
    run = db.get(BrainExecutionRun, execution_id)
    transition_run(db, run, ExecutionState.QUEUED)
    db.commit()
    return enqueue_execution(execution_id, **queue_kwargs)


def test_brain_execution_start_enqueues_approved_task(client, owner_headers):
    plan = client.post("/api/brain/plan", headers=owner_headers, json={"goal": "分析近期爆款手表趋势"})
    execution_id = plan.json()["execution_id"]
    approve = client.post(
        "/api/brain/approve",
        headers=owner_headers,
        json={"execution_id": execution_id, "boss_confirm": True, "security_audited": True},
    )
    assert approve.status_code == 200

    start = client.post("/api/brain/start", headers=owner_headers, json={"execution_id": execution_id})
    assert start.status_code == 200
    assert start.json()["queued"] is True
    assert start.json()["status"] == "QUEUED"
    assert start.json()["queue_item"]["execution_id"] == execution_id

    status = client.get("/api/brain/queue/status", headers=owner_headers)
    assert status.status_code == 200
    assert status.json()["waiting"] >= 1


def test_worker_consumes_queue_and_marks_success(test_db):
    db = test_db()
    try:
        execution_id = create_approved_execution(db)
        queue_execution(db, execution_id)
        result = process_next_execution(db, timeout=1, worker_id="worker-a")
        assert result["run"]["status"] == "SUCCESS"
        run = db.get(BrainExecutionRun, execution_id)
        assert run.status == "SUCCESS"
        assert run.worker_id == "worker-a"
        assert run.started_at is not None
        assert run.finished_at is not None
        assert db.query(BrainExecutionContext).filter(BrainExecutionContext.execution_id == execution_id).count() >= 1
        assert db.query(BrainWorkerStatus).filter(BrainWorkerStatus.worker_id == "worker-a").one().status == "idle"
        assert db.query(BrainExecutionLog).filter(BrainExecutionLog.run_id == str(execution_id)).count() >= 4
    finally:
        db.close()


def test_worker_blocks_unapproved_execution(test_db):
    db = test_db()
    try:
        plan = create_plan(db, "分析近期爆款手表趋势", created_by="owner")
        execution_id = plan["execution_id"]
        enqueue_execution(execution_id)
        result = process_next_execution(db, timeout=1)
        assert result["status"] == "blocked"
        assert db.get(BrainExecutionRun, execution_id).status == "WAIT_APPROVAL"
    finally:
        db.close()


def test_worker_retries_failure_then_marks_failed(test_db):
    db = test_db()
    try:
        execution_id = create_approved_execution(db)
        queue_execution(db, execution_id, max_retry=1, payload={"simulate_failure": True})
        first = process_next_execution(db, timeout=1)
        assert first["status"] == "retrying"
        second = process_next_execution(db, timeout=1)
        assert second["status"] == "failed"
        run = db.get(BrainExecutionRun, execution_id)
        assert run.status == "FAILED"
        assert run.retry_count == 1
    finally:
        db.close()


def test_worker_timeout_records_timeout_status(test_db):
    db = test_db()
    try:
        execution_id = create_approved_execution(db)
        queue_execution(db, execution_id, max_retry=0, payload={"simulate_timeout": True})
        result = process_next_execution(db, timeout=1)
        assert result["status"] == "timeout"
        assert db.get(BrainExecutionRun, execution_id).status == "TIMEOUT"
        logs = db.query(BrainExecutionLog).filter(BrainExecutionLog.run_id == str(execution_id)).all()
        assert any(row.action == "worker_timeout" for row in logs)
    finally:
        db.close()


def test_queue_status_schema(test_db):
    db = test_db()
    try:
        execution_id = create_approved_execution(db)
        queue_execution(db, execution_id, priority="high")
        status = get_queue_status()
        assert {"waiting", "running", "success", "failed", "timeout", "recent", "priority_waiting"} <= set(status)
        assert status["waiting"] >= 1
        assert status["priority_waiting"]["high"] >= 1
    finally:
        db.close()


def test_priority_queue_consumes_high_before_normal(test_db):
    db = test_db()
    try:
        normal_execution = create_approved_execution(db, "整理普通日报")
        high_execution = create_approved_execution(db, "紧急分析高优先级销售异常")
        queue_execution(db, normal_execution, priority="normal")
        queue_execution(db, high_execution, priority="high")

        result = process_next_execution(db, timeout=1, worker_id="priority-worker")
        assert result["run"]["id"] == high_execution
        assert db.get(BrainExecutionRun, high_execution).status == "SUCCESS"
        assert db.get(BrainExecutionRun, normal_execution).status == "QUEUED"
    finally:
        db.close()


def test_worker_status_context_and_dashboard_summary_apis(client, owner_headers, test_db):
    db = test_db()
    try:
        execution_id = create_approved_execution(db)
        queue_execution(db, execution_id, priority="high")
        result = process_next_execution(db, timeout=1, worker_id="summary-worker")
        assert result["run"]["status"] == "SUCCESS"
    finally:
        db.close()

    workers = client.get("/api/brain/workers/status", headers=owner_headers)
    assert workers.status_code == 200
    assert any(row["worker_id"] == "summary-worker" and row["heartbeat"] for row in workers.json()["workers"])

    context = client.get(f"/api/brain/executions/{execution_id}/context", headers=owner_headers)
    assert context.status_code == 200
    assert context.json()["contexts"]
    assert all("token" not in str(row).lower() for row in context.json()["contexts"])

    summary = client.get("/api/ceo-dashboard/brain-execution-summary", headers=owner_headers)
    assert summary.status_code == 200
    data = summary.json()
    assert data["mode"] == "simulation"
    assert data["worker_count"] >= 1
    assert data["success_rate"] >= 0
    assert "shell" in data["forbidden_actions"]
